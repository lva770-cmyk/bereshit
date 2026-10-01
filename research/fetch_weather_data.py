"""Fetch the raw data for the weather-forecast study (runs inside GitHub Actions).

1. HUPX day-ahead prices (Energy-Charts API), 15-min, UTC.
2. Weather FORECASTS as they were known in advance (Open-Meteo Previous Runs API).
   *_previous_day2 = value from the model run ~48h before the target hour, so it was
   available before the D-1 12:00 CET gate for every hour of D (no look-ahead).
   *_previous_day1 (~24h before) is stored too, but leaks for afternoon hours; reference only.
Writes research/data/*.csv and research/data/fetch_status.json.
"""
import csv, json, time, urllib.request, urllib.error, datetime as dt, pathlib

OUT = pathlib.Path(__file__).parent / "data"; OUT.mkdir(exist_ok=True)
START, END = "2025-06-15", (dt.date.today() - dt.timedelta(days=1)).isoformat()
status = {"started": dt.datetime.utcnow().isoformat() + "Z", "start": START, "end": END, "steps": {}}

def get(url, tries=5):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa
            last = e; time.sleep(10 * (k + 1))
    raise last

# 1. prices, month by month
try:
    rows, d = [], dt.date.fromisoformat(START)
    end = dt.date.fromisoformat(END)
    while d <= end:
        e = min(d + dt.timedelta(days=30), end)
        j = get(f"https://api.energy-charts.info/price?bzn=HU&start={d}&end={e}")
        rows += list(zip(j["unix_seconds"], j["price"]))
        d = e + dt.timedelta(days=1); time.sleep(2)
    seen = {}
    for t, p in rows: seen[t] = p
    with open(OUT / "hu_prices.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["unix", "price"])
        for t in sorted(seen): w.writerow([t, seen[t]])
    status["steps"]["prices"] = {"ok": True, "rows": len(seen)}
except Exception as e:
    status["steps"]["prices"] = {"ok": False, "error": repr(e)}

# 2. weather forecasts
LOCS = {  # name: (lat, lon)
    "hu_budapest": (47.50, 19.04), "hu_debrecen": (47.53, 21.63), "hu_szeged": (46.25, 20.15),
    "hu_pecs": (46.07, 18.23), "hu_gyor": (47.68, 17.63),
    "at_vienna": (48.21, 16.37), "ro_dobrogea": (44.40, 28.30), "ro_bucharest": (44.43, 26.10),
    "de_north": (53.80, 9.50), "de_south": (48.40, 11.00), "pl_center": (52.00, 19.00), "sk_kosice": (48.72, 21.26),
}
VARS = ["temperature_2m", "shortwave_radiation", "wind_speed_100m", "cloud_cover"]
hourly = ",".join(f"{v}_previous_day{k}" for v in VARS for k in (1, 2))
for name, (la, lo) in LOCS.items():
    try:
        j = get("https://previous-runs-api.open-meteo.com/v1/forecast?"
                f"latitude={la}&longitude={lo}&hourly={hourly}&start_date={START}&end_date={END}"
                "&timezone=UTC&wind_speed_unit=ms")
        h = j["hourly"]; keys = [k for k in h if k != "time"]
        with open(OUT / f"wx_{name}.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["time"] + keys)
            for i, t in enumerate(h["time"]): w.writerow([t] + [h[k][i] for k in keys])
        nn = {k: sum(x is not None for x in h[k]) for k in keys}
        status["steps"][name] = {"ok": True, "hours": len(h["time"]), "non_null": nn}
    except Exception as e:
        status["steps"][name] = {"ok": False, "error": repr(e)}
    time.sleep(3)

status["finished"] = dt.datetime.utcnow().isoformat() + "Z"
(OUT / "fetch_status.json").write_text(json.dumps(status, indent=1))
print(json.dumps(status, indent=1)[:4000])
