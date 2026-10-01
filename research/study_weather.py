"""Does adding archived WEATHER FORECASTS improve Bereshit's day-ahead price forecast?

Walk-forward, no look-ahead:
 * prices up to D-1 only (published before the D-1 12:00 CET gate)
 * weather = Open-Meteo *_previous_day2 forecasts (model run ~48h before each hour of D)
 * models refit every day on a rolling window of past days only
 * hyper-parameters chosen on the first half (Oct-Mar); the second half (Apr-Sep) is untouched test
Profit = locked schedule from the forecast, settled at actual prices (same LP as the live engine).
"""
import sys, json, csv, glob, pathlib, datetime as dt
import numpy as np
from zoneinfo import ZoneInfo
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from bereshit.config import Battery
from bereshit.optimizer import schedule, settle

D = pathlib.Path(__file__).parent / "data"
TZ = ZoneInfo("Europe/Budapest"); S = 96; DT = np.full(S, 0.25)
BAT = Battery(power_mw=1.0, energy_mwh=4.0)

def to96(x):
    x = np.asarray(x, float)
    if len(x) == S: return x
    return np.interp(np.linspace(0, 1, S, endpoint=False) + .5 / S, np.linspace(0, 1, len(x), endpoint=False) + .5 / len(x), x)

# ---------- prices ----------
P = {}
with open(D / "hu_prices.csv") as f:
    for r in csv.DictReader(f):
        if r["price"] in ("", "None"): continue
        t = dt.datetime.fromtimestamp(int(r["unix"]), dt.timezone.utc).astimezone(TZ)
        P.setdefault(t.date(), []).append(float(r["price"]))
P = {d: np.array(v) for d, v in P.items() if len(v) in (23, 24, 25, 92, 96, 100)}
DAYS = sorted(P)
P96 = {d: to96(v) for d, v in P.items()}

# ---------- weather (hourly UTC -> local day -> 96 slots) ----------
def load_wx(lead):
    W = {}
    for fn in glob.glob(str(D / "wx_*.csv")):
        loc = pathlib.Path(fn).stem[3:]
        per = {}
        with open(fn) as f:
            for r in csv.DictReader(f):
                t = dt.datetime.fromisoformat(r["time"]).replace(tzinfo=dt.timezone.utc).astimezone(TZ)
                for k, v in r.items():
                    if not k.endswith(f"_previous_day{lead}"): continue
                    var = k.replace(f"_previous_day{lead}", "")
                    per.setdefault((var, t.date()), []).append(np.nan if v in ("", "None") else float(v))
        for (var, d), v in per.items():
            if len(v) in (23, 24, 25):
                W.setdefault(d, {})[f"{loc}:{var}"] = np.repeat(to96(np.array(v))[::4] if len(v) != 24 else np.array(v), 4) if False else to96(np.repeat(np.array(v), 4))
    return W

def feats(Wd):
    """Aggregate per-slot weather features for one day; None if incomplete."""
    if Wd is None: return None
    g = lambda locs, var: np.nanmean([Wd[f"{l}:{var}"] for l in locs if f"{l}:{var}" in Wd], axis=0)
    hu = ["hu_budapest", "hu_debrecen", "hu_szeged", "hu_pecs", "hu_gyor"]
    out = {
        "sol_hu": g(hu, "shortwave_radiation") / 100,
        "sol_region": g(["at_vienna", "de_south", "ro_bucharest", "pl_center", "sk_kosice"], "shortwave_radiation") / 100,
        "temp_hu": g(hu, "temperature_2m") / 10,
        "wind_de": g(["de_north"], "wind_speed_100m") / 5,
        "wind_ro": g(["ro_dobrogea"], "wind_speed_100m") / 5,
        "wind_hu": g(hu + ["at_vienna"], "wind_speed_100m") / 5,
    }
    if any(np.isnan(v).any() for v in out.values()): return None
    out["hdd"] = np.clip(1.6 - out["temp_hu"], 0, None)   # heating below 16C
    out["cdd"] = np.clip(out["temp_hu"] - 2.4, 0, None)   # cooling above 24C
    return out

# ---------- forecasters ----------
def hist(i, k):
    j = i - k
    return P96[DAYS[j]] if j >= 0 else None

def blend(i):
    return 0.5 * hist(i, 1) + 0.25 * hist(i, 7) + 0.25 * np.mean([hist(i, k) for k in range(1, 8)], 0)

WXK = ["sol_hu", "sol_region", "wind_de", "wind_ro", "wind_hu", "hdd", "cdd"]

