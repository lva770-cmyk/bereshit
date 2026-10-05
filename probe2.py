"""Compare German day-ahead sources for one day; list ENTSO-E TimeSeries metadata. Writes probe2.json."""
import json, os, urllib.request, datetime as dt, xml.etree.ElementTree as ET
D = "2026-10-03"; out = {}
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "bereshit/1.0"}), timeout=90) as r: return r.read()
j = json.loads(get(f"https://api.energy-charts.info/price?bzn=DE-LU&start={D}&end={D}"))
out["energy_charts_first"] = j["price"][:6]; out["ec_first_ts"] = dt.datetime.utcfromtimestamp(j["unix_seconds"][0]).isoformat()
tok = os.environ["ENTSOE_TOKEN"]
x = get(f"https://web-api.tp.entsoe.eu/api?securityToken={tok}&documentType=A44&in_Domain=10Y1001A1001A82H&out_Domain=10Y1001A1001A82H&periodStart=202610022200&periodEnd=202610032200")
root = ET.fromstring(x); ns = {"n": root.tag.split("}")[0].strip("{")}
series = []
for ts in root.findall("n:TimeSeries", ns):
    meta = {c.tag.split("}")[1]: (c.text or "").strip() for c in ts if len(c) == 0}
    for per in ts.findall("n:Period", ns):
        pts = [float(p.find("n:price.amount", ns).text) for p in per.findall("n:Point", ns)][:6]
        series.append({"meta": meta, "res": per.find("n:resolution", ns).text, "start": per.find("n:timeInterval/n:start", ns).text, "first": pts})
out["entsoe_series"] = series
json.dump(out, open("probe2.json", "w"), indent=1); print(json.dumps(out, indent=1))
