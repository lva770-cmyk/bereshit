"""Project 50 (Romania): do UPDATED weather forecasts help the intraday auctions (IDA1/IDA2/IDA3)?

Live rule (intraday_live.apply_day): before each auction the battery values every quarter-hour at the best price known
then - IDA1: the day-ahead result; IDA2: IDA1's clearing prices; IDA3: IDA2's - and re-trades its position against that.
Here the value is corrected by a ridge model of (auction price - that value) on the REVISION of the weather forecast
since the day-ahead decision: Open-Meteo previous_day1 (run ~24 h before the hour) minus previous_day2 (~48 h before).
No look-ahead: previous_day1 for hour h of D comes from a run ~24 h earlier; for IDA1 (gate 15:00 D-1) the revision is
used only for hours before 15:00, later hours get none. Models refit daily on past days only; settings chosen on
Oct-Mar, reported on the untouched Apr-Sep half. Trades are paid the actual auction prices, 25 MW cap as live."""
import sys, csv, json, collections, pathlib, datetime as dt
import numpy as np
ROOT = pathlib.Path(__file__).parent.parent; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "research"))
import engine, intraday_live as IL
import study_weather_ro as W

engine.use_zone("RO2"); R = ROOT / "research" / "data"; S = 96
P = {dt.date.fromisoformat(r["date"]): np.array([float(r[f"q{i}"]) for i in range(S)]) for r in csv.DictReader(open(R / "ro_prices.csv"))}
ida = collections.defaultdict(dict)
for r in csv.DictReader(open(R / "ro_ida.csv")): ida[(r["date"], r["auction"])][int(r["interval"])] = float(r["price_eur"])
def auctions(day):
    out = {}
    for a in IL.AUCTIONS:
        m = ida.get((day.isoformat(), a))
        if m:
            n = 100 if max(m) > 96 else 96; v = IL.to96([m.get(i + 1) for i in range(n)])
            if v: out[a] = np.array([np.nan if x is None else x for x in v], float)
    return out

F1 = {d: W.feats(w) for d, w in W.load_wx(1).items()}; F2 = {d: W.feats(w) for d, w in W.load_wx(2).items()}
KEYS = ["wind_ro", "sol_ro", "temp_ro", "wind_region", "sol_region", "wind_de"]
def rev(d, auction):
    a, b = F1.get(d), F2.get(d)
    if a is None or b is None: return None
    X = np.stack([a[k] - b[k] for k in KEYS], 1)
    if auction == "IDA1": X[60:] = 0.0                       # hours from 15:00 would use a run after the IDA1 gate
    return X

# ---------- per day: DA plan + the base value each auction sees ----------
DAYS = []; BASE = {}
for d in sorted(P):
    hist = [P.get(d - dt.timedelta(days=k)) for k in range(7, 0, -1)]
    pr = auctions(d)
    if any(h is None for h in hist) or not pr: continue
    net = engine.schedule(engine.blend([list(h) for h in hist]))
    vals = {}
    for i, a in enumerate(IL.AUCTIONS):
        if a not in pr: continue
        v = P[d].copy()
        if i and IL.AUCTIONS[i - 1] in pr: prev = pr[IL.AUCTIONS[i - 1]]; v = np.where(np.isnan(prev), v, prev)
        vals[a] = v
    DAYS.append(d); BASE[d] = (net, pr, vals)

def model(i, a, win, lam, pool):
    """Predicted (auction price - base value) for day DAYS[i], learned on earlier days only."""
    d = DAYS[i]; Xt = rev(d, a)
    if Xt is None or a not in BASE[d][1]: return None
    X, Y = [], []
    for j in range(max(0, i - win), i):
        dj = DAYS[j]; _, pr, vals = BASE[dj]; x = rev(dj, a)
        if x is None or a not in pr: continue
        y = pr[a] - vals[a]; ok = ~np.isnan(y)
        X.append(np.where(ok[:, None], x, 0)); Y.append(np.where(ok, y, 0))
    if len(X) < 30: return None
    X, Y = np.stack(X), np.stack(Y); k = X.shape[2]; out = np.zeros(S)
    for s in range(0, S, pool):
        g = list(range(s, min(S, s + pool))); A = X[:, g, :].reshape(-1, k); y = Y[:, g].reshape(-1)
        mu, sd = A.mean(0), A.std(0) + 1e-9; Z = np.column_stack([np.ones(len(A)), (A - mu) / sd])
        Rg = lam * np.eye(k + 1); Rg[0, 0] = 0; w = np.linalg.solve(Z.T @ Z + Rg, Z.T @ y)
        out[g] = np.column_stack([np.ones(len(g)), (Xt[g] - mu) / sd]) @ w
    out[np.abs(Xt).sum(1) == 0] = 0.0                        # no new information -> no correction
    return out

def run(lo, hi, cfg=None, xcap=25.0):
    tot = collections.Counter(); n = 0; daily = {}
    for i, d in enumerate(DAYS):
        if not (lo <= d <= hi) or d not in F1 or d not in F2: continue
        net, pr, vals = BASE[d]; pos = np.array(net, float); day = 0.0
        for a in IL.AUCTIONS:
            if a not in pr: continue
            v = vals[a].copy()
            if a != "IDA1" and IL.AUCTIONS[IL.AUCTIONS.index(a) - 1] in pr: pass
            if cfg:
                c = model(i, a, *cfg)
                if c is not None: v = v + c
            price = [None if np.isnan(x) else float(x) for x in pr[a]]
            x, pnl = IL.retrade(price, pos, engine.P_MW, engine.E_MWH, engine.CYC, xcap=xcap, value=list(v))
            pos = pos + x; tot[a] += pnl; day += pnl
        tot["id"] += day; n += 1; daily[d.isoformat()] = round(day)
    k = 365 / max(n, 1)
    return {"days": n, "intraday_year": round(tot["id"] * k), **{a: round(tot[a] * k) for a in IL.AUCTIONS}}, daily

if __name__ == "__main__":
    A0, A1, B0, B1 = dt.date(2025, 10, 1), dt.date(2026, 3, 31), dt.date(2026, 4, 1), dt.date(2026, 9, 30)
    res = {"plant": f"{engine.P_MW} MW / {engine.E_MWH} MWh, 2 cycles, 25 MW per auction", "tune": {}, "final": {}}
    res["tune"]["live_rule"] = run(A0, A1)[0]; print("live rule", res["tune"]["live_rule"], flush=True)
    for w in (90, 180):
        for l in (30.0, 300.0, 3000.0):
            for p in (4, 16):
                key = f"wx_w{w}_l{l:g}_p{p}"; res["tune"][key] = run(A0, A1, (w, l, p))[0]; print(key, res["tune"][key], flush=True)
    best = max((k for k in res["tune"] if k.startswith("wx_")), key=lambda k: res["tune"][k]["intraday_year"])
    res["chosen_on_tune_half"] = best; w, l, p = best.split("_")[1:]; cfg = (int(w[1:]), float(l[1:]), int(p[1:]))
    for name, c in (("live_rule", None), (best, cfg)):
        t, dd = run(B0, B1, c); y, _ = run(A0, B1, c)
        res["final"][name] = {"test_half": t, "full_year": y, "test_daily": dd}; print("FINAL", name, {"test": t, "year": y}, flush=True)
    (ROOT / "research" / "results" / "ro_intraday_weather_study.json").write_text(json.dumps(res, indent=1))
