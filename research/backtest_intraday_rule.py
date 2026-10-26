"""Year backtest of the Project 50 rule: DA commits 1 discharge; 2nd discharge intraday at >=310, buy back <=150
(forced buy at the last window). Compared with DA committing 2 discharges. Writes intraday-rule-RO2.json."""
import csv, collections, json, sys, datetime as dt, numpy as np
sys.path.insert(0, "."); import engine, intraday_rule as IR
R = "research/data/"
P = {dt.date.fromisoformat(r["date"]): [float(r[f"q{i}"]) for i in range(96)] for r in csv.DictReader(open(R + "ro_prices.csv"))}
rows = collections.defaultdict(list)
for r in csv.DictReader(open(R + "ro_idct.csv")):
    if r["res"] == "60":
        f = lambda k: float(r[k]) if r[k] else None
        rows[r["date"]].append((r["interval"], f("min"), f("max"), f("last"), f("ropex_id"), f("pmp1"), f("vol_buy") or 0, f("vol_sell") or 0))
rates = {r["date"]: float(r["eur_ron"]) for r in csv.DictReader(open(R + "eur_ron.csv"))}
def rate(d):
    for k in range(10):
        v = rates.get((dt.date.fromisoformat(d) - dt.timedelta(days=k)).isoformat())
        if v: return v
    return 5.08
engine.use_zone("RO2"); engine.P_MW, engine.E_MWH, engine.WEAR = 50.0, 89.5, 0.0
def run(sell=310, buy=150, share=0.2):
    tot = collections.Counter(); days = []
    for d in sorted(P):
        hist = [P.get(d - dt.timedelta(days=k)) for k in range(7, 0, -1)]; a = P[d]; key = d.isoformat()
        if not all(h is not None for h in hist) or key not in rows: continue
        f = engine.blend(hist)
        engine.CYC = 2.0; n2 = engine.schedule(f); da2 = engine.settle(n2, a)
        engine.CYC = 1.0; n1 = engine.schedule(f); da1 = engine.settle(n1, a)
        r = IR.run_day(n1, IR.hourly(rows[key], rate(key)), sell_at=sell, buy_at=buy, share=share, da=a)
        tot["da2"] += da2; tot["da1"] += da1; tot["id"] += r["pnl"]; tot["sold"] += r["sold_mwh"]; tot["open"] += r["open_mwh"]
        tot["deadline_mwh"] += sum(t["mw"] for t in r["trades"] if t["kind"] == "deadline")
        tot["sale_days"] += bool(r["sold_mwh"]); days.append(key)
    k = 365 / len(days)
    return {"days": len(days), "period": [days[0], days[-1]], "da_two_discharges": round(tot["da2"] * k), "da_one_discharge": round(tot["da1"] * k),
            "intraday_rule": round(tot["id"] * k), "sold_mwh_year": round(tot["sold"] * k), "deadline_buy_mwh_year": round(tot["deadline_mwh"] * k),
            "days_with_sale_share": round(tot["sale_days"] / len(days), 3), "open_mwh_total": round(tot["open"], 1)}
if __name__ == "__main__":
    out = {"rule": {"sell_at": 310, "buy_at": 150, "share": 0.2}, "base": run()}
    for s, b in ((250, 150), (310, 120), (360, 150)):
        out[f"alt_{s}_{b}"] = run(s, b)
    out["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(out, open("intraday-rule-RO2.json", "w"), indent=1)
    for k, v in out.items(): print(k, v)
