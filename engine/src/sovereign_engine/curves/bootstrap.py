"""Bootstrap a discount curve from bond-equivalent par yields (the US Treasury par curve).

Par yields are interpolated linearly in tenor onto the coupon grid, then discount factors are
solved one period at a time so that every grid bond prices at par. Tenors up to one coupon
period are money-market points with simple interest, which agrees with the coupon formula at
exactly one period.
"""

import numpy as np

from sovereign_engine._types import ArrayLike, as_float_array
from sovereign_engine.curves.piecewise import LogLinearDiscountCurve


def bootstrap_par_yields(
    tenors: ArrayLike, par_yields: ArrayLike, freq: int = 2
) -> LogLinearDiscountCurve:
    """Discount factors that reprice par bonds at every coupon date up to the last tenor.

    Equation:
        T ≤ 1/f (money market):   DF(T) = 1 / (1 + y_T · T)
        coupon grid tₙ = n/f, n ≥ 1, yₙ = par yield interpolated linearly in tenor:
                                  DF(tₙ) = (1 − (yₙ/f) · Σ_{k<n} DF(t_k)) / (1 + yₙ/f)
    """
    t, y = as_float_array(tenors), as_float_array(par_yields)
    if t.ndim != 1 or t.shape != y.shape or t.size < 2:
        raise ValueError("need at least two tenors with matching par yields")
    if t[0] <= 0 or np.any(np.diff(t) <= 0):
        raise ValueError("tenors must be positive and strictly increasing")
    last = round(t[-1] * freq)
    if last < 1 or not np.isclose(last / freq, t[-1]):
        raise ValueError("the longest tenor must be a whole number of coupon periods")

    grid = np.arange(1, last + 1, dtype=np.float64) / freq
    grid_yields = np.interp(grid, t, y)
    grid_dfs = np.empty_like(grid)
    annuity = 0.0
    for n, yn in enumerate(grid_yields):
        coupon = yn / freq
        grid_dfs[n] = (1 - coupon * annuity) / (1 + coupon)
        annuity += grid_dfs[n]
    if np.any(grid_dfs <= 0):
        raise ValueError("par yields imply a non-positive discount factor")

    short = t < grid[0] - 1e-12
    times = np.concatenate((t[short], grid))
    discounts = np.concatenate((1 / (1 + y[short] * t[short]), grid_dfs))
    return LogLinearDiscountCurve(times=times, discounts=discounts)
