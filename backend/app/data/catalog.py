"""Every time series the terminal uses, where it comes from, and its units as published.

Values are stored exactly as the source publishes them (FRED's WALCL in USD millions,
RRPONTSYD in USD billions, yields in percent); consumers convert. Series IDs are namespaced by
source: ``fred/DGS10``, ``ust/par/10Y``, ``fiscal/debt/total``, ``tic/japan``.
"""

from dataclasses import dataclass
from typing import Literal

Frequency = Literal["D", "W", "M", "Q"]
SourceName = Literal["fred", "treasury", "fiscaldata", "tic", "rbi", "fbil", "fbil_gsec", "nsdl"]


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
        "avg_rate/frn",
        "Treasury Floating Rate Notes (FRN)",
        "Average interest rate, FRNs",
        "%",
        "M",
    ),
    _fiscal(
        "avg_rate/marketable",
        "Total Marketable",
        "Average interest rate, total marketable",
        "%",
        "M",
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


def _rbi(remote: str, title: str, units: str = "%") -> SeriesSpec:
    return SeriesSpec(f"rbi/{remote}", "rbi", remote, title, units, "D")


IN_RBI_SERIES: tuple[SeriesSpec, ...] = (
    _rbi("repo", "RBI policy repo rate"),
    _rbi("sdf", "Standing deposit facility rate (LAF floor)"),
    _rbi("msf", "Marginal standing facility rate (LAF ceiling)"),
    _rbi("bank_rate", "Bank Rate"),
    _rbi("fixed_reverse_repo", "Fixed reverse repo rate"),
    _rbi("crr", "Cash reserve ratio", "% of NDTL"),
    _rbi("slr", "Statutory liquidity ratio", "% of NDTL"),
    _rbi("usdinr", "FBIL INR/USD reference rate, as shown on RBI's homepage", "INR"),
)


def _mmo(remote: str, title: str, units: str, key: str | None = None) -> SeriesSpec:
    return SeriesSpec(f"rbi/mmo/{key or remote}", "rbi", remote, title, units, "D")


_SEGMENTS = (
    ("overnight", "Overnight segment (call + TREPS + market repo + corporate repo)"),
    ("call", "Call money"),
    ("treps", "Triparty repo (TREPS), overnight"),
    ("market_repo", "Market repo, overnight"),
    ("notice", "Notice money (2-14 days)"),
    ("term", "Term money (15 days-1 year)"),
)

IN_MMO_SERIES: tuple[SeriesSpec, ...] = (
    _mmo("call_rate", "Weighted average call rate (WACR)", "%", key="wacr"),
    *(
        spec
        for key, name in _SEGMENTS
        for spec in (
            *(
                ()
                if key == "call"
                else (_mmo(f"{key}_rate", f"{name}: weighted average rate", "%"),)
            ),
            _mmo(f"{key}_volume", f"{name}: volume", "INR cr"),
            _mmo(f"{key}_low", f"{name}: lowest rate", "%"),
            _mmo(f"{key}_high", f"{name}: highest rate", "%"),
        )
    ),
    _mmo("sdf_amount", "SDF deposits outstanding (today's and earlier operations)", "INR cr"),
    _mmo("sdf_rate", "SDF rate in today's operations", "%"),
    _mmo("msf_amount", "MSF borrowing outstanding (today's and earlier operations)", "INR cr"),
    _mmo("msf_rate", "MSF rate in today's operations", "%"),
    _mmo("vrr_amount", "Variable rate repo outstanding (injection)", "INR cr"),
    _mmo("vrrr_amount", "Variable rate reverse repo outstanding (absorption)", "INR cr"),
    _mmo("ltro_amount", "Long-term repo operations outstanding (LTRO, TLTRO, SLTRO)", "INR cr"),
    _mmo("slf_amount", "Standing liquidity facilities availed from RBI", "INR cr"),
    _mmo(
        "net_liquidity",
        "Net liquidity injected (+) / absorbed (-), all operations outstanding",
        "INR cr",
    ),
    _mmo("crr_balance", "Scheduled commercial banks: cash balances with RBI", "INR cr"),
    _mmo("crr_requirement", "Average daily cash reserve requirement for the fortnight", "INR cr"),
    _mmo("gov_surplus_cash", "Government surplus cash balance reckoned for auction", "INR cr"),
    _mmo("durable_liquidity", "Net durable liquidity, surplus (+) / deficit (-)", "INR cr"),
)

FBIL_TBILL_TENORS = ("7D", "14D", *(f"{m}M" for m in range(1, 13)))

IN_FBIL_SERIES: tuple[SeriesSpec, ...] = (
    *(
        SeriesSpec(f"fbil/tbill/{t}", "fbil", f"tbill/{t}", f"FBIL T-bill benchmark, {t}", "%", "D")
        for t in FBIL_TBILL_TENORS
    ),
    SeriesSpec("fbil/mibor/ON", "fbil", "mibor/ON", "FBIL overnight MIBOR", "%", "D"),
    SeriesSpec("fbil/usdinr", "fbil", "usdinr", "FBIL reference rate, INR per USD", "INR", "D"),
)

# FBIL's G-sec base/par yield curve, by tenor in years: semi-annual par yields, except that the
# 3-month point is a simple (money-market) yield. FBIL publishes every quarter year to 40-50 years.
FBIL_GSEC_TENORS: dict[str, float] = {
    "3M": 0.25, "6M": 0.5, "1Y": 1.0, "2Y": 2.0, "3Y": 3.0, "5Y": 5.0,
    "7Y": 7.0, "10Y": 10.0, "14Y": 14.0, "20Y": 20.0, "30Y": 30.0,
}  # fmt: skip

IN_FBIL_GSEC_SERIES: tuple[SeriesSpec, ...] = tuple(
    SeriesSpec(
        f"fbil/gsec/par/{t}", "fbil_gsec", f"par/{t}", f"FBIL G-sec par yield, {t}", "%", "D"
    )
    for t in FBIL_GSEC_TENORS
)

_FPI_CLASSES = (
    ("equity", "equity"),
    ("debt", "debt (general limit + VRR + FAR)"),
    ("debt_general", "debt, general limit"),
    ("debt_vrr", "debt, voluntary retention route"),
    ("debt_far", "debt, fully accessible route"),
    ("hybrid", "hybrid"),
    ("total", "all classes"),
)

IN_NSDL_SERIES: tuple[SeriesSpec, ...] = tuple(
    SeriesSpec(
        f"nsdl/fpi/{key}_{unit}", "nsdl", f"{key}_{unit}", f"FPI net investment, {name}", label, "D"
    )
    for key, name in _FPI_CLASSES
    for unit, label in (("inr", "INR cr"), ("usd", "USD mn"))
)

INDIA_SERIES: tuple[SeriesSpec, ...] = (
    IN_RBI_SERIES + IN_MMO_SERIES + IN_FBIL_SERIES + IN_FBIL_GSEC_SERIES + IN_NSDL_SERIES
)

STATIC_SERIES: tuple[SeriesSpec, ...] = FRED_SERIES + TREASURY_SERIES + FISCAL_SERIES + INDIA_SERIES
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
