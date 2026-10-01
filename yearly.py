"""Year-long walk-forward backtest per zone for the screen's 'last year' chart (runs in GitHub Actions).
Same engine (LP, blend forecast, 88% RTE, 2 cycles, €3 wear). Output yearly-<ZONE>.json, rows per MW:
"yy-mm-dd,perfect,blend,naive;..." (the page multiplies by 100 MW)."""
import json, sys, time, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
import numpy as np
import engine

def fetch(zone, start, end):
    out, d = {}, start
    tz = ZoneInfo("Europe/Budapest")
    while d <= end:
        e = min(d + dt.timedelta(days=30), end)
        url = f"https://api.energy-charts.info/price?bzn={zone}&start={d}&end={e}"
        for k in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bereshit/1.0"}), timeout=120) as r:
                    j = json.load(r); break
            except Exception:
                if k == 4: raise
                time.sleep(15 * (k + 1))
        for t, p in zip(j["unix_seconds"], j["price"]):
            if p is None: continue
            out.setdefault(dt.datetime.fromtimestamp(t, tz).date(), {})[t] = p
        d = e + dt.timedelta(days=1); time.sleep(2)
    days = {}
    for day, m in out.items():
        a = [m[t] for t in sorted(m)]
        if len(a) in (23, 24, 25): a = [x for x in a for _ in range(4)]
        if len(a) == 100: a = a[:12] + a[16:]
        elif len(a) == 92: a = a[:8] + a[4:8] + a[8:]
        if len(a) == 96: days[day] = a
    return days

def run(zone):
    end = dt.datetime.now(ZoneInfo("Europe/Budapest")).date() - dt.timedelta(days=1)
    P = fetch(zone, dt.date(2025, 9, 20), end)
    rows = []
    d = dt.date(2025, 10, 1)
    while d <= end:
        hist = [P.get(d - dt.timedelta(days=k)) for k in range(7, 0, -1)]
        a = P.get(d)
        if a and all(h is not None for h in hist):
            pf = engine.settle(engine.schedule(a), a) / 100
            bl = engine.settle(engine.schedule(engine.blend(hist)), a) / 100
            nv = engine.settle(engine.schedule(hist[-1]), a) / 100
            rows.append(f"{d:%y-%m-%d},{pf:.0f},{bl:.0f},{nv:.0f}")
        d += dt.timedelta(days=1)
    json.dump({"zone": zone, "per": "MW", "rows": ";".join(rows),
               "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
              open(f"yearly-{zone}.json", "w"))
    print(zone, len(rows), "days")

if __name__ == "__main__":
    for z in sys.argv[1:] or ["HU", "RO", "GR"]: run(z)
