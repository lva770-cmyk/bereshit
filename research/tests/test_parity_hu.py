"""Parity with the in-browser JS mirror used for the full-year backtest (real HU prices)."""
import datetime as dt, pathlib
import numpy as np
from bereshit.config import Battery
from bereshit.forecast import ridge, naive, blend
from bereshit.optimizer import schedule, settle

FIX = pathlib.Path(__file__).parent / "fixtures" / "hu_2026-08-27_2026-09-21.txt"
P = {dt.date.fromisoformat(l.split(":")[0]): np.array([float(x) for x in l.split(":")[1].split(",")])
     for l in FIX.read_text().strip().splitlines()}
JS = {  # values printed by the JS mirror on the same data (train_days=17, lam=1, 1 MW / 4 MWh)
 "2026-09-19": dict(f5=[123.2764, 85.6363, 76.6449, 62.1463, 91.8126], real=829.0484, naive=891.4204, blend=882.6961),
 "2026-09-20": dict(f5=[40.3757, 34.8809, 24.867, 37.4324, 49.9512], real=836.5108, naive=897.3908, blend=892.3166),
 "2026-09-21": dict(f5=[128.0237, 80.7752, 110.2355, 137.8089, 100.9017], real=643.2188, naive=793.6421, blend=769.8739),
}

def test_parity():
    b = Battery(power_mw=1, energy_mwh=4); dt96 = np.full(96, .25)
    for k, js in JS.items():
        day = dt.date.fromisoformat(k); past = sorted(d for d in P if d < day)
        f = ridge(past, P, target_day=day, train_days=17, lam=1.0)
        assert np.allclose(f[40:45], js["f5"], atol=1e-3), (k, f[40:45])
        assert abs(settle(schedule(f, dt96, b, hurdle=0), P[day], dt96, b) - js["real"]) < 0.05
        # naive/blend forecasts contain flat stretches (e.g. many 0 €/MWh slots), so the LP has several
        # equally optimal schedules; SciPy-HiGHS and HiGHS-wasm may pick different ones -> allow 0.1 %.
        assert abs(settle(schedule(naive(past, P), dt96, b, hurdle=0), P[day], dt96, b) - js["naive"]) < 1e-3 * js["naive"]
        assert abs(settle(schedule(blend(past, P), dt96, b, hurdle=0), P[day], dt96, b) - js["blend"]) < 1e-3 * js["blend"]
