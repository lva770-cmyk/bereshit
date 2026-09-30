import datetime as dt
import numpy as np
from bereshit.config import Battery
from bereshit.optimizer import schedule, settle
from bereshit.backtest import run, summary

AT_2026_08_02 = [189.09,171.30,161.10,160.77,160.86,156.81,162.01,160.57,159.15,156.92,157.31,154.80,157.75,154.04,154.94,154.78,157.79,153.93,154.35,153.26,160.62,163.67,161.63,159.18,162.26,154.80,153.34,140.00,154.10,142.60,136.11,122.32,152.74,130.33,112.43,93.22,104.96,84.61,54.92,11.31,11.11,4.36,2.83,0.99,0.89,1.19,3.36,4.21,5.32,5.48,6.59,7.87,8.44,6.30,8.66,6.81,9.61,8.65,7.24,5.68,10.11,11.85,13.56,14.32,19.42,22.68,117.33,167.75,71.34,141.89,142.73,164.44,160.86,174.59,189.48,190.94,183.58,183.56,189.23,192.75,190.30,186.85,190.94,197.10,194.87,190.31,187.05,181.50,190.52,184.88,181.11,167.94,188.48,170.77,164.56,159.95]

def test_matches_earlier_lp():
    # same LP as the Europe-wide study: 1 MW / 4 MWh gave 700.195 €/day on this day
    b = Battery(power_mw=1, energy_mwh=4)
    net = schedule(AT_2026_08_02, np.full(96, .25), b, hurdle=0)
    assert abs(settle(net, AT_2026_08_02, np.full(96, .25), b) - 700.195) < 0.5

def test_energy_and_power_limits():
    b = Battery(power_mw=80, energy_mwh=320)
    net = schedule(AT_2026_08_02, np.full(96, .25), b)
    assert net.max() <= 80 + 1e-6 and net.min() >= -80 - 1e-6
    assert np.clip(net, 0, None).sum() * .25 <= 2 * 320 + 1e-6

def _synthetic(n=140, seed=1):
    rng = np.random.default_rng(seed); days = {}
    t = np.arange(96) / 96
    for i in range(n):
        d = dt.date(2026, 1, 1) + dt.timedelta(days=i)
        base = 110 + 20 * np.sin(i / 9)
        shape = -70 * np.exp(-((t - .55) / .12) ** 2) + 60 * np.exp(-((t - .83) / .06) ** 2)
        wk = -15 if d.weekday() >= 5 else 0
        days[d] = base + shape + wk + rng.normal(0, 12, 96)
    return days

def test_backtest_capture_bounds():
    P = _synthetic(); b = Battery(power_mw=1, energy_mwh=4)
    for fc in ("naive", "blend", "ridge"):
        s = summary(run(P, b, fc, start=dt.date(2026, 3, 1)))
        assert 0.3 < s["capture"] <= 1.0 + 1e-9, (fc, s)

def test_ridge_beats_naive_on_structured_data():
    P = _synthetic(); b = Battery(power_mw=1, energy_mwh=4)
    r = summary(run(P, b, "ridge", start=dt.date(2026, 3, 1)))["mae"]
    n = summary(run(P, b, "naive", start=dt.date(2026, 3, 1)))["mae"]
    assert r < n
