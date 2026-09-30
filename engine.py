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
P_MW, E_MWH, RTE, CYC, WEAR = 100.0, 400.0, 0.88, 2.0, 3.0   # full 100 MW / 400 MWh plant

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

API = "https://api.energy-charts.info/price?bzn=HU&start={d}&end={d}"

def fetch_day(day):
    """Real prices for one delivery day, straight from the API. Returns None if not published yet."""
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(urllib.request.Request(API.format(d=day), headers={"User-Agent": "bereshit/1.0"}), timeout=60) as r:
            j = json.load(r)
    except urllib.error.HTTPError as err:
        if err.code in (404, 204): return None
        raise
    tz = ZoneInfo("Europe/Budapest")
    vals = [p for t, p in zip(j.get("unix_seconds", []), j.get("price", []))
            if dt.datetime.fromtimestamp(t, tz).date().isoformat() == day and p is not None]
    return vals if len(vals) in (92, 96, 100) else None

def update():
    tz = ZoneInfo("Europe/Budapest"); today = dt.datetime.now(tz).date()
    s = load(); changed = False
    for k in range(-7, 2):                      # D-7 .. D+1
        day = (today + dt.timedelta(days=k)).isoformat()
        if s["days"].get(day, {}).get("actual"): continue
        a = fetch_day(day)
        if a is None: print(f"{day}: not published yet"); continue
        b = fetch_day(day)                      # second independent HTTP read
        ingest(day, a, b, method="2 direct API reads (GitHub Actions)"); changed = True
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    if not s["days"].get(tomorrow, {}).get("net") and dt.datetime.now(tz).hour < 12:
        try: plan(tomorrow); changed = True
        except SystemExit as err: print("plan skipped:", err)
    print("changed" if changed else "no change")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["update", "ingest", "plan", "check"])
    ap.add_argument("--date"); ap.add_argument("--prices"); ap.add_argument("--prices2"); a = ap.parse_args()
    if a.cmd == "update": update()
    elif a.cmd == "ingest":
        if not a.prices2: raise SystemExit("give two independent reads: --prices a.json --prices2 b.json")
        ingest(a.date, json.load(open(a.prices)), json.load(open(a.prices2)))
    elif a.cmd == "plan": plan(a.date)
    else:
        s = load()
        for k in sorted(s["days"])[-5:]:
            d = s["days"][k]; print(k, d.get("source"), "plan" if d.get("net") else "-", "prices" if d.get("actual") else "-", d.get("realized"))
