"""Every time series the terminal uses, where it comes from, and its units as published.

Values are stored exactly as the source publishes them (FRED's WALCL in USD millions,
RRPONTSYD in USD billions, yields in percent); consumers convert. Series IDs are namespaced by
source: ``fred/DGS10``, ``ust/par/10Y``, ``fiscal/debt/total``, ``tic/japan``.
"""

from dataclasses import dataclass
from typing import Literal

Frequency = Literal["D", "W", "M", "Q"]
SourceName = Literal["fred", "treasury", "fiscaldata", "tic"]


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    series_id: str
    source: SourceName
    remote: str
    """Source-specific key: FRED series ID, Treasury CSV column, FiscalData field, TIC row label."""
    title: str
    units: str
    frequency: Frequency


def _fred(remote: str, title: str, units: str, frequency: Frequency) -> SeriesSpec:
    return SeriesSpec(f"fred/{remote}", "fred", remote, title, units, frequency)


# IDs verified against the FRED API (fred/series) on 2026-10-19.
FRED_SERIES: tuple[SeriesSpec, ...] = (
    _fred("DGS1MO", "Treasury 1-month constant maturity yield", "%", "D"),
    _fred("DGS3MO", "Treasury 3-month constant maturity yield", "%", "D"),
    _fred("DGS6MO", "Treasury 6-month constant maturity yield", "%", "D"),
    _fred("DGS1", "Treasury 1-year constant maturity yield", "%", "D"),
    _fred("DGS2", "Treasury 2-year constant maturity yield", "%", "D"),
    _fred("DGS3", "Treasury 3-year constant maturity yield", "%", "D"),
    _fred("DGS5", "Treasury 5-year constant maturity yield", "%", "D"),
    _fred("DGS7", "Treasury 7-year constant maturity yield", "%", "D"),
    _fred("DGS10", "Treasury 10-year constant maturity yield", "%", "D"),
    _fred("DGS20", "Treasury 20-year constant maturity yield", "%", "D"),
    _fred("DGS30", "Treasury 30-year constant maturity yield", "%", "D"),
    _fred("EFFR", "Effective federal funds rate", "%", "D"),
    _fred("DFF", "Federal funds effective rate (long history)", "%", "D"),
    _fred("SOFR", "Secured overnight financing rate", "%", "D"),
    _fred("DFEDTARU", "Fed funds target range, upper limit", "%", "D"),
    _fred("DFEDTARL", "Fed funds target range, lower limit", "%", "D"),
    _fred("IORB", "Interest rate on reserve balances", "%", "D"),
    _fred("IOER", "Interest rate on excess reserves (to Jul 2021)", "%", "D"),
    _fred("RRPONTSYAWARD", "Overnight reverse repo award rate", "%", "D"),
    _fred("RRPONTSYD", "Overnight reverse repo, Treasury securities", "USD bn", "D"),
    _fred("WALCL", "Fed total assets", "USD mn", "W"),
    _fred("TREAST", "Fed Treasury securities held outright", "USD mn", "W"),
    _fred("WSHOMCB", "Fed MBS held outright", "USD mn", "W"),
    _fred("WRESBAL", "Reserve balances with Federal Reserve Banks", "USD mn", "W"),
    _fred("WTREGEN", "Treasury General Account", "USD mn", "W"),
    _fred("WCURCIR", "Currency in circulation (Fed liability)", "USD mn", "W"),
    _fred("TLAACBW027SBOG", "Total assets, all commercial banks (SA)", "USD bn", "W"),
    _fred("CPIAUCSL", "CPI, all items (SA)", "index 1982-84=100", "M"),
    _fred("CPILFESL", "Core CPI, less food and energy (SA)", "index 1982-84=100", "M"),
    _fred("PCEPILFE", "Core PCE price index", "index 2017=100", "M"),
    _fred("GDP", "Nominal GDP (SAAR)", "USD bn", "Q"),
    _fred("FDHBFIN", "Federal debt held by foreign and international investors", "USD bn", "Q"),
    _fred("GFDEBTN", "Federal debt, total public debt", "USD mn", "Q"),
    _fred("A091RC1Q027SBEA", "Federal interest payments (SAAR, BEA)", "USD bn", "Q"),
    _fred("MTSR133FMS", "Federal receipts (Monthly Treasury Statement)", "USD mn", "M"),
    _fred("MTSO133FMS", "Federal outlays (Monthly Treasury Statement)", "USD mn", "M"),
    _fred("THREEFYTP10", "10-year term premium (Kim-Wright)", "%", "D"),
    _fred("VIXCLS", "CBOE VIX", "index", "D"),
    _fred("DTWEXBGS", "Nominal broad US dollar index", "index Jan 2006=100", "D"),
    _fred("DEXINUS", "INR per USD, spot", "INR", "D"),
    _fred("INDIRLTLT01STM", "India 10-year government bond yield (OECD)", "%", "M"),
)

