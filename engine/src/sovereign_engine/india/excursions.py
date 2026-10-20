"""WACR's day-to-day deviation from the macro map, and how often it leaves RBI's corridor.

The map gives WACR's level for a liquidity position; real WACR wanders around it, persistently
and with fat, skewed tails: on some days it prints well below the SDF rate (surplus days, thin
sessions) or above the MSF rate (deficits, year-ends). The deviation here is an AR(1) whose
innovations are resampled from the fit's own residuals, with the downward and upward ones
scaled separately so that, run over the historical liquidity path, the share of days below
the SDF and above the MSF matches what RBI's releases show.
"""

from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


@dataclass(frozen=True, slots=True)
class DeviationModel:
    rho: float
    innovations: FloatArray
    """Empirical innovations uᵢ = eᵢ − ρ·eᵢ₋₁ of the map's residuals (decimal)."""
    scale_down: float = 1.0
    scale_up: float = 1.0

    def step(self, previous: float, rng: np.random.Generator) -> float:
        """The next day's deviation.

        Equation:
            eₜ = ρ·eₜ₋₁ + k(u)·u,   u drawn from the empirical innovations,
            k(u) = k_down if u < 0 else k_up
        """
        u = float(rng.choice(self.innovations))
        return self.rho * previous + (self.scale_down if u < 0 else self.scale_up) * u

    def paths(self, days: int, count: int, rng: np.random.Generator) -> FloatArray:
        """``count`` simulated deviation paths of ``days`` days, starting at zero.

        Equation:
            e₀ = 0,  eₜ = ρ·eₜ₋₁ + k(uₜ)·uₜ  for each path independently
        """
        draws = rng.choice(self.innovations, size=(count, days))
        draws = np.where(draws < 0, self.scale_down * draws, self.scale_up * draws)
        out = np.zeros((count, days))
        for t in range(1, days):
            out[:, t] = self.rho * out[:, t - 1] + draws[:, t]
        return out


def excursion_shares(
    model: DeviationModel,
    centre: ArrayLike,
    lower: ArrayLike,
    upper: ArrayLike,
    rng: np.random.Generator,
    count: int = 200,
) -> tuple[float, float]:
    """Share of simulated days below the floor and above the ceiling along a given path.

    Equation:
            below = mean over paths and days of 1[cₜ + eₜ < Lₜ],  above = mean 1[cₜ + eₜ > Uₜ]
    """
    c, lo, hi = as_float_array(centre), as_float_array(lower), as_float_array(upper)
    rates = c + model.paths(c.size, count, rng)
    return float(np.mean(rates < lo)), float(np.mean(rates > hi))


def calibrate_deviations(
    residuals: ArrayLike,
    centre: ArrayLike,
    lower: ArrayLike,
    upper: ArrayLike,
    target_below: float,
    target_above: float,
    seed: int = 7,
    rounds: int = 3,
    steps: int = 12,
) -> DeviationModel:
    """Fit the AR(1) to the residuals, then scale its tails to the observed excursion shares.

    Equation:
        ρ = corr(eₜ, eₜ₋₁),  uₜ = eₜ − ρ·eₜ₋₁
        choose k_down, k_up ∈ [0.25, 4] by bisection, each in turn, so that along the history
        below(k) = target_below and above(k) = target_above (common random numbers)
    """
    e = as_float_array(residuals)
    if e.ndim != 1 or e.size < 30:
        raise ValueError("need at least thirty residuals")
    if not (0 <= target_below < 1 and 0 <= target_above < 1):
        raise ValueError("targets are shares of days")
    rho = float(np.corrcoef(e[1:], e[:-1])[0, 1])
    model = DeviationModel(rho, e[1:] - rho * e[:-1])

    def shares(m: DeviationModel) -> tuple[float, float]:
        return excursion_shares(m, centre, lower, upper, np.random.default_rng(seed))

    for _ in range(rounds):
        for side in ("down", "up"):
            lo, hi = 0.25, 4.0
            for _ in range(steps):
                k = (lo + hi) / 2
                trial = (
                    DeviationModel(rho, model.innovations, k, model.scale_up)
                    if side == "down"
                    else DeviationModel(rho, model.innovations, model.scale_down, k)
                )
                below, above = shares(trial)
                got, want = (below, target_below) if side == "down" else (above, target_above)
                lo, hi = (k, hi) if got < want else (lo, k)
            k = (lo + hi) / 2
            model = (
                DeviationModel(rho, model.innovations, k, model.scale_up)
                if side == "down"
                else DeviationModel(rho, model.innovations, model.scale_down, k)
            )
    return model
