"""Hourly observed (reanalysis) weather for north-east Romania, for the plant-level study.
Open-Meteo Historical API (ERA5). Writes research/data/wx_ro_ne_obs.csv (UTC)."""
import csv, json, time, urllib.request, datetime as dt, pathlib
OUT = pathlib.Path(__file__).parent / "data"; OUT.mkdir(exist_ok=True)
START, END = "2025-09-20", (dt.date.today() - dt.timedelta(days=6)).isoformat()
PTS = {"ne_center": (47.0, 26.5), "iasi": (47.16, 27.59), "bacau": (46.57, 26.91)}
VARS = "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation"
def get(url):
    for k in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as r: return json.load(r)
        except Exception as e: last = e; time.sleep(10 * (k + 1))
    raise last
rows = {}
for name, (la, lo) in PTS.items():
    j = get(f"https://archive-api.open-meteo.com/v1/archive?latitude={la}&longitude={lo}"
            f"&start_date={START}&end_date={END}&hourly={VARS}&timezone=UTC")
    h = j["hourly"]
    for i, t in enumerate(h["time"]):
        rows.setdefault(t, {})[name] = [h[v][i] for v in VARS.split(",")]
    time.sleep(3)
with open(OUT / "wx_ro_ne_obs.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["time_utc"] + [f"{n}_{v}" for n in PTS for v in VARS.split(",")])
    for t in sorted(rows):
        w.writerow([t] + sum((rows[t].get(n, [None]*4) for n in PTS), []))
print("rows", len(rows))
