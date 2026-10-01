"""Year-long walk-forward backtest per zone for the screen's 'last year' chart (runs in GitHub Actions).
Same engine (LP, blend forecast, 88% RTE, 2 cycles, €3 wear). Output yearly-<ZONE>.json, rows per MW:
"yy-mm-dd,perfect,blend,naive;..." (the page multiplies by 100 MW)."""
import json, sys, time, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
import numpy as np
import engine

def fetch(zone, start, end):
    """Same strict fetch as the live engine: CET delivery days, exact quarter-hour count, DST days mapped to 96."""
    engine.use_zone(zone)
    days, d = {}, start
    while d <= end:
        e = min(d + dt.timedelta(days=30), end)
        for day, a in engine.fetch_range(d.isoformat(), e.isoformat()).items():
            if len(a) * 4 == engine._dst_len(day): a = [x for x in a for _ in range(4)]
            if len(a) == 100: a = a[:12] + a[16:]
            elif len(a) == 92: a = a[:8] + a[4:8] + a[8:]
            if len(a) == 96: days[dt.date.fromisoformat(day)] = a
        d = e + dt.timedelta(days=1); time.sleep(2)
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
