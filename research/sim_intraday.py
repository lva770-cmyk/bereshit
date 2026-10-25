"""Project 50 research backtest: day-ahead + balancing capacity, then intraday re-trading of the position.

Per delivery day D (walk-forward, same forecasts as the live screen):
  1. D-1: co-optimise DA schedule + balancing reserves on forecasts (balancing.coplan).  Settle DA at actual DA prices.
  2. D-1 15:00 CET: IDA1 - re-optimise the physical schedule against the IDA1 clearing prices, keeping every reserve
     commitment deliverable. Trades x1 = change of position, |x1| <= XCAP MW per quarter (liquidity limit).
  3. Continuous market: re-optimise again against ROPEX_ID (volume-weighted average of continuous trades), |x2| <= XCAP.
Price-taker at those prices (no own price impact beyond the XCAP volume limit) - optimistic, see notes in output."""
import sys, csv, datetime as dt, collections, numpy as np, warnings
from scipy.optimize import linprog
from scipy.sparse import lil_matrix
warnings.filterwarnings("ignore")
sys.path.insert(0, "."); import balancing as B
R = "research/data/"

def to96(a):
    if len(a) == 100: return a[:12] + a[16:]
    if len(a) == 92: return a[:8] + a[4:8] + a[8:]
    return a if len(a) == 96 else None

def load(shift=0):
    Pd = {dt.date.fromisoformat(r["date"]): [float(r[f"q{i}"]) for i in range(96)] for r in csv.DictReader(open(R + "ro_prices.csv"))}
    caps = {}
    for r in csv.DictReader(open(R + "ro_balancing.csv")):
        if r["product"] in ("aFRR", "mFRR") and r["direction"] in ("up", "down") and r["price"]:
            caps.setdefault((r["product"], r["direction"]), {})[r["time_utc"][:13]] = (float(r["price"]), float(r["quantity_mw"] or 0))
    ida = collections.defaultdict(dict)
    for r in csv.DictReader(open(R + "ro_ida.csv")):
        ida[(r["date"], r["auction"])][int(r["interval"])] = float(r["price_eur"])
    rates = {r["date"]: float(r["eur_ron"]) for r in csv.DictReader(open(R + "eur_ron.csv"))} if __import__("os").path.exists(R + "eur_ron.csv") else {}
    idh, vb, vs = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for r in csv.DictReader(open(R + "ro_idct.csv")):
        if r["res"] != "60": continue
        v = float(r["ropex_id"]) if r["ropex_id"] else np.nan
        idh[r["date"]].append(v); vb[r["date"]].append(float(r["vol_buy"] or 0)); vs[r["date"]].append(float(r["vol_sell"] or 0))
    def series(day, auction):
        m = ida.get((day, auction))
        if not m: return None
        n = max(m); a = [m.get(i + 1, np.nan) for i in range(n)]
        return to96(a)
    def cont(day):
        rate = B._rate(rates, day) if rates else B.RON_FALLBACK
        h = idh.get(day)
        if h and len(h) in (23, 24, 25):
            q = lambda arr: to96([x for x in arr for _ in range(4)])
            return q([x / rate for x in h]), q(vb[day]), q(vs[day])     # EUR/MWh; hourly buy / sell volume (MWh = MW)
        return None
    return Pd, caps, series, cont

