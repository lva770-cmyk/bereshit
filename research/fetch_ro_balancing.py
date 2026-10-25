"""A year of Romanian balancing-capacity auction results from ENTSO-E (TR 17.1.B&C, documentType A81, daily market).
Writes research/data/ro_balancing.csv: hour (UTC), product, direction, quantity MW, price, currency, price unit.
Token from the ENTSOE_TOKEN secret; never printed."""
import os, re, io, csv, json, zipfile, time, urllib.request, urllib.error, datetime as dt
TOK = os.environ.get("ENTSOE_TOKEN", ""); RO = "10YRO-TEL------P"
PROD = {"aFRR": "A51", "mFRR": "A47", "FCR": "A52"}
DIRN = {"A01": "up", "A02": "down", "A03": "sym"}
start = dt.datetime(2025, 9, 1); end = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=2)
def get(q, a, b):
    u = f"https://web-api.tp.entsoe.eu/api?securityToken={TOK}&{q}&periodStart={a:%Y%m%d%H%M}&periodEnd={b:%Y%m%d%H%M}"
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "bereshit/1.0"}), timeout=120) as r: x = r.read()
            if x[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(x)); x = b"".join(z.read(n) for n in z.namelist())
            return x.decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            t = e.read().decode("utf8", "replace")
            if "No matching data" in t: return ""
            last = f"HTTP {e.code}: " + " ".join(re.findall(r"<text>([^<]+)</", t))[:200]
        except Exception as e: last = repr(e)[:200]
        time.sleep(8 * (k + 1))
    raise RuntimeError(last)
def parse(t):
    for ts in re.findall(r"<TimeSeries>(.*?)</TimeSeries>", t, re.S):
        d = (re.findall(r"<flowDirection.direction>([^<]+)<", ts) or ["?"])[0]
        cur = (re.findall(r"<currency_Unit.name>([^<]+)<", ts) or [""])[0]
        pu = (re.findall(r"<price_Measure_Unit.name>([^<]+)<", ts) or [""])[0]
        for per in re.findall(r"<Period>(.*?)</Period>", ts, re.S):
            st = dt.datetime.strptime(re.findall(r"<start>([^<]+)<", per)[0], "%Y-%m-%dT%H:%MZ")
            res = re.findall(r"<resolution>([^<]+)<", per)[0]; step = {"PT60M": 60, "PT15M": 15, "PT30M": 30, "P1D": 1440, "PT240M": 240}.get(res, 60)
            for p in re.findall(r"<Point>(.*?)</Point>", per, re.S):
                pos = int(re.findall(r"<position>(\d+)<", p)[0]); q = re.findall(r"<quantity>([^<]+)<", p); pr = re.findall(r"<procurement_Price.amount>([^<]+)<", p)
                yield st + dt.timedelta(minutes=step * (pos - 1)), step, DIRN.get(d, d), float(q[0]) if q else None, float(pr[0]) if pr else None, cur, pu
rows, log = [], {}
for name, pt in PROD.items():
    a = start; n = 0
    while a < end:
        b = min(a + dt.timedelta(days=30), end)
        try:
            t = get(f"documentType=A81&businessType=B95&processType={pt}&type_MarketAgreement.Type=A01&controlArea_Domain={RO}", a, b)
            for r in parse(t): rows.append((r[0].strftime("%Y-%m-%dT%H:%M"), name) + r[1:]); n += 1
        except Exception as e: log[f"{name} {a:%Y-%m-%d}"] = str(e)
        a = b; time.sleep(2)
    log[name] = n
seen = {}
for r in rows: seen[(r[0], r[1], r[3])] = r   # de-duplicate (time, product, direction)
os.makedirs("research/data", exist_ok=True)
with open("research/data/ro_balancing.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["time_utc", "product", "minutes", "direction", "quantity_mw", "price", "currency", "price_unit"])
    for k in sorted(seen): w.writerow(seen[k])
json.dump({"at": dt.datetime.utcnow().isoformat() + "Z", "rows": len(seen), **log}, open("research/data/ro_balancing_status.json", "w"), indent=1)
print(len(seen), log)
