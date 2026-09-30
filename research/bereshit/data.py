"""Market data from the Energy-Charts API (Fraunhofer ISE, CC BY 4.0).

Day-ahead prices are the SDAC/HUPX results; generation and load are published actuals.
All series are returned on a 15-minute UTC grid (hourly history is repeated 4x).
"""
import json, time, urllib.request
import numpy as np
import pandas as pd

API = "https://api.energy-charts.info"

def _get(path, retries=4):
    for k in range(retries):
        try:
            with urllib.request.urlopen(API + path, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and k < retries - 1:
                time.sleep(15 * (k + 1)); continue
            raise

def _to_15min(ts, vals, name):
    s = pd.Series(vals, index=pd.to_datetime(ts, unit="s", utc=True), name=name, dtype="float64")
    s = s[~s.index.duplicated()]
    return s.resample("15min").ffill(limit=3)

def prices(zone, start, end):
    j = _get(f"/price?bzn={zone}&start={start}&end={end}")
    return _to_15min(j["unix_seconds"], j["price"], "price")

def power(country, start, end):
    j = _get(f"/public_power?country={country}&start={start}&end={end}")
    pick = {t["name"]: t["data"] for t in j["production_types"]}
    cols = {"solar": "Solar", "wind": "Wind onshore", "load": "Load"}
    return pd.concat([_to_15min(j["unix_seconds"], pick.get(v, [None] * len(j["unix_seconds"])), k)
                      for k, v in cols.items()], axis=1)

def to_days(series, tz):
    """Split a 15-min UTC series into delivery days (local date) -> dict[date] = np.array."""
    local = series.tz_convert(tz)
    out = {}
    for day, g in local.groupby(local.index.date):
        out[day] = g.to_numpy()
    return out