def retrade(price, net_prev, plan, xcap, sell_cap=None, buy_cap=None):
    """Max sum(price * x * 0.25) s.t. physical schedule net_prev + x feasible with plan reserves (power + energy)."""
    n = 96; dt_ = .25; ec = ed = B.RTE ** .5; E, P = B.E, B.P
    price = np.asarray(price, float); ok = ~np.isnan(price); pr = np.where(ok, price, 0.0)
    up = np.zeros(n); dn = np.zeros(n)
    for (prod, d), v in plan["res"].items():
        for t in range(n): (up if d == "up" else dn)[t] += v[t // 4]
    floor, ceil = plan["floor"], plan["ceil"]
    C, D, Ev, X = 0, n, 2 * n, 3 * n; nv = 4 * n
    cost = np.zeros(nv); cost[X:] = -pr * dt_
    Aeq = lil_matrix((2 * n, nv)); beq = np.zeros(2 * n); e0 = .5 * E
    for t in range(n):
        Aeq[t, C + t] = -ec * dt_; Aeq[t, D + t] = dt_ / ed; Aeq[t, Ev + t] = 1
        if t: Aeq[t, Ev + t - 1] = -1
        else: beq[t] = e0
        Aeq[n + t, D + t] = 1; Aeq[n + t, C + t] = -1; Aeq[n + t, X + t] = -1; beq[n + t] = net_prev[t]
    A = lil_matrix((3 * n + 1, nv)); b = []
    for t in range(n):
        A[3 * t, D + t] = 1; A[3 * t, C + t] = -1; b.append(P - up[t])           # discharge + reserved up <= P
        A[3 * t + 1, C + t] = 1; A[3 * t + 1, D + t] = -1; b.append(P - dn[t])   # charge + reserved down <= P
        A[3 * t + 2, D + t] = 0; b.append(0)
    for t in range(n): A[3 * n, D + t] = dt_ / ed
    b.append(B.CYC * E)
    lo = [max(floor[t], floor[t + 1] if t + 1 < n else 0) for t in range(n)]       # energy kept for reserves (slot start & end)
    hi = [min(ceil[t], ceil[t + 1] if t + 1 < n else E) for t in range(n)]
    bounds = [(0, P)] * (2 * n) + [(min(lo[t], hi[t]), hi[t]) for t in range(n - 1)] + [(e0, e0)] \
             + [((-min(xcap, buy_cap[t] if buy_cap is not None else xcap), min(xcap, sell_cap[t] if sell_cap is not None else xcap)) if ok[t] else (0, 0)) for t in range(n)]
    res = linprog(cost, A_ub=A.tocsr(), b_ub=np.array(b), A_eq=Aeq.tocsr(), b_eq=beq, bounds=bounds, method="highs")
    if res.status: return np.zeros(n), 0.0
    x = res.x[X:]; x[np.abs(x) < 1e-6] = 0
    return x, float((pr * x * dt_).sum())

def run(use_bal=True, xcap=25.0, steps=("IDA1", "ID"), shift=0, share=0.2):
    Pd, caps, series, cont = load()
    rate = B.RON_FALLBACK; tot = collections.Counter(); nd = 0
    d = dt.date(2025, 10, 2); end = max(Pd)
    while d <= end:
        hist = [Pd.get(d - dt.timedelta(days=k)) for k in range(7, 0, -1)]; a = Pd.get(d); day = d.isoformat()
        p1 = series(day, "IDA1"); pc = cont(day)
        if a and all(h is not None for h in hist) and (p1 or pc):
            f = B.blend(hist); capf = B.cap_forecast(caps, day, rate); ca = B.day_caps(caps, day, rate)
            plan = B.coplan(f, capf, use_bal=use_bal); da, c = B.settle(plan, a, ca)
            tot["da"] += da; tot["bal"] += sum(c.values()); net = plan["net"].copy(); nd += 1
            for s in steps:
                sc = bc = None
                if s == "IDA1": pr = p1
                elif pc: pr, b_, s_ = pc; sc = share * np.asarray(b_); bc = share * np.asarray(s_)   # we sell into their buys
                else: pr = None
                if pr is None: continue
                pr = np.roll(pr, shift) if shift else pr
                x, v = retrade(pr, net, plan, xcap, sc, bc); tot[s] += v; tot[s + "_mwh"] += np.abs(x).sum() * .25; net = net + x
        d += dt.timedelta(days=1)
    return nd, tot

if __name__ == "__main__":
    B.CYC, B.WEAR = 2.0, 0.0
    for ub in (False, True):
        for xc in (10.0, 25.0, 50.0):
            nd, t = run(ub, xc)
            k = 365 / max(nd, 1)
            print(f"{'DA+bal' if ub else 'DA only':7} xcap {xc:>4} days {nd}: DA €{t['da']*k/1e6:.2f}M  bal €{t['bal']*k/1e6:.2f}M  "
                  f"IDA1 +€{t['IDA1']*k/1e6:.2f}M  ID +€{t['ID']*k/1e6:.2f}M  total €{(t['da']+t['bal']+t['IDA1']+t['ID'])*k/1e6:.2f}M /yr  "
                  f"(ID volume {t['IDA1_mwh']/nd:.0f}+{t['ID_mwh']/nd:.0f} MWh/day)")
