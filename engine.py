"""בראשית live engine – paper trading on real HUPX day-ahead prices.

GitHub version: `python engine.py update` fetches prices DIRECTLY from the Energy-Charts API (no AI in the loop),
ingests every missing day, and locks tomorrow's plan before gate closure. Safe to run as often as you like.

Single file, used by the daily scheduled task. State lives in data.json (published next to the page).
    python engine.py ingest  --date 2026-10-01 --prices prices.json   # 96 real DA prices (€/MWh) for that day
    python engine.py plan    --date 2026-10-02                        # lock tomorrow's schedule (before 12:00 CET)
    python engine.py check                                            # print state summary
Nothing is ever sent to an exchange. Plans are write-once.
"""
import argparse, datetime as dt, json, sys
from zoneinfo import ZoneInfo
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, csr_matrix

STATE = "data.json"
# Bidding zones on the same SDAC auction (gate 12:00 CET for all). Each zone has its own state file.
ZONES = {"HU": ("data.json", "HUPX day-ahead (SDAC), 15-min"),
         "RO": ("data-RO.json", "OPCOM day-ahead (SDAC), 15-min"),
         "DE": ("data-DE.json", "EPEX SPOT DE-LU day-ahead (SDAC), 15-min")}
BZN = {"DE": "DE-LU"}   # Energy-Charts bidding-zone code where it differs from ours
ZONE = "HU"
def use_zone(z):
    global STATE, ZONE
    ZONE = z; STATE = ZONES[z][0]
    import os
    if not os.path.exists(STATE):
        json.dump({"zone": z, "market": ZONES[z][1], "battery": {"power_mw": 40, "energy_mwh": 160, "rte": 0.88},
                   "mode": "paper", "days": {}}, open(STATE, "w"), separators=(",", ":"))
P_MW, E_MWH, RTE, CYC, WEAR = 40.0, 160.0, 0.88, 2.0, 3.0   # 40 MW / 160 MWh plant (4 h)

