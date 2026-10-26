"""Year backtest of the live Project 50 strategy: DA plan (2 discharges, blend forecast) + IDA1/IDA2/IDA3 re-trading
(intraday_live.apply_day). Writes intraday-RO2.json (read by the Project 50 screen)."""
import csv, collections, json, sys, datetime as dt, numpy as np
sys.path.insert(0, "."); import engine, intraday_live as IL
R = "research/data/"
P = {dt.date.fromisoformat(r["date"]): [float(r[f"q{i}"]) for i in range(96)] for r in csv.DictReader(open(R + "ro_prices.csv"))}
ida = collections.defaultdict(dict)
for r in csv.DictReader(open(R + "ro_ida.csv")): ida[(r["date"], r["auction"])][int(r["interval"])] = float(r["price_eur"])
def prices(day):
    out = {}
    for a in IL.AUCTIONS:
        m = ida.get((day, a))
        if m:
            n = 100 if max(m) > 96 else 96; v = IL.to96([m.get(i + 1) for i in range(n)])
            if v: out[a] = v
    return out
engine.use_zone("RO2")
def run(xcap):
    tot = collections.Counter(); days = []; month = collections.defaultdict(lambda: [0.0, 0.0])
    for d in sorted(P):
        hist = [P.get(d - dt.timedelta(days=k)) for k in range(7, 0, -1)]; a = P[d]; key = d.isoformat(); pr = prices(key)
        if not all(h is not None for h in hist) or not pr: continue
        net = engine.schedule(engine.blend(hist)); da = engine.settle(net, a)
        rec = {"net": list(net), "actual": a}; IL.apply_day(rec, pr, engine.P_MW, engine.E_MWH, engine.CYC, xcap=xcap)
        idp = rec.get("intraday_pnl", 0); tot["da"] += da; tot["id"] += idp
        for k, v in rec.get("intraday", {}).items(): tot[k] += v["pnl"]
        tot["perfect"] += engine.settle(engine.schedule(a), a); days.append(key)
        month[key[:7]][0] += da; month[key[:7]][1] += idp
    k = 365 / len(days)
    return {"days": len(days), "period": [days[0], days[-1]], "xcap_mw": xcap, "da": round(tot["da"] * k), "intraday": round(tot["id"] * k),
            "by_auction": {a: round(tot[a] * k) for a in IL.AUCTIONS}, "perfect_da": round(tot["perfect"] * k),
            "monthly": {m: [round(x), round(y)] for m, (x, y) in sorted(month.items())}}
if __name__ == "__main__":
    out = {"zone": "RO2", "strategy": "DA (2 discharges) + IDA1/IDA2/IDA3 re-trading", "battery": {"power_mw": engine.P_MW, "energy_mwh": engine.E_MWH, "max_cycles_day": engine.CYC, "wear_eur_mwh": engine.WEAR},
           "live_xcap_mw": IL.XCAP, "base": run(25.0), "conservative": run(10.0), "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    json.dump(out, open("intraday-RO2.json", "w"), indent=1)
    for k in ("base", "conservative"): print(k, {x: out[k][x] for x in ("days", "da", "intraday", "by_auction", "perfect_da")})
