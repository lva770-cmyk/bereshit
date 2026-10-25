"""Project 50 (zone RO2): day-ahead arbitrage co-optimised with Romanian balancing-capacity auctions (aFRR, mFRR).
Paper simulation only - nothing is offered to any market.

Each delivery day D is planned on D-1 with information available then:
  * day-ahead price forecast = the live screen's forecast for D (data-RO2.json),
  * capacity-price forecast  = per hour, mean of the last 7 published auction results (Transelectrica via ENTSO-E),
  * one LP over 96 quarter-hours decides the day-ahead schedule AND how many MW to reserve each hour for
    aFRR up/down and mFRR up/down, such that every reserved MW is deliverable:
      - power headroom: scheduled discharge + reserved up  <= P ;  scheduled charge + reserved down <= P
      - energy headroom: state of charge always keeps (reserved up x duration) above empty and
        (reserved down x duration) below full, so an activation can be served for the full duration.
Settlement uses the real day-ahead prices and the real published auction prices for D.

Assumptions (shown on the screen): we receive the published average procurement price; at most SHARE of the MW
procured by the TSO in an hour; activation energy (paid separately when the TSO calls the reserve) is not counted;
FCR is excluded (its published price looks regulated / differently defined)."""
import os, re, io, csv, json, time, zipfile, urllib.request, urllib.error, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, csr_matrix

TZ = ZoneInfo("Europe/Budapest"); RO = "10YRO-TEL------P"
OUT = "bal-RO2.json"; DA_STATE = "data-RO2.json"
P, E, RTE, CYC, WEAR = 50.0, 89.5, 0.88, 1.4, 3.0      # same generic battery as the live RO2 screen
PROD = [("aFRR", "up", 0.5), ("aFRR", "down", 0.5), ("mFRR", "up", 1.0), ("mFRR", "down", 1.0)]   # (product, dir, hours of full delivery reserved)
SHARE = 0.20            # at most 20% of the MW the TSO procured in that hour
RON_FALLBACK = 5.08

