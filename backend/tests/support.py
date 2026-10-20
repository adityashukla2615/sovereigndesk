"""Helpers shared by the backend tests: mock HTTP, recorded fixtures and tiny seeds."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from tenacity import wait_none

if TYPE_CHECKING:
    from app.sim.anchors import USAnchors
    from app.sim.india_anchors import INAnchors

from app.data.catalog import SeriesSpec
from app.data.http import Fetcher, RawCache
from app.data.seed import Manifest, write_manifest, write_series
from app.data.sources.base import Provenance, SeriesFrame, tidy

SOURCES = Path(__file__).parent / "fixtures" / "sources"
SEED_FETCHED = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

Handler = Callable[[httpx2.Request], httpx2.Response]


def fixture_bytes(name: str) -> bytes:
    return (SOURCES / name).read_bytes()


def make_fetcher(handler: Handler, cache_dir: Path, attempts: int = 3) -> Fetcher:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return Fetcher(
        client, RawCache(cache_dir), attempts=attempts, wait=wait_none(), sleep=lambda _: None
    )


def query(request: httpx2.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}


def json_response(payload: bytes | dict[str, Any], status: int = 200) -> httpx2.Response:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return httpx2.Response(status, content=content, headers={"content-type": "application/json"})


def frame(
    spec: SeriesSpec,
    points: list[tuple[date, float]],
    *,
    when: datetime = SEED_FETCHED,
    from_cache: bool = False,
) -> SeriesFrame:
    provenance = Provenance(spec.source, f"https://example.test/{spec.remote}", when, from_cache)
    return SeriesFrame(spec, tidy(points), provenance)


def write_seed(seed_dir: Path, frames: list[SeriesFrame]) -> None:
    entries = [write_series(seed_dir, f) for f in frames]
    write_manifest(seed_dir, Manifest(SEED_FETCHED.isoformat(), entries, []))


def make_us_anchors(**overrides: object) -> "USAnchors":
    """Internally consistent US anchors with realistic magnitudes (Oct 2026 data), no database."""
    from datetime import date

    from app.sim.anchors import USAnchors
    from app.sim.us_market import EVAL_TENORS, par_from_zero
    from sovereign_engine.curves.nss import NelsonSiegelSvensson
    from sovereign_engine.us.balance_sheet import FedBalanceSheet, QTPlan
    from sovereign_engine.us.corridor import FedCorridor, ReserveDemandCurve
    from sovereign_engine.us.debt import DebtSecurity, IssuanceMix

    zero = NelsonSiegelSvensson(0.0, 0.0392, 0.0494, 0.1701, 1.93, 15.76)
    ladder = [
        DebtSecurity("bill", date(2026, 12, 3), 0.0375, 3500.0, 0.25),
        DebtSecurity("bill", date(2027, 4, 1), 0.0372, 3600.0, 0.5),
        DebtSecurity("note", date(2027, 9, 30), 0.0350, 4000.0, 2.0),
        DebtSecurity("note", date(2029, 10, 15), 0.0400, 4000.0, 3.0),
        DebtSecurity("note", date(2031, 9, 30), 0.0380, 4100.0, 5.0),
        DebtSecurity("note", date(2036, 8, 15), 0.0420, 4200.0, 10.0),
        DebtSecurity("bond", date(2056, 8, 15), 0.0450, 5500.0, 30.0),
        DebtSecurity("tips", date(2035, 1, 15), 0.0120, 2170.0, 10.0),
        DebtSecurity("frn", date(2028, 7, 31), 0.0012, 710.0, 2.0),
    ]
    stock: dict[float, float] = {}
    for security in ladder:
        stock[security.term] = stock.get(security.term, 0.0) + security.outstanding
    values: dict[str, object] = {
        "as_of": date(2026, 10, 16),
        "corridor": FedCorridor(lower=0.0375, upper=0.04, iorb=0.039, on_rrp=0.0375),
        "effr": 0.0388,
        "par_curve": par_from_zero(zero.zero_rate(EVAL_TENORS)),
        "zero_curve": zero,
        "term_premium": 0.0085,
        "balance_sheet": FedBalanceSheet.from_h41(
            total_assets=6756,
            treasuries=4571,
            mbs=1898,
            reserves=3022,
            on_rrp=50,
            tga=883,
            currency=2488,
        ),
        "bank_assets": 26_100.0,
        "observed_qt": QTPlan(treasury_cap=0.0, mbs_cap=16.8),
        "reserve_curve": ReserveDemandCurve(-0.00065, 0.00019, 0.1155, 0.0055),
        "reserve_fit_rmse_bp": 2.35,
        "dollar_index": 121.0,
        "foreign_holdings": {
            "Japan": 1068.3,
            "United Kingdom": 1009.5,
            "China, Mainland": 590.7,
            "Grand Total": 9400.0,
        },
        "tic_as_of": date(2026, 8, 31),
        "debt_public": 32_538.0,
        "debt_public_2010": 8_634.0,
        "nominal_gdp": 32_563.0,
        "receipts_12m": 5_403.0,
        "deficit_12m": 1_993.0,
        "ladder": ladder,
        "issuance_mix": IssuanceMix.from_stock(stock),
        "mspd_as_of": date(2026, 9, 30),
        "quality": {},
    }
    values.update(overrides)
    return USAnchors(**values)  # type: ignore[arg-type]


def make_india_anchors(**overrides: object) -> "INAnchors":
    """India anchors with the magnitudes fitted on the real seed (Oct 2026), no database."""
    from datetime import timedelta

    import numpy as np

    from app.sim.india_anchors import Excursions, INAnchors, Reaction, SegmentSpreads, TaxCycle
    from sovereign_engine.india.excursions import DeviationModel
    from sovereign_engine.india.liquidity_map import LiquidityMap
    from sovereign_engine.india.reaction import ReactionCurve

    as_of = date(2026, 10, 16)
    values: dict[str, Any] = {
        "as_of": as_of,
        "repo": 0.055,
        "sdf": 0.0525,
        "msf": 0.0575,
        "crr": 0.03,
        "slr": 0.18,
        "ndtl": 27_776_966.67,
        "crr_requirement": 833_309.0,
        "surplus": 185_873.0,
        "vrr_outstanding": 0.0,
        "vrrr_outstanding": 56_825.0,
        "durable_liquidity": 1_014_401.0,
        "durable_as_of": date(2026, 9, 30),
        "wacr": 0.0528,
        "wacr_as_of": as_of,
        "call_volume": 15_677.0,
        "liquidity_map": LiquidityMap(0.00253, -0.00452, 0.792, 0.954),
        "map_rmse_bp": 17.4,
        "map_points": 1045,
        "map_residual_ar1": 0.29,
        "map_residual": 0.0,
        "spreads": SegmentSpreads(-0.0014, -0.0012, -0.0005, 0.00545, 27.7, 11.3, 0.0175, 0.05),
        "tbills": {"3M": 0.0565, "6M": 0.0586, "12M": 0.0632},
        "tbill_as_of": date(2026, 10, 12),
        "tbill_slopes": {"3M": -0.00088, "6M": -0.00035, "12M": 0.0},
        "tbill_slopes_fitted": {"3M": -0.00088, "6M": -0.00035, "12M": 0.00049},
        "tax": TaxCycle(128_425.0, 88_109.0, {10: -0.03, 20: 0.73}, 54),
        "noise_sd": 23_852.0,
        "ndtl_growth": 0.118,
        "reaction": Reaction(
            ReactionCurve(-2.2, -1.05), ReactionCurve(-2.8, 0.52), 34_528.0, 33_453.0, 136, 128
        ),
        # Skewed innovations like the fit's: mostly small, with occasional large falls.
        "deviations": DeviationModel(
            0.29,
            np.array(
                [0.0004, 0.0002, -0.0003, 0.0006, -0.0001, 0.0003, -0.0025, 0.0005, -0.0012, 0.0001]
            ),
            1.1,
            1.3,
        ),
        "excursions": Excursions(1214, 257, 80, 1045, 151, 70, 0.143, 0.069, -0.0113, 0.014),
        "history": [(as_of - timedelta(days=k), -0.0012) for k in range(30, 0, -1)],
        "quality": {"rbi/repo": "SEED 2026-10-20"},
    }
    values.update(overrides)
    return INAnchors(**values)
