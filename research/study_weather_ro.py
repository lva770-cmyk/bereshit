"""Project 50 (Romania): do archived WEATHER FORECASTS improve the day-ahead price forecast and the money made?

Same walk-forward design as study_weather.py (Hungary), on Romanian (OPCOM / SDAC) prices and the P50 battery
(per MW: 1 MW / 1.54 MWh usable, 88% round trip, max 2 full discharges a day, no wear charge):
 * prices up to D-1 only; weather = Open-Meteo *_previous_day2 (model run ~48 h before each hour of D, i.e. known
   before the 12:00 CET gate on D-1); *_previous_day1 kept as an optimistic reference
 * models refit every day on a rolling window of past days only
 * settings chosen on Oct-Mar; Apr-Sep is an untouched test half
Profit = schedule from the forecast, settled at actual prices (same LP as the live engine)."""
import sys, json, csv, glob, pathlib, datetime as dt
import numpy as np
from zoneinfo import ZoneInfo
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from bereshit.config import Battery
from bereshit.optimizer import schedule, settle

D = pathlib.Path(__file__).parent / "data"; ROOT = pathlib.Path(__file__).parent.parent
TZ = ZoneInfo("Europe/Budapest"); S = 96; DT = np.full(S, 0.25)
BAT = Battery(power_mw=1.0, energy_mwh=76.0 / 49.4, rte=0.88, max_cycles_per_day=2.0, wear_eur_per_mwh=0.0)

# ---------- prices: research CSV + the live engine's verified actuals ----------
P = {}
with open(D / "ro_prices.csv") as f:
    for r in csv.DictReader(f):
        v = [float(r[f"q{k}"]) for k in range(S)]; P[dt.date.fromisoformat(r["date"])] = np.array(v)
for k, rec in json.load(open(ROOT / "data-RO2.json"))["days"].items():
    if rec.get("actual") and len(rec["actual"]) == S: P.setdefault(dt.date.fromisoformat(k), np.array(rec["actual"], float))
DAYS = sorted(P)

def load_wx(lead):
    W = {}
    for fn in glob.glob(str(D / "wx_*.csv")):
        loc = pathlib.Path(fn).stem[3:]
        if loc.endswith("_obs"): continue                       # observations, not forecasts
        per = {}
        with open(fn) as f:
            for r in csv.DictReader(f):
                t = dt.datetime.fromisoformat(r["time"]).replace(tzinfo=dt.timezone.utc).astimezone(TZ)
                for k, v in r.items():
                    if not k.endswith(f"_previous_day{lead}"): continue
                    per.setdefault((k.replace(f"_previous_day{lead}", ""), t.date()), []).append(np.nan if v in ("", "None") else float(v))
        for (var, d), v in per.items():
            if len(v) in (23, 24, 25):
                v = np.array(v[:24] if len(v) == 25 else (v + v[-1:] if len(v) == 23 else v))
                W.setdefault(d, {})[f"{loc}:{var}"] = np.repeat(v, 4)
    return W

def pcurve(ws):                      # rough wind-turbine power curve: 0 below 3 m/s, full at 12 m/s
    return np.clip((ws - 3) / 9, 0, 1) ** 3

def feats(Wd):
    if Wd is None: return None
    g = lambda locs, var: np.nanmean([Wd[f"{l}:{var}"] for l in locs if f"{l}:{var}" in Wd], axis=0)
    out = {
        "wind_ro": pcurve(g(["ro_dobrogea"], "wind_speed_100m")),
        "sol_ro": g(["ro_bucharest", "ro_dobrogea"], "shortwave_radiation") / 100,
        "temp_ro": g(["ro_bucharest"], "temperature_2m") / 10,
        "sol_region": g(["hu_budapest", "hu_szeged", "at_vienna", "de_south", "pl_center", "sk_kosice"], "shortwave_radiation") / 100,
        "wind_region": pcurve(g(["hu_debrecen", "hu_gyor", "at_vienna", "pl_center"], "wind_speed_100m")),
        "wind_de": pcurve(g(["de_north"], "wind_speed_100m")),
    }
    if any(np.isnan(v).any() for v in out.values()): return None
    out["hdd"] = np.clip(1.6 - out["temp_ro"], 0, None); out["cdd"] = np.clip(out["temp_ro"] - 2.4, 0, None)
    return out

def hist(i, k):
    j = i - k
    if j < 0 or (DAYS[i] - DAYS[j]).days != k: return None
    return P[DAYS[j]]

def blend(i):
    h = [hist(i, k) for k in range(1, 8)]
    if any(x is None for x in h): return None
    return 0.5 * h[0] + 0.25 * h[6] + 0.25 * np.mean(h, 0)

KEYS = {"wx": ["wind_ro", "sol_ro", "hdd", "cdd", "sol_region", "wind_region", "wind_de"],
        "ro": ["wind_ro", "sol_ro", "hdd", "cdd"]}

