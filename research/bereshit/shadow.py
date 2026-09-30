"""Shadow trading: log tomorrow's schedule before gate closure, settle it after prices are out.

    python -m bereshit.shadow plan    # run daily ~11:00 local (before SDAC gate closure 12:00)
    python -m bereshit.shadow settle  # run daily after ~13:30 local, settles all open plans
    python -m bereshit.shadow report  # cumulative P&L vs perfect foresight

No orders are sent anywhere. Plans and results are written to Settings.log_dir as JSON/CSV.
"""
import argparse, datetime as dt, json, os
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo
from .config import Settings
from . import data
from .forecast import FORECASTERS, fund_profiles, SLOTS, _profile
from .optimizer import schedule, settle

def _today(tz): return dt.datetime.now(ZoneInfo(tz)).date()

def plan(S: Settings, target=None):
    tz = S.market.tz; today = _today(tz)
    target = target or today + dt.timedelta(days=1)
    start = (target - dt.timedelta(days=S.train_days + 10)).isoformat()
    P = data.to_days(data.prices(S.market.zone, start, (target - dt.timedelta(days=1)).isoformat()), tz)
    past = sorted(d for d in P if d < target)
    fund = None
    if S.forecaster == "ridge_fund":
        raise SystemExit("ridge_fund needs a solar/wind/load *forecast* feed for D – plug one into data.py first.")
    f = FORECASTERS[S.forecaster](past, P, target_day=target, train_days=S.train_days, lam=S.ridge_lambda)
    net = schedule(f, np.full(SLOTS, 0.25), S.battery)
    os.makedirs(S.log_dir, exist_ok=True)
    rec = dict(target=target.isoformat(), created=dt.datetime.now(ZoneInfo(tz)).isoformat(timespec="seconds"),
               forecaster=S.forecaster, battery=S.battery.__dict__, forecast_eur_mwh=[round(x, 2) for x in f],
               net_mw=[round(x, 3) for x in net], status="planned")
    path = os.path.join(S.log_dir, f"plan_{target.isoformat()}.json")
    if os.path.exists(path):
        raise SystemExit(f"{path} exists – plans are write-once so the shadow record stays honest.")
    json.dump(rec, open(path, "w"), indent=1)
    print(f"planned {target}: sell {np.clip(net,0,None).sum()*0.25:.0f} MWh, buy {np.clip(-net,0,None).sum()*0.25:.0f} MWh -> {path}")
    return path

def settle_open(S: Settings):
    tz = S.market.tz
    for fn in sorted(os.listdir(S.log_dir)):
        if not fn.startswith("plan_"): continue
        path = os.path.join(S.log_dir, fn); rec = json.load(open(path))
        if rec["status"] != "planned": continue
        day = dt.date.fromisoformat(rec["target"])
        P = data.to_days(data.prices(S.market.zone, day.isoformat(), day.isoformat()), tz)
        if day not in P or len(P[day]) != SLOTS: continue
        actual = np.asarray(P[day], float); d = np.full(SLOTS, 0.25)
        rec.update(actual_eur_mwh=[round(x, 2) for x in actual], status="settled",
                   realised_eur=round(settle(rec["net_mw"], actual, d, S.battery), 2),
                   perfect_eur=round(settle(schedule(actual, d, S.battery, hurdle=0.0), actual, d, S.battery), 2))
        json.dump(rec, open(path, "w"), indent=1)
        print(f"settled {day}: {rec['realised_eur']:,.0f} € vs perfect {rec['perfect_eur']:,.0f} €")

def report(S: Settings):
    recs = [json.load(open(os.path.join(S.log_dir, f))) for f in sorted(os.listdir(S.log_dir)) if f.startswith("plan_")]
    df = pd.DataFrame([r for r in recs if r["status"] == "settled"])
    if df.empty: print("nothing settled yet"); return
    print(df[["target", "realised_eur", "perfect_eur"]].to_string(index=False))
    print(f"capture {df.realised_eur.sum() / df.perfect_eur.sum():.1%} over {len(df)} days")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "settle", "report"])
    ap.add_argument("--date"); ap.add_argument("--forecaster", default="blend")
    a = ap.parse_args(); S = Settings(forecaster=a.forecaster)
    if a.cmd == "plan": plan(S, dt.date.fromisoformat(a.date) if a.date else None)
    elif a.cmd == "settle": settle_open(S)
    else: report(S)
