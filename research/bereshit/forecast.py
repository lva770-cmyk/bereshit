"""Day-ahead price forecasts made at D-1 before gate closure.

Only information available at D-1 11:00 local is used: day-ahead prices up to and including D-1
(published after the D-2 auction) and, for `ridge_fund`, a forecast of D's solar, wind and load.
In backtests `ridge_fund` uses *actual* D fundamentals, i.e. it is an upper bound for a very good
weather/load forecast, not a realistic result.
"""
import numpy as np

SLOTS = 96

def _profile(day_prices):
    """Resample any day (92/96/100 slots or 24 hourly) to 96 slots."""
    x = np.asarray(day_prices, float)
    if len(x) == SLOTS: return x
    return np.interp(np.linspace(0, 1, SLOTS, endpoint=False) + 0.5 / SLOTS,
                     np.linspace(0, 1, len(x), endpoint=False) + 0.5 / len(x), x)

def _hist(days, prices_by_day, k):
    """Profile of the k-th previous day (k=1 -> D-1). Falls back to nearest available."""
    for j in range(k, k + 7):
        if j <= len(days) and days[-j] in prices_by_day:
            return _profile(prices_by_day[days[-j]])
    return None

def naive(past_days, P, **_):
    return _hist(past_days, P, 1)

def blend(past_days, P, **_):
    d1, d7 = _hist(past_days, P, 1), _hist(past_days, P, 7)
    wk = np.mean([_hist(past_days, P, k) for k in range(1, 8)], axis=0)
    return 0.5 * d1 + 0.25 * d7 + 0.25 * wk

def _features(past_days, P, target_day, fund=None):
    d1, d2, d7 = _hist(past_days, P, 1), _hist(past_days, P, 2), _hist(past_days, P, 7)
    wd = target_day.weekday()
    const = np.ones(SLOTS)
    cols = [const, d1, d2, d7, np.full(SLOTS, d1.mean()), np.full(SLOTS, d1.max() - d1.min()),
            np.full(SLOTS, float(wd >= 5)), np.full(SLOTS, float(wd == 0))]
    if fund is not None:
        cols += [fund["solar"], fund["wind"], fund["load"]]
    return np.stack(cols, axis=1)  # (96, k)

def ridge(past_days, P, target_day, train_days=56, lam=1.0, fund_by_day=None, **_):
    """Per-slot ridge regression trained on the last `train_days` days (rolling, no look-ahead)."""
    use_f = fund_by_day is not None
    X, Y = [], []
    hist = past_days[-train_days:]
    for i, d in enumerate(hist):
        prior = past_days[: len(past_days) - len(hist) + i]
        if len(prior) < 8 or d not in P: continue
        f = None
        if use_f:
            if d not in fund_by_day: continue
            f = fund_by_day[d]
        X.append(_features(prior, P, d, f)); Y.append(_profile(P[d]))
    ftarget = fund_by_day.get(target_day) if use_f else None
    if len(X) < 14 or (use_f and ftarget is None):
        return blend(past_days, P)
    X, Y = np.stack(X), np.stack(Y)            # (n, 96, k), (n, 96)
    Xt = _features(past_days, P, target_day, ftarget)
    out = np.empty(SLOTS)
    k = X.shape[2]
    for s in range(SLOTS):
        A, y = X[:, s, :], Y[:, s]
        mu, sd = A[:, 1:].mean(0), A[:, 1:].std(0) + 1e-9      # standardise, keep intercept
        Z = np.column_stack([np.ones(len(A)), (A[:, 1:] - mu) / sd])
        reg = lam * np.eye(k); reg[0, 0] = 0
        w = np.linalg.solve(Z.T @ Z + reg, Z.T @ y)
        zt = np.concatenate([[1.0], (Xt[s, 1:] - mu) / sd])
        out[s] = zt @ w
    return out

def fund_profiles(power_days):
    """Normalise daily solar/wind/load (MW) to 96-slot profiles in GW."""
    return {d: {k: _profile(v[k]) / 1000.0 for k in ("solar", "wind", "load")} for d, v in power_days.items()}

FORECASTERS = {"naive": naive, "blend": blend, "ridge": ridge, "ridge_fund": ridge}