# Column headers of Treasury's daily par yield curve CSV → tenor labels.
TREASURY_TENORS: dict[str, str] = {
    "1 Mo": "1M",
    "1.5 Month": "6W",
    "2 Mo": "2M",
    "3 Mo": "3M",
    "4 Mo": "4M",
    "6 Mo": "6M",
    "1 Yr": "1Y",
    "2 Yr": "2Y",
    "3 Yr": "3Y",
    "5 Yr": "5Y",
    "7 Yr": "7Y",
    "10 Yr": "10Y",
    "20 Yr": "20Y",
    "30 Yr": "30Y",
}

TREASURY_SERIES: tuple[SeriesSpec, ...] = tuple(
    SeriesSpec(f"ust/par/{tenor}", "treasury", column, f"Treasury par yield, {tenor}", "%", "D")
    for column, tenor in TREASURY_TENORS.items()
)


def _fiscal(key: str, remote: str, title: str, units: str, frequency: Frequency) -> SeriesSpec:
    return SeriesSpec(f"fiscal/{key}", "fiscaldata", remote, title, units, frequency)


FISCAL_SERIES: tuple[SeriesSpec, ...] = (
    _fiscal("debt/total", "tot_pub_debt_out_amt", "Total public debt outstanding", "USD", "D"),
    _fiscal("debt/public", "debt_held_public_amt", "Debt held by the public", "USD", "D"),
    _fiscal("debt/intragov", "intragov_hold_amt", "Intragovernmental holdings", "USD", "D"),
    _fiscal("avg_rate/bills", "Treasury Bills", "Average interest rate, bills", "%", "M"),
    _fiscal("avg_rate/notes", "Treasury Notes", "Average interest rate, notes", "%", "M"),
    _fiscal("avg_rate/bonds", "Treasury Bonds", "Average interest rate, bonds", "%", "M"),
    _fiscal(
        "avg_rate/tips",
        "Treasury Inflation-Protected Securities (TIPS)",
        "Average interest rate, TIPS",
        "%",
        "M",
    ),
    _fiscal(
        "avg_rate/frn", "Treasury Floating Rate Notes (FRN)", "Average interest rate, FRNs", "%", "M"
    ),
    _fiscal(
        "avg_rate/marketable", "Total Marketable", "Average interest rate, total marketable", "%", "M"
    ),
    _fiscal(
        "interest/public_issues",
        "INTEREST EXPENSE ON PUBLIC ISSUES",
        "Interest expense on public issues (month)",
        "USD",
        "M",
    ),
    _fiscal("interest/total", "*", "Interest expense, all categories (month)", "USD", "M"),
)

STATIC_SERIES: tuple[SeriesSpec, ...] = FRED_SERIES + TREASURY_SERIES + FISCAL_SERIES
BY_ID: dict[str, SeriesSpec] = {spec.series_id: spec for spec in STATIC_SERIES}


def tic_series_id(label: str) -> str:
    """Slug a TIC row label: ``"China, Mainland"`` → ``tic/china_mainland``.

    ``"Of Which: Foreign Official"`` becomes ``tic/foreign_official``.
    """
    text = label.strip().lower().removeprefix("of which:").strip()
    slug = "".join(ch if ch.isalnum() else "_" for ch in text.replace("&", "and"))
    return "tic/" + "_".join(part for part in slug.split("_") if part)


def tic_spec(label: str) -> SeriesSpec:
    title = f"Foreign holdings of Treasuries: {label}"
    return SeriesSpec(tic_series_id(label), "tic", label, title, "USD bn", "M")
