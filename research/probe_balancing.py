"""Probe: which Romanian balancing-market datasets does ENTSO-E serve? Writes research/data/balancing_probe.json.
Token from the ENTSOE_TOKEN secret; never printed."""
import os, re, io, json, zipfile, urllib.request, urllib.error, datetime as dt
TOK = os.environ.get("ENTSOE_TOKEN", ""); RO = "10YRO-TEL------P"
end = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0) - dt.timedelta(days=2)
start = end - dt.timedelta(days=7)
P = f"periodStart={start:%Y%m%d%H%M}&periodEnd={end:%Y%m%d%H%M}"
Q = {
 "A81_aFRR_daily": f"documentType=A81&businessType=B95&processType=A51&type_MarketAgreement.Type=A01&controlArea_Domain={RO}",
 "A81_mFRR_daily": f"documentType=A81&businessType=B95&processType=A47&type_MarketAgreement.Type=A01&controlArea_Domain={RO}",
 "A81_FCR_daily": f"documentType=A81&businessType=B95&processType=A52&type_MarketAgreement.Type=A01&controlArea_Domain={RO}",
 "A81_aFRR_any": f"documentType=A81&businessType=B95&processType=A51&controlArea_Domain={RO}",
 "A15_aFRR_procured": f"documentType=A15&processType=A51&area_Domain={RO}",
 "A15_mFRR_procured": f"documentType=A15&processType=A47&area_Domain={RO}",
 "A84_aFRR_energy_price": f"documentType=A84&processType=A16&businessType=A96&controlArea_Domain={RO}",
 "A84_mFRR_energy_price": f"documentType=A84&processType=A16&businessType=A97&controlArea_Domain={RO}",
 "A85_imbalance_price": f"documentType=A85&controlArea_Domain={RO}",
 "A89_contracted_reserves": f"documentType=A89&businessType=B95&processType=A51&type_MarketAgreement.Type=A01&controlArea_Domain={RO}",
}
def fetch(q):
    u = f"https://web-api.tp.entsoe.eu/api?securityToken={TOK}&{q}&{P}"
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "bereshit/1.0"}), timeout=90) as r:
            b = r.read(); st = r.status
    except urllib.error.HTTPError as e:
        b = e.read(); st = e.code
    except Exception as e:
        return {"error": repr(e)[:200]}
    if b[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(b)); b = b"".join(z.read(n) for n in z.namelist())
    t = b.decode("utf8", "replace")
    tags = {}
    for tag in ("procurement_Price.amount", "price.amount", "quantity", "activation_Price.amount", "imbalance_Price.amount", "secondaryQuantity"):
        v = re.findall(rf"<{re.escape(tag)}>([^<]+)</", t)
        if v: tags[tag] = {"n": len(v), "sample": v[:6]}
    res = re.findall(r"<resolution>([^<]+)</", t)
    flow = re.findall(r"<flowDirection.direction>([^<]+)</", t)
    reason = re.findall(r"<text>([^<]+)</", t)
    return {"http": st, "bytes": len(b), "points": t.count("<Point>"), "tags": tags, "resolution": sorted(set(res))[:4],
            "directions": sorted(set(flow)), "reason": reason[:2], "head": t[:300] if not tags else ""}
out = {"at": dt.datetime.utcnow().isoformat() + "Z", "window": [str(start), str(end)], "token_present": bool(TOK)}
for k, q in Q.items(): out[k] = fetch(q)
os.makedirs("research/data", exist_ok=True)
json.dump(out, open("research/data/balancing_probe.json", "w"), indent=1); print(json.dumps(out, indent=1)[:3000])