# ------------------------------------------------------------------ data
def _get(url, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bereshit/1.0"}), timeout=120) as r:
                x = r.read()
            if x[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(x)); x = b"".join(z.read(n) for n in z.namelist())
            return x.decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            t = e.read().decode("utf8", "replace")
            if "No matching data" in t: return ""
            last = f"HTTP {e.code}"
        except Exception as e: last = repr(e)[:120]
        time.sleep(6 * (k + 1))
    raise RuntimeError(last)

def fetch_caps(start, end):
    """Hourly auction results {(product, dir): {utc_hour_iso: (price_RON, qty_MW)}} from ENTSO-E A81."""
    tok = os.environ.get("ENTSOE_TOKEN")
    if not tok: raise RuntimeError("no ENTSO-E token")
    out = {}
    for prod, pt in (("aFRR", "A51"), ("mFRR", "A47")):
        a = start
        while a < end:
            b = min(a + dt.timedelta(days=30), end)
            t = _get(f"https://web-api.tp.entsoe.eu/api?securityToken={tok}&documentType=A81&businessType=B95&processType={pt}"
                     f"&type_MarketAgreement.Type=A01&controlArea_Domain={RO}&periodStart={a:%Y%m%d%H%M}&periodEnd={b:%Y%m%d%H%M}")
            for ts in re.findall(r"<TimeSeries>(.*?)</TimeSeries>", t, re.S):
                d = {"A01": "up", "A02": "down"}.get((re.findall(r"<flowDirection.direction>([^<]+)<", ts) or [""])[0])
                if not d: continue
                for per in re.findall(r"<Period>(.*?)</Period>", ts, re.S):
                    st = dt.datetime.strptime(re.findall(r"<start>([^<]+)<", per)[0], "%Y-%m-%dT%H:%MZ")
                    step = 15 if "PT15M" in per else 60
                    for p in re.findall(r"<Point>(.*?)</Point>", per, re.S):
                        pos = int(re.findall(r"<position>(\d+)<", p)[0]); q = re.findall(r"<quantity>([^<]+)<", p)
                        pr = re.findall(r"<procurement_Price.amount>([^<]+)<", p)
                        if not pr: continue
                        h = (st + dt.timedelta(minutes=step * (pos - 1))).strftime("%Y-%m-%dT%H")
                        out.setdefault((prod, d), {})[h] = (float(pr[0]), float(q[0]) if q else 0.0)
            a = b; time.sleep(1)
    return out

def eur_ron():
    """Daily ECB EUR/RON reference rate {date_iso: rate}; falls back to a fixed rate."""
    try:
        t = _get("https://data-api.ecb.europa.eu/service/data/EXR/D.RON.EUR.SP00.A?format=csvdata&startPeriod=2025-08-01")
        rows = list(csv.DictReader(io.StringIO(t)))
        return {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE")}
    except Exception:
        return {}

def day_hours(day):
    """UTC hour keys of the 24 delivery hours of a CET day (DST days mapped to 24 like the price grid)."""
    d = dt.date.fromisoformat(day); a = dt.datetime(d.year, d.month, d.day, tzinfo=TZ)
    hs = []
    cur = a
    while cur < a + dt.timedelta(days=1) + dt.timedelta(hours=1) and len(hs) < 25:
        hs.append(cur.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H")); cur += dt.timedelta(hours=1)
        if (cur.astimezone(TZ).date() != d): break
    if len(hs) == 25: hs = hs[:2] + hs[3:]
    elif len(hs) == 23: hs = hs[:2] + [hs[1]] + hs[2:]
    return hs[:24]

def day_caps(caps, day, rate):
    """{(prod,dir): (24 prices EUR/MW/h or nan, 24 qty)} for a CET day."""
    hs = day_hours(day); r = {}
    for k in [(p, d) for p, d, _ in PROD]:
        m = caps.get(k, {})
        pr = np.array([m[h][0] / rate if h in m else np.nan for h in hs]); q = np.array([m[h][1] if h in m else np.nan for h in hs])
        r[k] = (pr, q)
    return r

def cap_forecast(caps, day, rate):
    """Per hour: mean of the 7 previous days' published prices (and quantities); NaN-tolerant."""
    d = dt.date.fromisoformat(day); acc = {}
    for k in range(1, 8):
        dc = day_caps(caps, (d - dt.timedelta(days=k)).isoformat(), rate)
        for key, (pr, q) in dc.items(): acc.setdefault(key, ([], []))[0].append(pr); acc[key][1].append(q)
    out = {}
    for key, (ps, qs) in acc.items():
        with np.errstate(all="ignore"):
            p = np.nanmean(np.array(ps), axis=0); q = np.nanmean(np.array(qs), axis=0)
        out[key] = (np.nan_to_num(p, nan=0.0), np.nan_to_num(q, nan=0.0))
    return out

# ------------------------------------------------------------------ the co-optimisation
def coplan(da, capf, use_bal=True):
    """da: 96 day-ahead prices (forecast). capf: {(prod,dir): (24 EUR/MW/h, 24 MW procured)}.
    Returns dict: net (96 MW, + = sell), soc (96 MWh end of slot), res {(prod,dir): 24 MW}, floor/ceil (96 MWh)."""
    n, H = 96, 24; da = np.asarray(da, float); dt_ = .25; ec = ed = RTE ** .5
    K = len(PROD) if use_bal else 0
    nv = 3 * n + K * H      # c, d, e, r
    C, D, Ev, R = 0, n, 2 * n, 3 * n
    cost = np.zeros(nv); cost[C:C + n] = da * dt_; cost[D:D + n] = -(da - WEAR) * dt_
    for k in range(K):
        cost[R + k * H:R + (k + 1) * H] = -capf[PROD[k][:2]][0]          # EUR per MW per hour
    Aeq = lil_matrix((n, nv)); beq = np.zeros(n); e0 = 0.5 * E
    for t in range(n):
        Aeq[t, C + t] = -ec * dt_; Aeq[t, D + t] = dt_ / ed; Aeq[t, Ev + t] = 1
        if t: Aeq[t, Ev + t - 1] = -1
        else: beq[t] = e0
    rows = []; b = []
    def row(): rows.append({}); return rows[-1]
    r = row(); [r.__setitem__(D + t, dt_ / ed) for t in range(n)]; b.append(CYC * E)       # day-ahead throughput cap
    for t in range(n):
        h = t // 4
        up = row(); up[D + t] = 1; up[C + t] = -1; dn = row(); dn[C + t] = 1; dn[D + t] = -1
        lo = row(); lo[Ev + t] = -1; hi = row(); hi[Ev + t] = 1
        lo0 = row(); hi0 = row()
        if t: lo0[Ev + t - 1] = -1; hi0[Ev + t - 1] = 1
        for k in range(K):
            prod, d, tau = PROD[k]; j = R + k * H + h
            if d == "up":
                up[j] = 1; lo[j] = tau / ed; lo0[j] = tau / ed
            else:
                dn[j] = 1; hi[j] = tau * ec; hi0[j] = tau * ec
        b += [P, P, 0.0, E, (0.0 if t else e0), (E if t else E - e0)]
    A = lil_matrix((len(rows), nv))
    for i, rr in enumerate(rows):
        for j, v in rr.items(): A[i, j] = v
    bounds = [(0, P)] * (2 * n) + [(0, E)] * (n - 1) + [(e0, e0)]
    for k in range(K):
        q = capf[PROD[k][:2]][1]
        bounds += [(0, float(max(0.0, min(P, SHARE * q[h])))) for h in range(H)]
    res = linprog(cost, A_ub=A.tocsr(), b_ub=np.array(b), A_eq=Aeq.tocsr(), b_eq=beq, bounds=bounds, method="highs")
    if res.status: raise RuntimeError("LP failed: " + res.message)
    x = res.x; net = x[D:D + n] - x[C:C + n]; net[np.abs(net) < 1e-6] = 0
    resv = {PROD[k][:2]: np.round(x[R + k * H:R + (k + 1) * H], 2) for k in range(K)}
    floor = np.zeros(n); ceil = np.full(n, E)
    for t in range(n):
        h = t // 4
        for k in range(K):
            prod, d, tau = PROD[k]; v = resv[PROD[k][:2]][h]
            if d == "up": floor[t] += v * tau / ed
            else: ceil[t] -= v * tau * ec
    return {"net": net, "soc": x[Ev:Ev + n], "res": resv, "floor": floor, "ceil": ceil}

def settle(plan, da_actual, caps_actual):
    a = np.asarray(da_actual, float); net = plan["net"]
    da = float((a * net * .25).sum() - WEAR * np.clip(net, 0, None).sum() * .25)
    cap = {}
    for key, v in plan.get("res", {}).items():
        pr, q = caps_actual[key]
        vv = np.where(np.isnan(q), 0, np.minimum(v, SHARE * np.nan_to_num(q)))   # hour not procured / smaller than offered
        cap[f"{key[0]} {key[1]}"] = float(np.nansum(np.where(np.isnan(pr), 0, pr) * vv))
    return da, cap

# ------------------------------------------------------------------ runs
def blend(hist):
    d1, d7 = np.asarray(hist[-1]), np.asarray(hist[-7]); wk = np.mean([np.asarray(h) for h in hist[-7:]], axis=0)
    return 0.5 * d1 + 0.25 * d7 + 0.25 * wk

def _rate(rates, day):
    for k in range(10):
        r = rates.get((dt.date.fromisoformat(day) - dt.timedelta(days=k)).isoformat())
        if r: return r
    return RON_FALLBACK

def year(caps, rates):
    """Walk-forward year: same forecasts and rules as live; DA-only vs DA + balancing."""
    import yearly
    end = dt.datetime.now(TZ).date() - dt.timedelta(days=1)
    Pd = yearly.fetch("RO2", dt.date(2025, 9, 20), end)
    rows = []; d = dt.date(2025, 10, 1)
    while d <= end:
        hist = [Pd.get(d - dt.timedelta(days=k)) for k in range(7, 0, -1)]; a = Pd.get(d)
        if a and all(h is not None for h in hist):
            day = d.isoformat(); rate = _rate(rates, day); f = blend(hist); capf = cap_forecast(caps, day, rate); ca = day_caps(caps, day, rate)
            p0 = coplan(f, capf, use_bal=False); da0, _ = settle(p0, a, ca)
            p1 = coplan(f, capf); da1, c1 = settle(p1, a, ca)
            pf = coplan(a, {k: (np.nan_to_num(v[0]), np.nan_to_num(v[1])) for k, v in ca.items()}); daf, cf = settle(pf, a, ca)
            rows.append([d.strftime("%y-%m-%d"), round(da0), round(da1), round(c1.get("aFRR up", 0)), round(c1.get("aFRR down", 0)),
                         round(c1.get("mFRR up", 0)), round(c1.get("mFRR down", 0)), round(daf + sum(cf.values()))])
        d += dt.timedelta(days=1)
    return rows

def pack(plan, capf=None):
    o = {"net": [round(float(x), 1) for x in plan["net"]], "soc": [round(float(x), 1) for x in plan["soc"]],
         "floor": [round(float(x), 1) for x in plan["floor"]], "ceil": [round(float(x), 1) for x in plan["ceil"]],
         "res": {f"{k[0]} {k[1]}": [round(float(v), 1) for v in vals] for k, vals in plan["res"].items()}}
    if capf: o["capf"] = {f"{k[0]} {k[1]}": [round(float(v), 2) for v in p] for k, (p, q) in capf.items()}
    return o

def update(full=False):
    s = json.load(open(OUT)) if os.path.exists(OUT) else {"days": {}}
    now = dt.datetime.now(dt.timezone.utc)
    need_year = full or not s.get("rows") or s.get("rows_at", "")[:10] < (dt.date.today() - dt.timedelta(days=7)).isoformat()
    da = json.load(open(DA_STATE))["days"]
    pending = [d for d in sorted(da)[-6:] if (da[d].get("forecast") and d not in s["days"]) or
               (da[d].get("actual") and "settled" not in s["days"].get(d, {"settled": 1}))]
    fresh = s.get("updated_at", "") > (now - dt.timedelta(minutes=55)).isoformat()
    if not need_year and fresh and not pending:
        print("balancing: nothing new"); return
    caps = fetch_caps(dt.datetime(2025, 9, 1) if need_year else now.replace(tzinfo=None) - dt.timedelta(days=12),
                      now.replace(tzinfo=None, minute=0, second=0, microsecond=0) + dt.timedelta(days=2))
    if not need_year:
        old = s.get("caps_cache", {})
        for k, m in old.items():
            key = tuple(k.split(" ")); caps.setdefault(key, {}); [caps[key].setdefault(h, tuple(v)) for h, v in m.items()]
    rates = eur_ron()
    if need_year:
        s["rows"] = year(caps, rates); s["rows_at"] = now.isoformat(timespec="seconds")
    # live: plan every DA-planned day of the live RO2 screen that has no co-plan yet; settle when actuals exist
    for day in sorted(da)[-6:]:
        v = da[day]; rate = _rate(rates, day); rec = s["days"].get(day)
        if v.get("forecast") and not rec:
            capf = cap_forecast(caps, day, rate); p = coplan(v["forecast"], capf)
            s["days"][day] = rec = {"planned_at": v.get("planned_at") or now.isoformat(timespec="seconds"), "rate": rate, **pack(p, capf)}
        if rec and v.get("actual") and "settled" not in rec:
            ca = day_caps(caps, day, rate)
            if any(np.isfinite(ca[k][0]).sum() >= 8 for k in ca):
                p = {"net": np.array(rec["net"]), "res": {tuple(k.split(" ")): np.array(x) for k, x in rec["res"].items()}}
                da1, c1 = settle(p, v["actual"], ca)
                rec["settled"] = {"da": round(da1), **{k: round(x) for k, x in c1.items()}}
                rec["cap_actual"] = {f"{k[0]} {k[1]}": [None if np.isnan(x) else round(float(x), 2) for x in pr] for k, (pr, q) in ca.items()}
    s["days"] = {k: s["days"][k] for k in sorted(s["days"])[-14:]}
    keep_from = (now - dt.timedelta(days=12)).strftime("%Y-%m-%dT%H")
    s["caps_cache"] = {f"{k[0]} {k[1]}": {h: list(v) for h, v in m.items() if h >= keep_from} for k, m in caps.items()}
    s.update({"zone": "RO2", "battery": {"power_mw": P, "energy_mwh": E, "rte": RTE},
              "assumptions": {"share": SHARE, "hours_reserved": {f"{p} {d}": tau for p, d, tau in PROD}, "ron_fallback": RON_FALLBACK},
              "updated_at": now.isoformat(timespec="seconds")})
    json.dump(s, open(OUT, "w"), separators=(",", ":")); print("balancing updated", len(s.get("rows", [])), "year rows;", sorted(s["days"]))

if __name__ == "__main__":
    import sys
    update(full="full" in sys.argv)
