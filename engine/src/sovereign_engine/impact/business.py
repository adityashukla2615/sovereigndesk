"""What a rate or rupee shock does to a small business: its loan rate, interest cost, margin and
sales, month by month.

* The loan's benchmark. An external benchmark (EBLR) is an external rate such as RBI's repo
  rate, so it moves with repo; a bank's MCLR follows its marginal cost of funds, so it takes
  part of a repo change and part of the money market's move beyond it, and only gradually.
* The loan's rate takes the benchmark's level at each reset (every R months from the first
  reset after the shock) and keeps its fixed spread over it.
* Imported costs move with the rupee as the stock bought at the old rate runs off over the
  inventory period; a share of the increase is passed on to selling prices.
* Sales volume responds to the repo-linked rate (credit-financed demand) and to prices.

Rates are decimals, amounts rupees a month, the rupee's move in per cent (+ is weaker).
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import least_squares

from sovereign_engine._types import ArrayLike, FloatArray, as_float_array

Benchmark = Literal["EBLR", "MCLR"]
DAYS_PER_MONTH = 30.0


@dataclass(frozen=True, slots=True)
class LoanTerms:
    amount: float
    """Outstanding (a working-capital limit, drawn in full)."""
    benchmark: Benchmark
    spread: float
    """Over the benchmark (decimal)."""
    reset_months: int
    first_reset_month: int
    """Months from the shock to the loan's next reset."""
    tenor_months: int

    def __post_init__(self) -> None:
        if self.amount < 0 or self.reset_months < 1 or self.first_reset_month < 0:
            raise ValueError("need amount ≥ 0, reset_months ≥ 1 and first_reset_month ≥ 0")


@dataclass(frozen=True, slots=True)
class PassThrough:
    """How lending benchmarks follow the market: every coefficient is an assumption or an
    estimate from RBI's reports, listed in ASSUMPTIONS.md."""

    eblr_per_repo: float = 1.0
    eblr_lag_months: int = 0
    mclr_per_repo: float = 0.61
    mclr_per_money: float = 0.3
    """MCLR's share of the money market's move beyond what repo explains (liquidity)."""
    mclr_months: float = 6.0
    """Time constant of MCLR's adjustment."""
    mclr_lag_months: int = 1


@dataclass(frozen=True, slots=True)
class MarketMove:
    """The shock as the business meets it: changes since before the shock."""

    repo: float
    money: float
    """The 3-month T-bill's change, a proxy for banks' marginal cost of funds."""
    money_beta: float
    """How much of a repo change the 3-month bill takes, to separate out liquidity."""
    inr_pct: float


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    name: str
    monthly_sales: float
    cost_share: float
    """Costs other than interest, as a share of sales."""
    import_share: float
    """Share of those costs paid in dollars."""
    fx_to_price: float
    """Share of an imported-cost increase passed on to selling prices."""
    inventory_days: float
    rate_semi_elasticity: float
    """% change in sales volume per percentage point of the repo-linked rate (negative)."""
    price_elasticity: float
    """% change in sales volume per % change in price (negative)."""
    loan: LoanTerms

    def __post_init__(self) -> None:
        for name in ("cost_share", "import_share", "fx_to_price"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} is a share between 0 and 1")
        if self.monthly_sales <= 0 or self.inventory_days < 0:
            raise ValueError("need positive sales and non-negative inventory days")


def benchmark_path(
    benchmark: Benchmark, move: MarketMove, passthrough: PassThrough, months: int
) -> FloatArray:
    """The benchmark's change at the end of each month 1 … H.

    Equation:
        EBLR:  ΔBₜ = a·Δrepo                                  for t ≥ lag
        MCLR:  ΔBₜ = (b·Δrepo + m·(Δmoney − β·Δrepo))·(1 − e^(−(t − lag)/τ))   for t ≥ lag
    """
    t = np.arange(1, months + 1, dtype=np.float64)
    p = passthrough
    if benchmark == "EBLR":
        return np.where(t >= p.eblr_lag_months, p.eblr_per_repo * move.repo, 0.0)
    liquidity = move.money - move.money_beta * move.repo
    target = p.mclr_per_repo * move.repo + p.mclr_per_money * liquidity
    phase = np.clip(t - p.mclr_lag_months, 0.0, None)
    return np.asarray(target * (1 - np.exp(-phase / p.mclr_months)), dtype=np.float64)


