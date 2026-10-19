"""Discount bills: US Treasury bills and Indian T-bills.

US formulas follow 31 CFR Part 356 Appendix B §VI; Indian T-bill yields follow RBI's
actual/365 convention. Prices are per 100 face; rates and yields are decimals; ``days`` is the
number of days from settlement (or issue) to maturity.
"""

import math
from datetime import date

from sovereign_engine.bonds.schedule import add_months


def _check_days(days: int) -> None:
    if days <= 0:
        raise ValueError("days to maturity must be positive")


def us_bill_price(discount_rate: float, days: int) -> float:
    """Price of a US Treasury bill from its bank-discount rate (App. B §VI.A).

    Equation:
        P = 100 · (1 − d·r / 360)
    """
    _check_days(days)
    return 100 * (1 - discount_rate * days / 360)


def us_bill_discount_rate(price: float, days: int) -> float:
    """Bank-discount rate of a US Treasury bill from its price.

    Equation:
        d = (100 − P)/100 · 360/r
    """
    _check_days(days)
    return (100 - price) / 100 * 360 / days


def us_bill_year_basis(issue_date: date) -> int:
    """Days in the year following the issue date: 366 if that year contains 29 February.

    Equation:
        y = (issue date + 1 year) − issue date   ∈ {365, 366}
    """
    return (add_months(issue_date, 12) - issue_date).days


def us_bill_investment_rate(price: float, days: int, year_basis: int = 365) -> float:
    """Coupon-equivalent (investment) rate of a US Treasury bill (App. B §VI.D).

    Bills with more than half a year to run compound once, so the rate solves a quadratic.

    Equation:
        r ≤ y/2:   i = (100 − P)/P · y/r
        r > y/2:   P·[1 + (r − y/2)·(i/y)]·(1 + i/2) = 100  ⇒  i = (−b + √(b² − 4ac)) / (2a)
                   a = r/(2y) − 0.25,   b = r/y,   c = (P − 100)/P
    """
    _check_days(days)
    if price <= 0:
        raise ValueError("price must be positive")
    if days <= year_basis / 2:
        return (100 - price) / price * year_basis / days
    a = days / (2 * year_basis) - 0.25
    b = days / year_basis
    c = (price - 100) / price
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def money_market_yield(price: float, days: int, basis: int = 360) -> float:
    """Simple-interest yield on the price paid (USD money-market / CD-equivalent basis by default).

    Equation:
        i = (100 − P)/P · B/r
    """
    _check_days(days)
    return (100 - price) / price * basis / days


def india_tbill_yield(price: float, days: int) -> float:
    """Implicit yield of an Indian T-bill (RBI convention: actual/365, simple interest).

    Equation:
        y = (100 − P)/P · 365/D
    """
    return money_market_yield(price, days, basis=365)


def india_tbill_price(yield_: float, days: int) -> float:
    """Price of an Indian T-bill from its actual/365 yield.

    Equation:
        P = 100 / (1 + y·D/365)
    """
    _check_days(days)
    return 100 / (1 + yield_ * days / 365)
