"""Diagnostics: what the price API returns for a zone code (written to probe.json)."""
import json, sys, urllib.request, urllib.error, datetime as dt
out = {}
for bzn in sys.argv[1:]:
    url = f"https://api.energy-charts.info/price?bzn={bzn}&start=2026-10-01&end=2026-10-03"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bereshit/1.0"}), timeout=90) as r:
            j = json.load(r)
        ts = j.get("unix_seconds", []); pr = j.get("price", [])
        out[bzn] = {"ok": True, "n": len(ts), "nonnull": sum(p is not None for p in pr), "keys": list(j)[:8],
                    "first": [dt.datetime.utcfromtimestamp(t).isoformat() for t in ts[:3]], "step_s": (ts[1] - ts[0]) if len(ts) > 1 else None,
                    "sample": pr[:6], "unit": j.get("unit")}
    except urllib.error.HTTPError as e:
        out[bzn] = {"ok": False, "http": e.code, "body": e.read()[:300].decode("utf8", "replace")}
    except Exception as e:
        out[bzn] = {"ok": False, "error": repr(e)}
json.dump(out, open("probe.json", "w"), indent=1); print(json.dumps(out, indent=1))
