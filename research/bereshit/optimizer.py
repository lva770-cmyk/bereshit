"""Daily battery schedule by linear programming (HiGHS via SciPy).

Variables per interval t: charge c_t, discharge d_t (MW), state of charge s_t (MWh).
Maximise  sum_t [ (p_t - wear - hurdle) * d_t - (p_t + hurdle) * c_t ] * dt_t
subject to  s_t = s_{t-1} + eta_c * c_t * dt_t - d_t * dt_t / eta_d,  s starts and ends empty,
            0 <= c, d <= P,  0 <= s <= E,  sum d_t dt_t <= cycles * E.
"""
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, csr_matrix
from .config import Battery

def schedule(prices, dt, bat: Battery, hurdle: float | None = None):
    p = np.asarray(prices, float); dt = np.asarray(dt, float); n = len(p)
    h = bat.hurdle_eur_per_mwh if hurdle is None else hurdle
    ec = ed = bat.rte ** 0.5
    P, E = bat.power_mw, bat.energy_mwh
    cost = np.concatenate([(p + h) * dt, -(p - bat.wear_eur_per_mwh - h) * dt, np.zeros(n)])
    A = lil_matrix((n, 3 * n))
    for t in range(n):
        A[t, t] = -ec * dt[t]; A[t, n + t] = dt[t] / ed; A[t, 2 * n + t] = 1.0
        if t: A[t, 2 * n + t - 1] = -1.0
    A_ub = csr_matrix(np.concatenate([np.zeros(n), dt, np.zeros(n)])[None, :])
    bounds = [(0, P)] * (2 * n) + [(0, E)] * (n - 1) + [(0, 0)]
    r = linprog(cost, A_ub=A_ub, b_ub=[bat.max_cycles_per_day * E], A_eq=A.tocsr(), b_eq=np.zeros(n),
                bounds=bounds, method="highs")
    if r.status != 0:
        raise RuntimeError(f"LP failed: {r.message}")
    c, d = r.x[:n], r.x[n:2 * n]
    net = d - c
    net[np.abs(net) < 1e-6] = 0.0     # remove simultaneous charge/discharge noise
    return net                         # MW, + = sell (discharge), - = buy (charge)

def settle(net_mw, prices, dt, bat: Battery):
    """Cash result of a fixed schedule at the given (actual) prices, after wear cost."""
    net = np.asarray(net_mw, float); p = np.asarray(prices, float); dt = np.asarray(dt, float)
    discharge = np.clip(net, 0, None)
    return float(np.sum(p * net * dt) - bat.wear_eur_per_mwh * np.sum(discharge * dt))
