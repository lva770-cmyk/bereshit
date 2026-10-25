"""Romanian intraday prices from OPCOM's public report pages (research data for the Project 50 simulation).

  research/data/ro_ida.csv   date,auction,interval,price_eur          - IDA1/IDA2/IDA3 auction clearing price per 15-min
  research/data/ro_idct.csv  date,res,interval,min,max,last,ropex_id,pmp1,vol_buy,vol_sell   - continuous market (RON/MWh, MWh)

Dates are delivery days. Resumes: dates already in the files are skipped. Manual research only (no live screen)."""
import os, re, csv, sys, time, html, datetime as dt, urllib.request, urllib.parse, http.cookiejar
D = "research/data"; IDA, IDCT = f"{D}/ro_ida.csv", f"{D}/ro_idct.csv"
START = dt.date(2025, 9, 24)
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("User-Agent", "Mozilla/5.0 (research; bereshit)"), ("Accept-Language", "ro,en")]
U_IDA = "https://www.opcom.ro/rapoarte-ida-rezultate-cuplare/ro"; U_ID = "https://www.opcom.ro/rapoarte-pi-raport-cuplare-pi/ro"

def num(s):
    s = s.strip()
    if not s or s == "-": return ""
    try: return float(s.replace(".", "").replace(",", "."))
    except ValueError: return ""

def cells(tab):
    out = []
    for r in re.findall(r"<tr.*?</tr>", tab, re.S):
        c = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<t[dh][^>]*>.*?</t[dh]>", r, re.S)]
        if any(c): out.append(c)
    return out

def token(u):
    h = op.open(u, timeout=60).read().decode("utf8", "replace")
    return re.search(r'name="_token" value="([^"]+)"', h).group(1)

def post(u, data, tries=4):
    for k in range(tries):
        try:
            data["_token"] = TOK[u]
            return op.open(urllib.request.Request(u, urllib.parse.urlencode(data).encode()), timeout=90).read().decode("utf8", "replace")
        except Exception as e:
            print("retry", u, data.get("ziua") or data.get("data_calendar_ro"), repr(e)[:80]); time.sleep(5 * (k + 1))
            try: TOK[u] = token(u)
            except Exception: pass
    return ""

def parse_ida(h):
    """[(auction, interval, price_eur)] - tables with 'Pret RO[EUR/MWh]' in page order = IDA1, IDA2, IDA3."""
    out = []; n = 0
    for tab in re.findall(r"<table.*?</table>", h, re.S):
        c = cells(tab)
        if not c or not any("Pret RO" in x for x in c[0]): continue
        n += 1
        for r in c[2:]:
            if r and r[0].isdigit() and len(r) > 1 and num(r[1]) != "": out.append((f"IDA{n}", int(r[0]), num(r[1])))
    return out

def parse_id(h):
    """{delivery_date: [(interval, min, max, last, ropex, pmp1, vbuy, vsell)]}"""
    days = [dt.datetime.strptime(x, "%d.%m.%Y").date() for x in re.findall(r"Ziua de livrare (\d\d\.\d\d\.\d{4})", h)]
    tabs = [cells(t) for t in re.findall(r"<table.*?</table>", h, re.S)]
    tabs = [c for c in tabs if len(c) > 3 and any("ROPEX_ID_H" in x for x in c[1])]
    out = {}
    for d, c in zip(days, tabs):
        rows = []
        for r in c[3:]:
            if r and re.match(r"^\d", r[0]) and len(r) >= 8:
                rows.append((r[0], *[num(x) for x in r[1:8]]))
        out[d] = rows
    return out

def done(path, col=0):
    if not os.path.exists(path): return set()
    return {r[col] for r in csv.reader(open(path))}

def ecb():
    """Daily ECB EUR/RON reference rate -> research/data/eur_ron.csv (to convert continuous-market RON prices)."""
    try:
        t = op.open("https://data-api.ecb.europa.eu/service/data/EXR/D.RON.EUR.SP00.A?format=csvdata&startPeriod=2025-08-01", timeout=60).read().decode()
        rows = [(r["TIME_PERIOD"], r["OBS_VALUE"]) for r in csv.DictReader(t.splitlines()) if r.get("OBS_VALUE")]
        with open(f"{D}/eur_ron.csv", "w", newline="") as f: w = csv.writer(f); w.writerow(["date", "eur_ron"]); w.writerows(rows)
        print("ECB rates", len(rows))
    except Exception as e: print("ECB failed", e)

if __name__ == "__main__":
    os.makedirs(D, exist_ok=True)
    if not os.environ.get("PART"): ecb()
    end = dt.date.fromisoformat(os.environ["END"]) if os.environ.get("END") else dt.date.today() - dt.timedelta(days=1)
    if os.environ.get("START"): START = dt.date.fromisoformat(os.environ["START"])
    have_ida, have_id = done(IDA), done(IDCT)
    sfx = os.environ.get("PART")
    if sfx:   # parallel chunk: write to its own part files (merged by the workflow)
        IDA, IDCT = f"{D}/part_ida_{sfx}.csv", f"{D}/part_idct_{sfx}.csv"
    TOK = {U_IDA: token(U_IDA), U_ID: token(U_ID)}
    fi = open(IDA, "a", newline=""); wi = csv.writer(fi)
    fc = open(IDCT, "a", newline=""); wc = csv.writer(fc)
    if not have_ida or sfx: wi.writerow(["date", "auction", "interval", "price_eur"])
    if not have_id or sfx: wc.writerow(["date", "res", "interval", "min", "max", "last", "ropex_id", "pmp1", "vol_buy", "vol_sell"])
    d = START; n = 0; t0 = time.time()
    while d <= end and time.time() - t0 < 50 * 60:
        s = d.isoformat()
        if s not in have_ida:
            rows = parse_ida(post(U_IDA, {"data_calendar_ro": d.strftime("%d/%m/%Y"), "buton": "Refresh", "lang": "ro"}))
            for a, i, p in rows: wi.writerow([s, a, i, p])
            print(s, "IDA rows", len(rows)); n += 1; time.sleep(0.6)
        if s not in have_id:
            got = {}
            for res in ("60",):   # 15-min continuous products are not published for most of the history
                q = parse_id(post(U_ID, {"ziua": (d + dt.timedelta(days=1)).strftime("%d/%m/%Y"), "buton": "Refresh",
                                         "action": "trading_for", "limba": "ro", "tip": res})).get(d, [])
                got[res] = q; time.sleep(0.6)
            for res, q in got.items():
                for r in q: wc.writerow([s, res, *r])
            print(s, "IDCT rows", {k: len(v) for k, v in got.items()}); n += 1
        fi.flush(); fc.flush(); d += dt.timedelta(days=1)
    print("done", n, "fetches")
