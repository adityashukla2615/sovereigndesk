"""How well a model's path tracks what happened in a replay: the scores, and a summary of what
the model got right and wrong in plain words.

Both paths are levels on the same dates (a yield, a rate, a cumulative flow). Steps where
either is missing are left out.
"""

from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, as_float_array


@dataclass(frozen=True, slots=True)
class ReplayScore:
    n: int
    rmse: float
    mae: float
    direction: float | None
    """Share of steps the model moved the same way as what happened, among the steps where
    something happened; None when nothing moved."""
    peak_model: float
    """The model's largest move from the start (signed)."""
    peak_actual: float
    peak_lag: int
    """Steps from the actual peak to the model's (positive: the model peaked later)."""
    end_model: float
    """The model's move from the start to the end."""
    end_actual: float


def _peak(path: np.ndarray) -> tuple[float, int]:
    moves = path - path[0]
    k = int(np.argmax(np.abs(moves)))
    return float(moves[k]), k


def score(model: ArrayLike, actual: ArrayLike, *, horizon: int = 1) -> ReplayScore:
    """Score a model path against the actual one; direction is judged on the moves over each
    ``horizon`` steps (5 for a week of daily data), so day-to-day noise does not decide it.

    Equation:
        RMSE = √(mean (mₜ − aₜ)²),   MAE = mean |mₜ − aₜ|,
        Δxₖ = x_{(k+1)h} − x_{kh};   direction = #{k: sign Δmₖ = sign Δaₖ, Δaₖ ≠ 0} / #{k: Δaₖ ≠ 0},
        peak = x_k − x₀ with k = argmaxₜ |xₜ − x₀|,   lag = k_model − k_actual,
        end = x_T − x₀
    """
    m, a = as_float_array(model), as_float_array(actual)
    if m.shape != a.shape:
        raise ValueError("the two paths must cover the same dates")
    keep = np.isfinite(m) & np.isfinite(a)
    m, a = m[keep], a[keep]
    if m.size < 2:
        raise ValueError("need at least two dates where both paths are known")
    if horizon < 1:
        raise ValueError("horizon must be at least one step")
    error = m - a
    dm, da = np.diff(m[::horizon]), np.diff(a[::horizon])
    moved = np.abs(da) > 1e-12
    direction = float(np.mean(np.sign(dm[moved]) == np.sign(da[moved]))) if moved.any() else None
    peak_m, k_m = _peak(m)
    peak_a, k_a = _peak(a)
    return ReplayScore(
        n=int(m.size),
        rmse=float(np.sqrt(np.mean(error**2))),
        mae=float(np.mean(np.abs(error))),
        direction=direction,
        peak_model=peak_m,
        peak_actual=peak_a,
        peak_lag=k_m - k_a,
        end_model=float(m[-1] - m[0]),
        end_actual=float(a[-1] - a[0]),
    )


def summarize(
    label: str,
    unit: str,
    s: ReplayScore,
    *,
    digits: int = 1,
    step: str = "day",
    moves: str = "days that moved",
) -> list[str]:
    """What the model got right and wrong, in sentences built from the score.

    Equation:
        none: each sentence compares one field of the score with a threshold (direction ≥ 60%
        is "mostly right"; a peak within 25% of the actual one is "about right")
    """

    def v(x: float) -> str:
        return f"{x:+.{digits}f}{unit}"

    out = []
    if s.direction is not None:
        verdict = (
            "mostly right"
            if s.direction >= 0.6
            else "often wrong"
            if s.direction < 0.45
            else "mixed"
        )
        out.append(
            f"{label}: direction {verdict}, the same way as what happened in {s.direction:.0%} "
            f"of the {moves}"
        )
    if abs(s.peak_actual) > 0:
        ratio = s.peak_model / s.peak_actual
        size = (
            "about right"
            if 0.75 <= ratio <= 1.25
            else "too small"
            if 0 <= ratio < 0.75
            else "too large"
            if ratio > 1.25
            else "the wrong way"
        )
        timing = (
            "on time"
            if s.peak_lag == 0
            else f"{abs(s.peak_lag)} {step}{'s' if abs(s.peak_lag) != 1 else ''} "
            f"{'late' if s.peak_lag > 0 else 'early'}"
        )
        out.append(
            f"{label}: peak move {v(s.peak_model)} against {v(s.peak_actual)}, {size}, {timing}"
        )
    out.append(
        f"{label}: ended {v(s.end_model)} against {v(s.end_actual)}; typical error "
        f"{s.mae:.{digits}f}{unit} (RMSE {s.rmse:.{digits}f}{unit})"
    )
    return out