def xrow(i, F, mode):
    """Feature matrix (96, k) for target day index i."""
    d = DAYS[i]; b = blend(i); d1 = hist(i, 1); wd = d.weekday()
    cols = [b, d1, np.full(S, float(wd >= 5)), np.full(S, float(wd == 0)), np.full(S, float(DAYS[i - 1].weekday() >= 5))]
    if mode == "price": return np.stack(cols, 1)
    fD, fY = F.get(d), F.get(DAYS[i - 1])
    if fD is None or fY is None: return None
    if mode in ("res", "res2"):
        f7 = [F.get(DAYS[i - k]) for k in range(1, 8)]
        if any(x is None for x in f7): return None
        keys = WXK if mode == "res" else ["sol_region", "wind_de", "wind_ro", "hdd"]
        cols = [np.full(S, float(wd >= 5)) - float(DAYS[i - 1].weekday() >= 5)]
        for k in keys:
            cols.append(fD[k] - fY[k])
            cols.append(fD[k] - np.mean([x[k] for x in f7], 0))
        return np.stack(cols, 1)
    for k in WXK:
        cols.append(fD[k])
        cols.append(fD[k] - fY[k])          # change vs yesterday: what the blend cannot see
    return np.stack(cols, 1)

def ridge_fc(i, F, mode, win, lam, pool):
    Xt = xrow(i, F, mode)
    if Xt is None: return blend(i)
    X, Y = [], []
    for j in range(max(8, i - win), i):
        if len(P[DAYS[j]]) != S: continue
        x = xrow(j, F, mode)
        if x is not None: X.append(x); Y.append(P96[DAYS[j]] - (blend(j) if mode.startswith("res") else 0))
    if len(X) < 21: return blend(i)
    X, Y = np.stack(X), np.stack(Y)
    out = np.empty(S); k = X.shape[2]
    groups = [list(range(s, min(S, s + pool))) for s in range(0, S, pool)]
    for gsl in groups:
        A = X[:, gsl, :].reshape(-1, k); y = Y[:, gsl].reshape(-1)
        mu, sd = A.mean(0), A.std(0) + 1e-9
        Z = np.column_stack([np.ones(len(A)), (A - mu) / sd])
        R = lam * np.eye(k + 1); R[0, 0] = 0
        w = np.linalg.solve(Z.T @ Z + R, Z.T @ y)
        out[gsl] = np.column_stack([np.ones(len(gsl)), (Xt[gsl] - mu) / sd]) @ w
    return out + (blend(i) if mode.startswith("res") else 0)

def evaluate(fc_fn, lo, hi):
    real = perf = mae = n = loss = 0.0
    for i, d in enumerate(DAYS):
        if not (lo <= d <= hi) or len(P[d]) != S or i < 60: continue
        a = P[d]; f = fc_fn(i)
        r = settle(schedule(f, DT, BAT, 0.0), a, DT, BAT); p = settle(schedule(a, DT, BAT, 0.0), a, DT, BAT)
        real += r; perf += p; mae += np.abs(f - a).mean(); n += 1; loss += r < 0
    return dict(days=int(n), realised=round(real), perfect=round(perf), capture=round(real / perf, 4),
                mae=round(mae / n, 2), loss_days=int(loss))

if __name__ == "__main__":
    lead = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    F = {d: feats(w) for d, w in load_wx(lead).items()}
    F = {d: v for d, v in F.items() if v is not None}
    A0, A1 = dt.date(2025, 10, 1), dt.date(2026, 3, 31)
    B0, B1 = dt.date(2026, 4, 1), max(DAYS)
    print(f"price days {len(DAYS)} {DAYS[0]}..{DAYS[-1]}  weather days {len(F)} (lead day{lead})", flush=True)
    res = {"lead": lead, "train_half": f"{A0}..{A1}", "test_half": f"{B0}..{B1}", "tune": {}, "final": {}}
    res["tune"]["blend"] = evaluate(blend, A0, A1); print("blend", res["tune"]["blend"], flush=True)
    grid = [(m, w, l, p) for m in ("price", "wx", "res", "res2") for w in (90, 180) for l in (30.0, 300.0, 3000.0) for p in (4, 16)]
    for m, w, l, p in grid:
        key = f"{m}_w{w}_l{l:g}_p{p}"
        res["tune"][key] = evaluate(lambda i: ridge_fc(i, F, m, w, l, p), A0, A1)
        print(key, {k: res["tune"][key][k] for k in ("capture", "mae", "loss_days")}, flush=True)
    best = {m: max((k for k in res["tune"] if k.startswith(m + "_")), key=lambda k: res["tune"][k]["capture"]) for m in ("price", "wx", "res", "res2")}
    res["chosen_on_first_half"] = best
    def fn(key):
        if key == "blend": return blend
        m, w, l, p = key.split("_"); return lambda i: ridge_fc(i, F, m, int(w[1:]), float(l[1:]), int(p[1:]))
    for name in ["blend"] + list(best.values()):
        res["final"][name] = {"test_half": evaluate(fn(name), B0, B1), "full_year": evaluate(fn(name), A0, B1)}
        print("FINAL", name, res["final"][name], flush=True)
    (pathlib.Path(__file__).parent / "results" / f"weather_study_day{lead}.json").write_text(json.dumps(res, indent=1))
