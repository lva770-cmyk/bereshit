"""Project 50 (zone RO2): intraday re-trading of the day-ahead position in the three intraday auctions (IDA1/IDA2/IDA3,
SIDC, 15-min) - paper trading only, nothing is sent to any exchange.

After the day-ahead result is known, each intraday auction is an opportunity to improve the schedule: sell more where
the auction price is high, buy back where it is low, within the battery's limits (power, energy, max 2 full discharges
a day, start and end the day empty). For each auction, once its results are published by OPCOM, the battery is
assumed to have submitted the bid curve that would have produced the optimal trade at the cleared prices (price-taker,
volume capped at XCAP MW per quarter-hour as a liquidity limit). IDA3 only covers the second half of the day.
Cash: day-ahead settlement of the committed position + sum(auction price x traded MW x 0.25 h)."""
import re, html, json, datetime as dt, urllib.request, urllib.parse, http.cookiejar
from zoneinfo import ZoneInfo
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

XCAP = 25.0                 # MW per quarter-hour per auction (liquidity limit)
AUCTIONS = ("IDA1", "IDA2", "IDA3")
URL = "https://www.opcom.ro/rapoarte-ida-rezultate-cuplare/ro"

def _cells(tab):
    out = []
    for r in re.findall(r"<tr.*?</tr>", tab, re.S):
        c = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[dh][^>]*>.*?</t[dh]>", r, re.S)]
        if any(c): out.append(c)
    return out

def _num(s):
    s = s.strip()
    if not s or s == "-": return None
    try: return float(s.replace(".", "").replace(",", "."))
    except ValueError: return None

def to96(a):
    if len(a) == 100: return a[:12] + a[16:]
    if len(a) == 92: return a[:8] + a[4:8] + a[8:]
    return a if len(a) == 96 else None

def fetch_ida(day):
    """{'IDA1': [96 EUR/MWh or None], ...} for a delivery day, from OPCOM's public IDA coupling report."""
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", "Mozilla/5.0 (bereshit paper trading)"), ("Accept-Language", "ro,en")]
    h = op.open(URL, timeout=60).read().decode("utf8", "replace")
    tok = re.search(r'name="_token" value="([^"]+)"', h).group(1)
    d = dt.date.fromisoformat(day).strftime("%d/%m/%Y")
    h = op.open(urllib.request.Request(URL, urllib.parse.urlencode({"_token": tok, "data_calendar_ro": d, "buton": "Refresh", "lang": "ro"}).encode()),
                timeout=90).read().decode("utf8", "replace")
    out, k = {}, 0
    for tab in re.findall(r"<table.*?</table>", h, re.S):
        c = _cells(tab)
        if not c or not any("Pret RO" in x for x in c[0]): continue
        k += 1; m = {}
        for r in c[2:]:
            if r and r[0].isdigit() and len(r) > 1 and _num(r[1]) is not None: m[int(r[0])] = _num(r[1])
        if m and k <= 3:
            n = 100 if max(m) > 96 else 96
            a = to96([m.get(i + 1) for i in range(n)])
            if a and any(v is not None for v in a): out[f"IDA{k}"] = a
    return out