def loan_rate_path(loan: LoanTerms, benchmark: FloatArray) -> FloatArray:
    """The loan rate's change each month: the benchmark's level at the latest reset.

    Equation:
        ΔLₜ = ΔB_{s(t)},  s(t) = the latest reset month ≤ t (resets at r₀, r₀ + R, …); 0 before r₀
    """
    out = np.zeros_like(benchmark)
    for i in range(benchmark.size):
        month = i + 1
        if month >= loan.first_reset_month:
            last = (
                loan.first_reset_month
                + ((month - loan.first_reset_month) // loan.reset_months) * loan.reset_months
            )
            out[i] = benchmark[max(last, 1) - 1]
    return out


@dataclass(frozen=True, slots=True)
class BusinessImpact:
    profile: BusinessProfile
    base_rate: float
    """The loan rate before the shock."""
    base_interest: float
    base_margin: float
    benchmark: FloatArray
    loan_rate: FloatArray
    """Change in the loan rate."""
    interest: FloatArray
    """Change in monthly interest."""
    import_cost: FloatArray
    """Change in monthly imported costs at the old volume."""
    price_pct: FloatArray
    volume_pct: FloatArray
    sales: FloatArray
    """Change in monthly sales."""
    margin: FloatArray
    """Change in the monthly margin (sales − costs − interest)."""


def business_impact(
    profile: BusinessProfile,
    move: MarketMove,
    passthrough: PassThrough,
    *,
    base_benchmark: float,
    months: int = 12,
) -> BusinessImpact:
    """A business's loan rate, interest, costs, prices, sales and margin after a shock.

    Equation:
        M = S·c·m;  ΔMₜ = M·(ΔX/100)·min(1, 30t/inventory days);  Δpₜ = φ·ΔMₜ/S
        Δvₜ = ε_r·ΔEBLRₜ·100 + ε_p·Δpₜ·100   (per cent);   Sₜ = S·(1 + vₜ)(1 + pₜ)
        Costsₜ = (S·c + ΔMₜ)·(1 + vₜ);   Interestₜ = A·(r₀ + ΔLₜ)/12
        Marginₜ = Sₜ − Costsₜ − Interestₜ
    """
    if months < 1:
        raise ValueError("months must be at least 1")
    p, loan = profile, profile.loan
    benchmark = benchmark_path(loan.benchmark, move, passthrough, months)
    loan_rate = loan_rate_path(loan, benchmark)
    demand_rate = benchmark_path("EBLR", move, passthrough, months)
    base_rate = base_benchmark + loan.spread
    base_interest = loan.amount * base_rate / 12
    costs = p.monthly_sales * p.cost_share
    imported = costs * p.import_share
    t = np.arange(1, months + 1, dtype=np.float64)
    run_off = (
        np.ones(months)
        if p.inventory_days <= 0
        else np.minimum(1.0, t * DAYS_PER_MONTH / p.inventory_days)
    )
    import_cost = imported * move.inr_pct / 100 * run_off
    price = p.fx_to_price * import_cost / p.monthly_sales
    volume = (p.rate_semi_elasticity * demand_rate * 100 + p.price_elasticity * price * 100) / 100
    sales = p.monthly_sales * (1 + volume) * (1 + price)
    shocked_costs = (costs + import_cost) * (1 + volume)
    interest = loan.amount * (base_rate + loan_rate) / 12
    base_margin = p.monthly_sales - costs - base_interest
    margin = sales - shocked_costs - interest
    return BusinessImpact(
        profile=profile,
        base_rate=base_rate,
        base_interest=base_interest,
        base_margin=base_margin,
        benchmark=benchmark,
        loan_rate=loan_rate,
        interest=interest - base_interest,
        import_cost=import_cost,
        price_pct=price * 100,
        volume_pct=volume * 100,
        sales=sales - p.monthly_sales,
        margin=margin - base_margin,
    )


@dataclass(frozen=True, slots=True)
class BenchmarkFit:
    """A benchmark's response to repo changes, fitted on its monthly history."""

    level: float
    """The benchmark's level net of every repo change in the sample (decimal)."""
    share: float
    """Long-run share of a repo change the benchmark takes."""
    months: float
    """Time constant of the adjustment."""
    lag_months: float
    rmse: float
    n: int


def fit_benchmark(
    observed_months: ArrayLike,
    values: ArrayLike,
    change_months: ArrayLike,
    changes: ArrayLike,
    *,
    lag_months: float = 0.0,
) -> BenchmarkFit:
    """Fit a benchmark's level, long-run share and adjustment speed to its history, given every
    repo change before or during it (times in months on one scale, rates decimal).

    Equation:
        Bₜ = c + b·Σⱼ Δrⱼ·(1 − e^(−max(t − tⱼ − L, 0)/τ)),   (c, b, τ) by least squares
    """
    t = as_float_array(observed_months)
    y = as_float_array(values)
    tj = as_float_array(change_months)
    dr = as_float_array(changes)
    if t.size != y.size or tj.size != dr.size or t.size < 4:
        raise ValueError("need at least four observations and one time per change")
    elapsed = np.clip(t[:, None] - tj[None, :] - lag_months, 0.0, None)

    def residuals(x: FloatArray) -> FloatArray:
        c, b, tau = x
        path = (dr[None, :] * (1 - np.exp(-elapsed / tau))).sum(axis=1)
        return np.asarray(c + b * path - y, dtype=np.float64)

    start = np.array([float(y.mean()), 0.6, 6.0])
    fit = least_squares(residuals, start, bounds=([-1.0, 0.0, 0.25], [1.0, 2.0, 60.0]))
    c, b, tau = (float(v) for v in fit.x)
    rmse = float(np.sqrt(np.mean(fit.fun**2)))
    return BenchmarkFit(c, b, tau, lag_months, rmse, int(t.size))
