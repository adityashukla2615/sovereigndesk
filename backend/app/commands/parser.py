"""Tokens of a function-code command: ``SHOCK JP 200B 10D LONG``, ``HIKE 25BP``, ``SPEED 10X``."""

import re
from dataclasses import dataclass

AVERAGE_MONTH_DAYS = 365.25 / 12


class CommandError(ValueError):
    """A command could not be parsed or carried out; the message is shown to the user."""


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    code: str
    args: tuple[str, ...]
    raw: str


def tokenize(text: str) -> ParsedCommand:
    tokens = text.strip().upper().split()
    if not tokens:
        raise CommandError("Empty command. Type HELP for the list of functions.")
    return ParsedCommand(tokens[0], tuple(tokens[1:]), text.strip())


_BP = re.compile(r"^([+-]?\d+(?:\.\d+)?)(?:BPS?)?$")
_USD = re.compile(r"^\$?(\d+(?:\.\d+)?)(B|BN|T|TN)?$")
_DAYS = re.compile(r"^(\d+(?:\.\d+)?)(D|W|M)$")
_SPEED = re.compile(r"^(\d+(?:\.\d+)?)X?$")
_INR = re.compile(r"^₹?(\d+(?:\.\d+)?)(CR|L|LCR)$")
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%?$")


def parse_bp(token: str) -> float:
    """``25BP`` → 0.0025 (decimal); a bare number is read as basis points."""
    match = _BP.match(token)
    if not match:
        raise CommandError(f"Expected basis points like 25BP, got {token}")
    return float(match[1]) * 1e-4


def parse_usd_bn(token: str) -> float:
    """``200B`` → 200, ``1.5T`` → 1500 (USD billions)."""
    match = _USD.match(token)
    if not match:
        raise CommandError(f"Expected an amount like 200B or 1.5T, got {token}")
    value = float(match[1])
    return value * 1000 if match[2] in ("T", "TN") else value


def parse_days(token: str) -> float:
    """``10D`` → 10, ``2W`` → 14, ``1M`` → 30.4 (calendar days)."""
    match = _DAYS.match(token)
    if not match:
        raise CommandError(f"Expected a pace like 10D, 2W or 1M, got {token}")
    return float(match[1]) * {"D": 1.0, "W": 7.0, "M": AVERAGE_MONTH_DAYS}[match[2]]


def parse_inr_cr(token: str) -> float:
    """``50000CR`` → 50000, ``1.5L`` or ``1.5LCR`` → 150000 (₹ crore)."""
    match = _INR.match(token)
    if not match:
        raise CommandError(f"Expected an amount like 50000CR or 1.5L (lakh crore), got {token}")
    return float(match[1]) * (1.0 if match[2] == "CR" else 100_000.0)


def parse_percent(token: str) -> float:
    """``3.5`` or ``3.5%`` → 0.035."""
    match = _PERCENT.match(token)
    if not match:
        raise CommandError(f"Expected a percentage like 3.5, got {token}")
    return float(match[1]) / 100


def parse_speed(token: str) -> float:
    match = _SPEED.match(token)
    if not match or float(match[1]) <= 0:
        raise CommandError(f"Expected a speed multiple like 10X, got {token}")
    return float(match[1])


def is_days(token: str) -> bool:
    return bool(_DAYS.match(token))


COUNTRY_CODES: dict[str, str] = {
    "JP": "Japan",
    "UK": "United Kingdom",
    "GB": "United Kingdom",
    "CN": "China, Mainland",
    "BE": "Belgium",
    "CA": "Canada",
    "KY": "Cayman Islands",
    "LU": "Luxembourg",
    "FR": "France",
    "IE": "Ireland",
    "TW": "Taiwan",
    "CH": "Switzerland",
    "SG": "Singapore",
    "HK": "Hong Kong",
    "NO": "Norway",
    "IN": "India",
    "BR": "Brazil",
    "SA": "Saudi Arabia",
    "KR": "Korea, South",
    "IL": "Israel",
    "DE": "Germany",
    "BM": "Bermuda",
    "AE": "United Arab Emirates",
    "MX": "Mexico",
    "TH": "Thailand",
    "ES": "Spain",
    "AU": "Australia",
    "PH": "Philippines",
    "SE": "Sweden",
    "NL": "Netherlands",
    "KW": "Kuwait",
    "CO": "Colombia",
    "PL": "Poland",
}


def resolve_country(token: str, holdings: dict[str, float]) -> str:
    """ISO-style code (JP) or a holder's name (JAPAN) → the TIC label it is reported under."""
    label = COUNTRY_CODES.get(token)
    if label is None:
        label = next((name for name in holdings if name.upper().replace(" ", "") == token), None)
    if label is None or label not in holdings:
        codes = sorted(code for code, name in COUNTRY_CODES.items() if name in holdings)
        raise CommandError(f"Unknown holder {token}. Try one of: {', '.join(codes)}")
    return label