def load(): return json.load(open(STATE))
def save(s):
    s["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(s, open(STATE, "w"), separators=(",", ":"))

def schedule(p):
    p = np.asarray(p, float); n = len(p); dt_ = np.full(n, .25); ec = ed = RTE ** .5
    cost = np.concatenate([p * dt_, -(p - WEAR) * dt_, np.zeros(n)])
    A = lil_matrix((n, 3 * n))
    for t in range(n):
        A[t, t] = -ec * dt_[t]; A[t, n + t] = dt_[t] / ed; A[t, 2 * n + t] = 1
        if t: A[t, 2 * n + t - 1] = -1
    r = linprog(cost, A_ub=csr_matrix(np.concatenate([np.zeros(n), dt_, np.zeros(n)])[None, :]), b_ub=[CYC * E_MWH],
                A_eq=A.tocsr(), b_eq=np.zeros(n), bounds=[(0, P_MW)] * (2 * n) + [(0, E_MWH)] * (n - 1) + [(0, 0)], method="highs")
    if r.status: raise SystemExit("LP failed: " + r.message)
    net = r.x[n:2 * n] - r.x[:n]; net[np.abs(net) < 1e-6] = 0
    return net

def settle(net, a):
    net, a = np.asarray(net, float), np.asarray(a, float)
    return float((a * net * .25).sum() - WEAR * np.clip(net, 0, None).sum() * .25)

def blend(hist):
    """hist: list of the 7 previous days' 96-price arrays, oldest first (hist[-1] = D-1)."""
    d1, d7 = np.asarray(hist[-1]), np.asarray(hist[-7]); wk = np.mean([np.asarray(h) for h in hist[-7:]], axis=0)
    return 0.5 * d1 + 0.25 * d7 + 0.25 * wk

def _norm(prices):
    a = [round(float(x), 2) for x in prices]
    if len(a) == 100: a = a[:12] + a[16:]
    elif len(a) == 92: a = a[:8] + a[4:8] + a[8:]
    return a

def ingest(day, prices, prices2=None, fetched_at=None, method="2 direct API reads"):
    """Store real DA prices for `day`. With prices2, both reads must be identical to the cent (guards against
    copy errors in the fetch path). Records a verification stamp that the page displays."""
    raw_n = len(prices)
    if prices2 is not None:
        if len(prices2) != raw_n or any(abs(float(x) - float(y)) > 0.005 for x, y in zip(prices, prices2)):
            raise SystemExit("the two reads differ – not ingesting. Fetch again.")
    a = [float(x) for x in prices]
    # clock-change days: 100 slots (autumn, 02:00-03:00 twice) -> drop the repeated hour; 92 (spring) -> repeat 01:00-02:00.
    # Keeps every day on the same 96-slot grid; the approximation affects one hour on two days a year.
    want = _dst_len(day)
    if len(a) * 4 == want: a = [x for x in a for _ in range(4)]   # hourly market day -> 15-min grid
    if len(a) != want: raise SystemExit(f"{day}: expected {want} quarter-hours, got {raw_n} – not ingesting")
    if len(a) == 100: a = a[:12] + a[16:]
    elif len(a) == 92: a = a[:8] + a[4:8] + a[8:]
    if len(a) != 96: raise SystemExit(f"expected 96 quarter-hour prices, got {len(prices)}")
    if not all(-500 <= x <= 4000 for x in a): raise SystemExit("price outside the SDAC harmonised range")
    s = load(); d = s["days"].setdefault(day, {"date": day})
    if d.get("actual") and max(abs(x - y) for x, y in zip(d["actual"], a)) > 0.01:
        raise SystemExit(f"{day} already has different actual prices – refusing to overwrite")
    d["actual"] = [round(x, 2) for x in a]
    import hashlib
    prev = s["days"].get((dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat(), {}).get("actual")
    mad = float(np.mean(np.abs(np.asarray(a) - np.asarray(prev)))) if prev else None
    d["verify"] = {"method": method, "reads": 2 if prices2 is not None else 1, "match": prices2 is not None,
                   "n": raw_n, "range_ok": True, "sha256": hashlib.sha256(json.dumps(d["actual"]).encode()).hexdigest()[:16],
                   "fetched_at": fetched_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "vs_prev_mae": round(mad, 1) if mad is not None else None,
                   "unusual": bool(mad is not None and mad > 80)}
    if d.get("net"):
        d["realized"] = round(settle(d["net"], a)); d["perfect"] = round(settle(schedule(a), a))
    save(s); print(f"ingested {day}: avg {np.mean(a):.2f} €/MWh, realized {d.get('realized')}, perfect {d.get('perfect')}")

def plan(day):
    s = load(); target = dt.date.fromisoformat(day)
    if s["days"].get(day, {}).get("net"): raise SystemExit(f"{day} already planned at {s['days'][day]['planned_at']} – plans are write-once")
    now_cet = dt.datetime.now(ZoneInfo("Europe/Budapest"))
    if now_cet.date() >= target or (now_cet.date() == target - dt.timedelta(days=1) and now_cet.hour >= 12):
        raise SystemExit(f"too late: gate closure for {day} was 12:00 CET on the day before (now {now_cet:%Y-%m-%d %H:%M} CET)")
    hist = []
    for k in range(7, 0, -1):
        dd = (target - dt.timedelta(days=k)).isoformat(); a = s["days"].get(dd, {}).get("actual")
        if not a: raise SystemExit(f"missing actual prices for {dd} – ingest it first")
        hist.append(a)
    f = blend(hist); net = schedule(f)
    s["days"][day] = {"date": day, "source": "live", "planned_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                      "forecast": [round(x, 2) for x in f], "net": [round(x, 1) for x in net]}
    save(s); print(f"planned {day}: buy {np.clip(-net,0,None).sum()*.25:.0f} MWh, sell {np.clip(net,0,None).sum()*.25:.0f} MWh")

API = "https://api.energy-charts.info/price?bzn={z}&start={d}&end={d}"

def _dst_len(day):
    """Number of quarter-hours in a CET delivery day: 92 on the spring clock change, 100 in autumn, else 96."""
    tz = ZoneInfo("Europe/Budapest"); d = dt.date.fromisoformat(day)
    a = dt.datetime(d.year, d.month, d.day, tzinfo=tz); b = a + dt.timedelta(days=1)
    return int((b.astimezone(dt.timezone.utc) - a.astimezone(dt.timezone.utc)).total_seconds() // 900)

SOURCE = None        # which source served the last successful fetch (shown in the verification stamp)
ENTSOE_EIC = {"HU": "10YHU-MAVIR----U", "RO": "10YRO-TEL------P", "DE": "10Y1001A1001A82H"}

def _get(url, kind="json", tries=3):
    import urllib.request, urllib.error, time
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bereshit/1.0"}), timeout=90) as r:
                body = r.read()
            return json.loads(body) if kind == "json" else body
        except urllib.error.HTTPError as err:
            if err.code in (404, 204): return None
            if err.code in (429, 500, 502, 503, 504) and k < tries - 1: time.sleep(10 * (k + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if k < tries - 1: time.sleep(10 * (k + 1)); continue
            raise

def _src_energy_charts(s0, e0):
    j = _get(f"https://api.energy-charts.info/price?bzn={BZN.get(ZONE, ZONE)}&start={s0}&end={e0}")
    if j is None: return {}
    return {t: p for t, p in zip(j.get("unix_seconds", []), j.get("price", [])) if p is not None}

def _src_entsoe(s0, e0):
    """ENTSO-E Transparency Platform (official TSO data). Needs a free token in the ENTSOE_TOKEN secret."""
    import os, xml.etree.ElementTree as ET
    tok = os.environ.get("ENTSOE_TOKEN")
    if not tok or ZONE not in ENTSOE_EIC: raise RuntimeError("no ENTSO-E token")
    f = lambda d: dt.datetime.combine(dt.date.fromisoformat(d), dt.time()).strftime("%Y%m%d0000")
    eic = ENTSOE_EIC[ZONE]
    x = _get(f"https://web-api.tp.entsoe.eu/api?securityToken={tok}&documentType=A44&in_Domain={eic}&out_Domain={eic}"
             f"&periodStart={f(s0)}&periodEnd={f(e0)}", kind="raw")
    if x is None: return {}
    root = ET.fromstring(x); ns = {"n": root.tag.split("}")[0].strip("{")}
    out = {}
    for ts in root.findall("n:TimeSeries", ns):
        for per in ts.findall("n:Period", ns):
            start = dt.datetime.strptime(per.find("n:timeInterval/n:start", ns).text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
            end = dt.datetime.strptime(per.find("n:timeInterval/n:end", ns).text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc)
            step = {"PT15M": 900, "PT30M": 1800, "PT60M": 3600}[per.find("n:resolution", ns).text]
            pts = {int(p.find("n:position", ns).text): float(p.find("n:price.amount", ns).text) for p in per.findall("n:Point", ns)}
            n = int((end - start).total_seconds() // step); last = None
            for i in range(1, n + 1):                       # curve type A03: a missing position repeats the previous price
                last = pts.get(i, last)
                if last is None: continue
                t0 = int(start.timestamp()) + (i - 1) * step
                for q in range(0, step, 900): out.setdefault(t0 + q, last)   # first series wins on duplicates
    return out

def _src_smard(s0, e0):
    """SMARD (Bundesnetzagentur) – official German day-ahead price DE-LU, quarter-hourly. Germany only."""
    if ZONE != "DE": raise RuntimeError("SMARD covers Germany only")
    idx = _get("https://www.smard.de/app/chart_data/4169/DE-LU/index_quarterhour.json") or {}
    lo = dt.datetime.fromisoformat(s0).replace(tzinfo=dt.timezone.utc).timestamp() * 1000
    hi = dt.datetime.fromisoformat(e0).replace(tzinfo=dt.timezone.utc).timestamp() * 1000 + 86400000
    out = {}
    for w in idx.get("timestamps", []):
        if w > hi or w + 8 * 86400000 < lo: continue
        j = _get(f"https://www.smard.de/app/chart_data/4169/DE-LU/4169_DE-LU_quarterhour_{w}.json") or {}
        for ms, v in j.get("series", []):
            if v is not None: out[int(ms // 1000)] = float(v)
    return out

def fetch_range(start, end):
    """Real prices split into CET/CEST delivery days (the SDAC day for every zone). Sources in order:
    Energy-Charts, then ENTSO-E (if a token is configured), then SMARD (Germany). The request is padded by a
    day on each side because sources cut days in the zone's own local time. Only complete days are returned."""
    global SOURCE
    s0 = (dt.date.fromisoformat(start) - dt.timedelta(days=1)).isoformat()
    e0 = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
    m, errs = None, []
    for name, fn in (("Energy-Charts", _src_energy_charts), ("ENTSO-E", _src_entsoe), ("SMARD", _src_smard)):
        try:
            m = fn(s0, e0); SOURCE = name; break
        except Exception as err:
            errs.append(f"{name}: {err!r}"[:160])
    if m is None: raise RuntimeError("all price sources failed – " + " | ".join(errs))
    tz = ZoneInfo("Europe/Budapest"); by = {}
    for t, p in m.items():
        by.setdefault(dt.datetime.fromtimestamp(t, tz).date().isoformat(), {})[t] = p
    out = {}
    for day, mm in by.items():
        if not (start <= day <= end): continue
        vals = [mm[t] for t in sorted(mm)]
        if len(vals) == _dst_len(day) or len(vals) * 4 == _dst_len(day):   # 15-min, or hourly
            out[day] = vals
    return out

def fetch_day(day):
    """Real prices for one delivery day. None if not (fully) published yet."""
    return fetch_range(day, day).get(day)

def update():
    """All zones; a failure in one zone never blocks the others."""
    for z in ZONES:
        use_zone(z); print(f"== {z}")
        try: update_zone()
        except (Exception, SystemExit) as err: print(f"{z}: error {err!r}")

def backfill(days):
    """Seed a new zone: ingest the last `days`+7 days of real prices (2 reads each), then build walk-forward
    'backtest' plans for every past day that has 7 prior days (forecast uses only earlier prices). Live plans
    start with the next gate. Backtest days are labelled as such on the screen."""
    tz = ZoneInfo("Europe/Budapest"); today = dt.datetime.now(tz).date()
    lo, hi = (today - dt.timedelta(days=days + 7)).isoformat(), today.isoformat()
    A = fetch_range(lo, hi); import time; time.sleep(3); B = fetch_range(lo, hi)   # two independent reads
    for k in range(days + 7, -1, -1):
        day = (today - dt.timedelta(days=k)).isoformat()
        s = load()
        if s["days"].get(day, {}).get("actual"): continue
        if day not in A or day not in B: print(f"{day}: not available"); continue
        ingest(day, A[day], B[day], method=f"2 direct API reads (GitHub Actions) · {SOURCE}")
    s = load()
    for k in range(days, -1, -1):
        day = (today - dt.timedelta(days=k)); key = day.isoformat(); d = s["days"].get(key)
        if not d or not d.get("actual") or d.get("net"): continue
        hist = [s["days"].get((day - dt.timedelta(days=j)).isoformat(), {}).get("actual") for j in range(7, 0, -1)]
        if not all(hist): continue
        f = blend(hist); net = schedule(f)
        d.update({"source": "backtest", "forecast": [round(x, 2) for x in f], "net": [round(x, 1) for x in net]})
        d["realized"] = round(settle(d["net"], d["actual"])); d["perfect"] = round(settle(schedule(d["actual"]), d["actual"]))
        print(f"backtest {key}: realized {d['realized']} / perfect {d['perfect']}")
    save(s)

def update_zone():
    tz = ZoneInfo("Europe/Budapest"); today = dt.datetime.now(tz).date()
    s = load(); changed = False
    if sum(1 for d in s["days"].values() if d.get("actual")) < 10:   # new zone: seed it (self-healing after outages)
        try: backfill(9); changed = True; s = load()
        except (Exception, SystemExit) as err: print("backfill failed (will retry next run):", repr(err))
    for k in range(-7, 2):                      # D-7 .. D+1
        day = (today + dt.timedelta(days=k)).isoformat()
        if s["days"].get(day, {}).get("actual"): continue
        try:
            a = fetch_day(day)
            if a is None: print(f"{day}: not published yet"); continue
            b = fetch_day(day)                  # second independent HTTP read
        except Exception as err:                # price server down: keep going, planning only needs stored data
            print(f"{day}: fetch failed ({err!r}) – will retry next run"); break
        ingest(day, a, b, method=f"2 direct API reads (GitHub Actions) · {SOURCE}"); changed = True; s = load()
    # Lock the next plan as early as the data allows: D+1 until today's gate, and D+2 as soon as D+1 prices are
    # published (still before D+2's gate). This survives long gaps between scheduled runs.
    for k in (1, 2):
        day = (today + dt.timedelta(days=k)).isoformat()
        if load()["days"].get(day, {}).get("net"): continue
        try: plan(day); changed = True
        except SystemExit as err: print(f"plan {day} skipped:", err)
    print("changed" if changed else "no change")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["update", "ingest", "plan", "check", "backfill"])
    ap.add_argument("--zone", default="HU", choices=list(ZONES)); ap.add_argument("--days", type=int, default=9)
    ap.add_argument("--date"); ap.add_argument("--prices"); ap.add_argument("--prices2"); a = ap.parse_args()
    use_zone(a.zone)
    if a.cmd == "update": update()
    elif a.cmd == "backfill": backfill(a.days)
    elif a.cmd == "ingest":
        if not a.prices2: raise SystemExit("give two independent reads: --prices a.json --prices2 b.json")
        ingest(a.date, json.load(open(a.prices)), json.load(open(a.prices2)))
    elif a.cmd == "plan": plan(a.date)
    else:
        s = load()
        for k in sorted(s["days"])[-5:]:
            d = s["days"][k]; print(k, d.get("source"), "plan" if d.get("net") else "-", "prices" if d.get("actual") else "-", d.get("realized"))
