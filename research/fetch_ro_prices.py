"""Fetch a year of real OPCOM (RO) day-ahead prices, 96 quarter-hours per CET delivery day, for offline studies.
Uses the live engine's strict fetch (Energy-Charts -> ENTSO-E fallback). Output: research/data/ro_prices.csv."""
import sys, os, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yearly

end = dt.datetime.now(ZoneInfo("Europe/Budapest")).date() - dt.timedelta(days=1)
P = yearly.fetch("RO", dt.date(2025, 9, 25), end)
with open("research/data/ro_prices.csv", "w") as f:
    f.write("date," + ",".join(f"q{i}" for i in range(96)) + "\n")
    for d in sorted(P):
        f.write(d.isoformat() + "," + ",".join(f"{x:.2f}" for x in P[d]) + "\n")
print(len(P), "days", min(P), max(P))
