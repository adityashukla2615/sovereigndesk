"""Discount curve interpolated log-linearly between knots (piecewise-flat forwards)."""

from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array


@dataclass(frozen=True, slots=True)
class LogLinearDiscountCurve:
    """Knots (tᵢ, DFᵢ); ln DF is linear between knots and through the origin (DF(0) = 1).

    Before the first knot the forward equals the first segment's; beyond the last knot the
    last segment's forward is extended, so forwards are flat at both ends.
    """

    times: FloatArray
    discounts: FloatArray

    def __post_init__(self) -> None:
        times, dfs = as_float_array(self.times), as_float_array(self.discounts)
        if times.ndim != 1 or times.shape != dfs.shape or times.size == 0:
            raise ValueError("times and discounts must be non-empty 1-D arrays of equal length")
        if times[0] <= 0 or np.any(np.diff(times) <= 0):
            raise ValueError("knot times must be positive and strictly increasing")
        if np.any(dfs <= 0):
            raise ValueError("discount factors must be positive")
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "discounts", dfs)

    def _knots(self) -> tuple[FloatArray, FloatArray]:
        return np.concatenate(([0.0], self.times)), np.concatenate(([0.0], np.log(self.discounts)))

    def _segment_forwards(self) -> FloatArray:
        t, log_df = self._knots()
        return -np.diff(log_df) / np.diff(t)

    def discount(self, t: ArrayLike) -> FloatArray:
        """Discount factor by log-linear interpolation.

        Equation:
            ln DF(t) = ln DFᵢ + (t − tᵢ)/(tᵢ₊₁ − tᵢ) · (ln DFᵢ₊₁ − ln DFᵢ)   on [tᵢ, tᵢ₊₁], t₀ = 0
            ln DF(t) = ln DF_n − f_n · (t − t_n)                             for t > t_n
        """
        times = as_float_array(t)
        if np.any(times < 0):
            raise ValueError("times must be non-negative")
        knots_t, knots_log = self._knots()
        log_df = np.interp(times, knots_t, knots_log)
        beyond = times > knots_t[-1]
        log_df = np.where(
            beyond, knots_log[-1] - self._segment_forwards()[-1] * (times - knots_t[-1]), log_df
        )
        return np.exp(log_df)

    def zero_rate(self, t: ArrayLike) -> FloatArray:
        """Continuously compounded zero rate.

        Equation:
            z(t) = −ln DF(t) / t;   z(0) = f(0), the first segment's forward
        """
        times = as_float_array(t)
        safe = np.where(times > 0, times, 1.0)
        return np.where(times > 0, -np.log(self.discount(safe)) / safe, self._segment_forwards()[0])

    def forward_rate(self, t: ArrayLike) -> FloatArray:
        """Instantaneous forward rate, constant on each segment (left-continuous).

        Equation:
            f(t) = (ln DFᵢ − ln DFᵢ₊₁) / (tᵢ₊₁ − tᵢ)   for t ∈ (tᵢ, tᵢ₊₁]
        """
        times = as_float_array(t)
        forwards = self._segment_forwards()
        index = np.searchsorted(self.times, times, side="left")
        return forwards[np.clip(index, 0, forwards.size - 1)]
