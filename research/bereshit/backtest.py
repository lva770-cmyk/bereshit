"""Walk-forward backtest: forecast at D-1 -> fixed schedule -> settle at actual D prices."""
import numpy as np
import pandas as pd
from .config import Battery
from .optimizer import schedule, settle
from .forecast import FORECASTERS, _profile, SLOTS

def run(price_days: dict, bat: Battery, forecaster="ridge", start=None, end=None,
        train_days=56, lam=1.0, fund_by_day=None, hurdle=None):
    days = sorted(price_days)
    rows = []
    for i, d in enumerate(days):
        if (start and d < start) or (end and d > end): continue
        actual = np.asarray(price_days[d], float)
        if len(actual) != SLOTS: continue            # skip DST-change days and hourly days
        past = days[:i]
        if len(past) < 14: continue
        f = FORECASTERS[forecaster](past, price_days, target_day=d, train_days=train_days, lam=lam,
                                    fund_by_day=fund_by_day if forecaster == "ridge_fund" else None)
        dt = np.full(SLOTS, 0.25)
        net_f = schedule(f, dt, bat, hurdle=hurdle)
        net_pf = schedule(actual, dt, bat, hurdle=0.0)
        rows.append(dict(day=d, realised=settle(net_f, actual, dt, bat), perfect=settle(net_pf, actual, dt, bat),
                         fc_mae=float(np.mean(np.abs(f - actual))),
                         fc_spread=float(f.max() - f.min()), act_spread=float(actual.max() - actual.min()),
                         mwh_out=float(np.clip(net_f, 0, None).sum() * 0.25)))
    df = pd.DataFrame(rows)
    return df

def summary(df):
    return dict(days=len(df), realised=df.realised.sum(), perfect=df.perfect.sum(),
                capture=df.realised.sum() / df.perfect.sum(), loss_days=int((df.realised < 0).sum()),
                worst_day=float(df.realised.min()), mae=float(df.fc_mae.mean()))

if __name__ == "__main__":
    import argparse, datetime as dt
    from . import data
    from .forecast import SLOTS
    ap = argparse.ArgumentParser(description="Walk-forward backtest on Energy-Charts day-ahead prices")
    ap.add_argument("--zone", default="HU"); ap.add_argument("--tz", default="Europe/Budapest")
    ap.add_argument("--start", default="2025-10-01"); ap.add_argument("--end", default="2026-09-28")
    ap.add_argument("--hours", type=float, default=4.0, help="storage duration (h) of the arbitrage part")
    ap.add_argument("--forecaster", default="blend", choices=["naive", "blend", "ridge"])
    ap.add_argument("--hurdle", type=float, default=0.0)
    a = ap.parse_args()
    s, e = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    warm = (s - dt.timedelta(days=92)).isoformat()
    P = data.to_days(data.prices(a.zone, warm, a.end), a.tz)
    bat = Battery(power_mw=1.0, energy_mwh=a.hours)
    df = run(P, bat, a.forecaster, start=s, end=e, hurdle=a.hurdle)
    print(summary(df)); df.to_csv(f"backtest_{a.zone}_{a.forecaster}_{a.hours:g}h.csv", index=False)