def xrow(i, F, mode):
    d = DAYS[i]; wd = d.weekday(); b = blend(i)
    if b is None: return None
    fD = F.get(d); f7 = [F.get(d - dt.timedelta(days=k)) for k in range(1, 8)]
    if fD is None or any(x is None for x in f7): return None
    cols = [np.full(S, float(wd >= 5)) - float((d - dt.timedelta(days=1)).weekday() >= 5)]
    for k in KEYS[mode]:
        cols.append(fD[k] - f7[0][k])                     # change vs yesterday (what the blend cannot see)
        cols.append(fD[k] - np.mean([x[k] for x in f7], 0))  # vs last week's average
    return np.stack(cols, 1)

def ridge_fc(i, F, mode, win, lam, pool):
    """Forecast = blend + ridge correction learned from weather changes (residual model)."""
    b = blend(i); Xt = xrow(i, F, mode)
    if b is None: return None
    if Xt is None: return b
    X, Y = [], []
    for j in range(max(8, i - win), i):
        x = xrow(j, F, mode); bj = blend(j)
        if x is not None and bj is not None: X.append(x); Y.append(P[DAYS[j]] - bj)
    if len(X) < 21: return b
    X, Y = np.stack(X), np.stack(Y); out = np.empty(S); k = X.shape[2]
    for s in range(0, S, pool):
        gsl = list(range(s, min(S, s + pool)))
        A = X[:, gsl, :].reshape(-1, k); y = Y[:, gsl].reshape(-1)
        mu, sd = A.mean(0), A.std(0) + 1e-9
        Z = np.column_stack([np.ones(len(A)), (A - mu) / sd]); R = lam * np.eye(k + 1); R[0, 0] = 0
        w = np.linalg.solve(Z.T @ Z + R, Z.T @ y)
        out[gsl] = np.column_stack([np.ones(len(gsl)), (Xt[gsl] - mu) / sd]) @ w
    return b + out

PERF = {}
def evaluate(fc_fn, lo, hi, F=None):
    real = perf = mae = n = loss = cov = 0.0; daily = {}
    for i, d in enumerate(DAYS):
        if not (lo <= d <= hi): continue
        f = fc_fn(i)
        if f is None: continue
        a = P[d]
        if d not in PERF: PERF[d] = settle(schedule(a, DT, BAT, 0.0), a, DT, BAT)
        r = settle(schedule(f, DT, BAT, 0.0), a, DT, BAT)
        real += r; perf += PERF[d]; mae += np.abs(f - a).mean(); n += 1; loss += r < 0; daily[d.isoformat()] = round(r, 1)
        if F is not None: cov += d in F
    return dict(days=int(n), realised=round(real), perfect=round(perf), capture=round(real / perf, 4),
                mae=round(mae / n, 2), loss_days=int(loss), wx_days=int(cov)), daily

if __name__ == "__main__":
    lead = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    F = {d: feats(w) for d, w in load_wx(lead).items()}; F = {d: v for d, v in F.items() if v is not None}
    A0, A1, B0, B1 = dt.date(2025, 10, 1), dt.date(2026, 3, 31), dt.date(2026, 4, 1), max(F)
    print(f"prices {DAYS[0]}..{DAYS[-1]} ({len(DAYS)} d) · weather {min(F)}..{max(F)} ({len(F)} d, lead day{lead})", flush=True)
    res = {"lead": lead, "battery": "1 MW / 1.54 MWh, 88%, 2 cycles, no wear", "tune_half": f"{A0}..{A1}", "test_half": f"{B0}..{B1}",
           "tune": {}, "final": {}}
    res["tune"]["blend"] = evaluate(blend, A0, A1)[0]; print("blend", res["tune"]["blend"], flush=True)
    for m in ("ro", "wx"):
        for w in (60, 120, 180):
            for l in (30.0, 300.0, 3000.0):
                for p in (4, 16):
                    key = f"{m}_w{w}_l{l:g}_p{p}"
                    res["tune"][key] = evaluate(lambda i: ridge_fc(i, F, m, w, l, p), A0, A1)[0]
                    print(key, {k: res["tune"][key][k] for k in ("capture", "mae", "loss_days")}, flush=True)
    best = {m: max((k for k in res["tune"] if k.startswith(m + "_")), key=lambda k: res["tune"][k]["realised"]) for m in ("ro", "wx")}
    res["chosen_on_tune_half"] = best
    def fn(key):
        if key == "blend": return blend
        m, w, l, p = key.split("_"); return lambda i: ridge_fc(i, F, m, int(w[1:]), float(l[1:]), int(p[1:]))
    daily = {}
    for name in ["blend"] + list(best.values()):
        t, dd = evaluate(fn(name), B0, B1); y, _ = evaluate(fn(name), A0, B1)
        res["final"][name] = {"test_half": t, "full_year": y}; daily[name] = dd
        print("FINAL", name, res["final"][name], flush=True)
    res["test_daily"] = daily
    (pathlib.Path(__file__).parent / "results" / f"ro_weather_study_day{lead}.json").write_text(json.dumps(res, indent=1))
