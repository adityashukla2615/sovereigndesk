"""The Taylor-rule baseline: the rate the rule prescribes, and the decision it implies.

The rule (Taylor 1993) sets the policy rate from the neutral real rate, inflation, and the gaps
of inflation from target and output from potential. Central banks move towards it in steps
rather than at once, so the baseline closes a share of the gap each meeting, in 25 bp steps,
and calls that the decision.
"""

from dataclasses import dataclass

import numpy as np

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array
from sovereign_engine.predict.classes import STEP, decision_class


@dataclass(frozen=True, slots=True)
class TaylorRule:
    r_star: float
    """Neutral real policy rate (decimal)."""
    pi_star: float = 0.04
    """Inflation target (decimal)."""
    a_pi: float = 0.5
    a_y: float = 0.5

    def prescribed(self, inflation: ArrayLike, output_gap: ArrayLike) -> FloatArray:
        """The policy rate the rule prescribes (decimals; the gap as a fraction of potential).

        Equation:
            i* = r* + π + a_π·(π − π*) + a_y·ỹ
        """
        pi, gap = as_float_array(inflation), as_float_array(output_gap)
        return np.asarray(
            self.r_star + pi + self.a_pi * (pi - self.pi_star) + self.a_y * gap, dtype=np.float64
        )


@dataclass(frozen=True, slots=True)
class TaylorBaseline:
    rule: TaylorRule
    adjustment: float = 0.25
    """Share of the gap between the prescribed and current rate closed at a meeting."""
    step: float = STEP
    cap: float = 2 * STEP
    """The largest move the baseline makes at one meeting."""

    def change(self, repo: ArrayLike, inflation: ArrayLike, output_gap: ArrayLike) -> FloatArray:
        """The move the baseline expects, in whole policy steps.

        Equation:
            Δ = clip(s·round(λ·(i* − r)/s), −c, c)     (λ adjustment, s step, c cap; halves
            round away from zero)
        """
        gap = self.rule.prescribed(inflation, output_gap) - as_float_array(repo)
        scaled = self.adjustment * gap / self.step
        steps = np.sign(scaled) * np.floor(np.abs(scaled) + 0.5 + 1e-9)
        return np.asarray(np.clip(steps * self.step, -self.cap, self.cap), dtype=np.float64)

    def predict_proba(
        self, repo: ArrayLike, inflation: ArrayLike, output_gap: ArrayLike
    ) -> FloatArray:
        """All probability on the baseline's class: the rule is deterministic.

        Equation:
            pₖ = 1 if k = class(Δ) else 0
        """
        classes = decision_class(self.change(repo, inflation, output_gap), step=self.step)
        out = np.zeros((classes.size, 5))
        out[np.arange(classes.size), classes] = 1.0
        return out
