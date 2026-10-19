"""The Fed's balance sheet, quantitative tightening (QT) and its term-premium effect.

Amounts are USD billions. The balance sheet always balances: QT shrinks securities, and the
public pays for the extra Treasury and MBS supply it absorbs out of deposits, which drains the
ON RRP facility first and bank reserves after (as in the 2022–24 runoff, when money funds moved
from ON RRP into bills).
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class FedBalanceSheet:
    treasuries: float
    mbs: float
    other_assets: float
    reserves: float
    on_rrp: float
    tga: float
    currency: float
    other_liabilities: float
    """Capital and everything else on the liability side; makes the identity hold exactly."""

    @classmethod
    def from_h41(
        cls,
        *,
        total_assets: float,
        treasuries: float,
        mbs: float,
        reserves: float,
        on_rrp: float,
        tga: float,
        currency: float,
    ) -> "FedBalanceSheet":
        """Build from H.4.1 aggregates, assigning the residuals on each side.

        Equation:
            other assets = A − T − MBS
            other liabilities = A − (R + RRP + TGA + C)
        """
        return cls(
            treasuries=treasuries,
            mbs=mbs,
            other_assets=total_assets - treasuries - mbs,
            reserves=reserves,
            on_rrp=on_rrp,
            tga=tga,
            currency=currency,
            other_liabilities=total_assets - (reserves + on_rrp + tga + currency),
        )

    @property
    def total_assets(self) -> float:
        return self.treasuries + self.mbs + self.other_assets

    @property
    def total_liabilities(self) -> float:
        return self.reserves + self.on_rrp + self.tga + self.currency + self.other_liabilities

    def identity_gap(self) -> float:
        """Assets minus liabilities and capital; zero whenever the sheet is consistent.

        Equation:
            gap = (T + MBS + other) − (R + RRP + TGA + C + other)
        """
        return self.total_assets - self.total_liabilities

    def run_off(
        self, treasuries: float, mbs: float, *, rrp_floor: float = 0.0
    ) -> "FedBalanceSheet":
        """Let securities roll off; the drain falls on ON RRP down to its floor, then on reserves.

        Equation:
            D = ΔT + ΔMBS
            ΔRRP = −min(D, RRP − floor),   ΔR = −(D + ΔRRP)
        """
        if treasuries < 0 or mbs < 0:
            raise ValueError("runoff amounts must be non-negative")
        drain = treasuries + mbs
        from_rrp = min(drain, max(self.on_rrp - rrp_floor, 0.0))
        return replace(
            self,
            treasuries=self.treasuries - treasuries,
            mbs=self.mbs - mbs,
            on_rrp=self.on_rrp - from_rrp,
            reserves=self.reserves - (drain - from_rrp),
        )


AVERAGE_MONTH_DAYS = 365.25 / 12


@dataclass(frozen=True, slots=True)
class QTPlan:
    """Monthly runoff caps (USD bn per month)."""

    treasury_cap: float
    mbs_cap: float

    @classmethod
    def from_total(cls, total: float, treasury_share: float = 60 / 95) -> "QTPlan":
        """Split a total cap as the FOMC's 4 May 2022 plan did: $60bn Treasuries, $35bn MBS.

        Equation:
            cap_T = s·total,   cap_MBS = (1 − s)·total,   s = 60/95 by default
        """
        if total < 0 or not 0 <= treasury_share <= 1:
            raise ValueError("need total ≥ 0 and a share in [0, 1]")
        return cls(treasury_cap=total * treasury_share, mbs_cap=total * (1 - treasury_share))

    def runoff(self, days: float) -> tuple[float, float]:
        """Treasury and MBS runoff over ``days``, spread evenly through the month.

        Equation:
            ΔT = cap_T · days / (365.25/12),   ΔMBS = cap_MBS · days / (365.25/12)
        """
        fraction = days / AVERAGE_MONTH_DAYS
        return self.treasury_cap * fraction, self.mbs_cap * fraction


def ten_year_equivalents(amount: float, duration: float, ten_year_duration: float) -> float:
    """Par amount of on-the-run 10-year notes with the same par × duration (FEDS Notes 2022, fn. 4).

    Equation:
        10ye = amount · D / D₁₀
    """
    if ten_year_duration <= 0:
        raise ValueError("the 10-year duration must be positive")
    return amount * duration / ten_year_duration


TERM_PREMIUM_BP_PER_PCT_GDP = 10.0
"""Crawley, Gagnon, Hebden and Trevino (2022, FEDS Notes, 3 June): a permanent reduction in the
Fed's 10-year-equivalent holdings of 1% of nominal GDP raises the 10-year term premium by about
10 bp (FRB/US with Li and Wei, 2013, term-premium effects)."""


def term_premium_effect(
    ten_year_equivalents_absorbed: float,
    nominal_gdp: float,
    bp_per_pct_gdp: float = TERM_PREMIUM_BP_PER_PCT_GDP,
) -> float:
    """Change in the 10-year term premium (decimal) when the public absorbs extra duration.

    Equation:
        Δtp = b · 100 · 10ye / GDP   basis points,   b ≈ 10 bp per 1% of GDP
    """
    if nominal_gdp <= 0:
        raise ValueError("nominal GDP must be positive")
    return bp_per_pct_gdp * 100 * ten_year_equivalents_absorbed / nominal_gdp * 1e-4