def retrade(price, pos, P, E, cyc, rte=0.88, xcap=XCAP, value=None):
    """Choose trades x (MW per quarter) so the new schedule pos+x is feasible (power, energy 0..E, start/end empty,
    total discharge <= cyc*E). The decision maximises sum(value*x) where `value` is the best price information
    available BEFORE the auction (no look-ahead); the trades are then paid the auction's clearing `price`.
    Quarters without an auction price are not traded."""
    n = 96; dt_ = .25; ec = ed = rte ** .5
    pr = np.array([np.nan if v is None else v for v in price], float); ok = ~np.isnan(pr)
    val = pr if value is None else np.array([np.nan if v is None else v for v in value], float)
    ok &= ~np.isnan(val); pz = np.where(ok, val, 0.0); pe = np.where(ok, pr, 0.0)
    C, D, Ev, X = 0, n, 2 * n, 3 * n; nv = 4 * n
    cost = np.zeros(nv); cost[X:] = -pz * dt_
    Aeq = lil_matrix((2 * n, nv)); beq = np.zeros(2 * n)
    for t in range(n):
        Aeq[t, C + t] = -ec * dt_; Aeq[t, D + t] = dt_ / ed; Aeq[t, Ev + t] = 1
        if t: Aeq[t, Ev + t - 1] = -1
        Aeq[n + t, D + t] = 1; Aeq[n + t, C + t] = -1; Aeq[n + t, X + t] = -1; beq[n + t] = pos[t]
    A = lil_matrix((1, nv)); [A.__setitem__((0, D + t), dt_ / ed) for t in range(n)]
    bounds = [(0, P)] * (2 * n) + [(0, E)] * (n - 1) + [(0, 0)] + [((-xcap, xcap) if ok[t] else (0, 0)) for t in range(n)]
    r = linprog(cost, A_ub=A.tocsr(), b_ub=[cyc * E], A_eq=Aeq.tocsr(), b_eq=beq, bounds=bounds, method="highs")
    if r.status: return np.zeros(n), 0.0
    x = r.x[X:]; x[np.abs(x) < 0.05] = 0
    return x, float((pe * x * dt_).sum())

def apply_day(rec, prices, P, E, cyc, xcap=XCAP):
    """Apply every published auction not yet applied, in order. Returns True if something changed."""
    if not rec.get("net"): return False
    idr = rec.setdefault("intraday", {}); changed = False
    pos = np.array(rec.get("net_final") or rec["net"], float)
    for a in AUCTIONS:
        if a in idr or a not in prices: continue
        if any(b not in idr for b in AUCTIONS[:AUCTIONS.index(a)] if b in prices): break   # keep the auction order
        # information available before this auction: the day-ahead result, refined by the previous auction's prices
        val = list(rec["actual"]) if rec.get("actual") else list(prices[a])
        prev = AUCTIONS[AUCTIONS.index(a) - 1] if a != "IDA1" else None
        if prev and prev in prices:
            val = [pv if pv is not None else dv for pv, dv in zip(prices[prev], val)]
        x, pnl = retrade(prices[a], pos, P, E, cyc, xcap=xcap, value=val)
        pos = pos + x
        idr[a] = {"x": [round(float(v), 1) for v in x], "price": [None if v is None else round(v, 2) for v in prices[a]],
                  "pnl": round(pnl), "sold_mwh": round(float(np.clip(x, 0, None).sum() * .25), 1),
                  "bought_mwh": round(float(np.clip(-x, 0, None).sum() * .25), 1),
                  "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        changed = True
    if changed:
        rec["net_final"] = [round(float(v), 1) for v in pos]
        rec["intraday_pnl"] = sum(v["pnl"] for v in idr.values())
    return changed

def update(state="data-RO2.json"):
    import engine
    engine.use_zone("RO2")
    s = json.load(open(state)); tz = ZoneInfo("Europe/Budapest"); today = dt.datetime.now(tz).date()
    changed = False
    for k in (0, 1):
        day = (today + dt.timedelta(days=k)).isoformat(); rec = s["days"].get(day)
        if not rec or not rec.get("net") or not rec.get("actual"): continue          # DA result must be known first
        if all(a in rec.get("intraday", {}) for a in AUCTIONS): continue
        try: prices = fetch_ida(day)
        except Exception as e: print(f"intraday {day}: OPCOM fetch failed ({e!r})"); continue
        if apply_day(rec, prices, engine.P_MW, engine.E_MWH, engine.CYC):
            changed = True; print(f"intraday {day}: applied {sorted(rec['intraday'])}, P&L €{rec['intraday_pnl']}")
        else: print(f"intraday {day}: nothing new ({sorted(prices)} published)")
    if changed:
        s["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        json.dump(s, open(state, "w"), separators=(",", ":"))

if __name__ == "__main__":
    update()
