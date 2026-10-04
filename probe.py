"""Diagnostics: is each price source reachable from GitHub Actions right now? Writes probe.json."""
import json, urllib.request, urllib.error, datetime as dt, time
T = (dt.date.today()).isoformat()
URLS = {
 "energy-charts HU": f"https://api.energy-charts.info/price?bzn=HU&start={T}&end={T}",
 "energy-charts DE-LU": f"https://api.energy-charts.info/price?bzn=DE-LU&start={T}&end={T}",
 "energy-charts RO": f"https://api.energy-charts.info/price?bzn=RO&start={T}&end={T}",
 "energy-charts root": "https://api.energy-charts.info/",
 "smard DE-LU index": "https://www.smard.de/app/chart_data/4169/DE-LU/index_quarterhour.json",
 "entsoe web": "https://web-api.tp.entsoe.eu/api",
}
out = {"at": dt.datetime.utcnow().isoformat() + "Z"}
for k, u in URLS.items():
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "bereshit/1.0"}), timeout=60) as r:
            b = r.read(); out[k] = {"http": r.status, "bytes": len(b), "head": b[:160].decode("utf8", "replace"), "s": round(time.time() - t0, 1)}
    except urllib.error.HTTPError as e:
        out[k] = {"http": e.code, "body": e.read()[:160].decode("utf8", "replace"), "s": round(time.time() - t0, 1)}
    except Exception as e:
        out[k] = {"error": repr(e)[:200], "s": round(time.time() - t0, 1)}
json.dump(out, open("probe.json", "w"), indent=1); print(json.dumps(out, indent=1))
