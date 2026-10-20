"""Module E on the simulators: the IMPACT command, the shocks it reads, and the REST endpoint."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router
from app.commands import execute
from app.sim.impact import ImpactModel, ImpactParams
from app.sim.simulator import Simulator
from sovereign_engine.impact import BenchmarkFit, PassThrough
from tests.support import make_gsec_anchors, make_india_anchors, make_us_anchors

MORNING = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)  # Tuesday 10:30 in Mumbai


def _model() -> ImpactModel:
    fit = BenchmarkFit(level=0.07, share=0.6, months=6.0, lag_months=0.0, rmse=0.0003, n=52)
    return ImpactModel(
        params=ImpactParams(),
        passthrough=PassThrough(mclr_per_repo=0.6, mclr_months=6.0),
        mclr_fit=fit,
        mclr_now=0.0861,
        mclr_as_of=date(2026, 9, 1),
        mclr_sample="monthly, Jun 2022–Sep 2026",
    )


def _simulator() -> Simulator:
    sim = Simulator(None, seed=3, clock=lambda: MORNING)
    sim.load(make_us_anchors(), make_india_anchors(gsec=make_gsec_anchors()))
    sim.impact = _model()
    return sim


def _run(sim: Simulator, text: str) -> tuple[str, dict[str, Any]]:
    reply = asyncio.run(execute(sim, text))
    assert reply.ok, reply.message
    assert reply.data is not None
    return reply.message, reply.data


def test_no_shock_yet_means_no_impact() -> None:
    message, data = _run(_simulator(), "IMPACT")
    assert data["shock"]["source"] == "simulation"
    totals = data["retail"]["totals"]
    assert abs(totals["change"]) < 1e-6 * totals["value0"]
    assert "Portfolio (ILLUSTRATIVE)" in message
    for business in data["business"]:
        assert max(abs(m) for m in business["margin"]) < 1e-6


def test_a_repo_hike_reaches_loans_and_bonds() -> None:
    sim = _simulator()
    assert asyncio.run(execute(sim, "REPO +25BP")).ok
    message, data = _run(sim, "IMPACT BUSINESS SHOP")
    assert data["shock"]["repo_bp"] == pytest.approx(25.0)
    shop = next(b for b in data["business"] if b["key"] == "SHOP")
    # EBLR: the whole 25 bp at the next reset, a month on.
    assert shop["loan_rate_bp"][0] == pytest.approx(25.0)
    assert shop["interest"][0] == pytest.approx(1_000_000 * 0.0025 / 12)
    assert all(m < 0 for m in shop["margin"])
    importer = next(b for b in data["business"] if b["key"] == "IMPORTER")
    # MCLR: nothing until the annual reset in month six, then only part of the move.
    assert importer["loan_rate_bp"][4] == 0.0
    assert 0 < importer["loan_rate_bp"][5] < 25.0
    assert "Small shop" in message
    # The bonds lose: the G-sec curve took the hike's pass-through.
    _, retail = _run(sim, "IMPACT RETAIL")
    assert retail["retail"]["totals"]["change"] < 0


def test_a_hypothetical_yield_shift_reprices_the_portfolio() -> None:
    _, data = _run(_simulator(), "IMPACT RETAIL +100BP")
    assert data["shock"]["source"] == "hypothetical"
    totals = data["retail"]["totals"]
    # Roughly −duration × 1%, and convexity makes the exact loss smaller than duration's.
    assert totals["change_pct"] == pytest.approx(-totals["modified_duration"], rel=0.1)
    assert totals["duration_only"] < totals["change"]
    bonds = [h for h in data["retail"]["holdings"] if h["kind"] == "bond"]
    thirty = next(h for h in bonds if h["name"].startswith("30-year"))
    assert thirty["hold"]["sale_gain"] < 0
    assert thirty["hold"]["realised_yield"] > thirty["hold"]["bought_yield"]
    assert abs(thirty["exact_pct"] - thirty["convexity_pct"]) < abs(
        thirty["exact_pct"] - thirty["duration_pct"]
    )
    funds = [h for h in data["retail"]["holdings"] if h["kind"] == "fund"]
    assert all(f["exact_pct"] is None and f["hold"] is None for f in funds)


def test_a_weaker_rupee_squeezes_the_importer() -> None:
    _, data = _run(_simulator(), "IMPACT BUSINESS IMPORTER INR+5")
    importer = next(b for b in data["business"] if b["key"] == "IMPORTER")
    assert importer["import_cost"][-1] > 0
    assert importer["price_pct"][-1] > 0
    assert importer["summary"]["margin"] < 0
    assert data["profile"] == "IMPORTER"


def test_impact_errors() -> None:
    sim = _simulator()
    reply = asyncio.run(execute(sim, "IMPACT RETAIL SOON"))
    assert not reply.ok
    assert "Unexpected SOON" in reply.message
    idle = Simulator(None, seed=3, clock=lambda: MORNING)
    idle.load(make_us_anchors(), make_india_anchors(gsec=make_gsec_anchors()))
    reply = asyncio.run(execute(idle, "IMPACT"))
    assert not reply.ok
    assert "Impact unavailable: no data service" in reply.message


def test_rest_endpoint_takes_a_portfolio_and_a_business() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.sim = _simulator()
    client = TestClient(app)
    body = {
        "bonds": [{"name": "7% 2035", "face": 100_000, "coupon": 0.07, "years": 9.0}],
        "funds": [
            {
                "name": "Dynamic bond fund",
                "value": 50_000,
                "modified_duration": 4.0,
                "convexity": 25.0,
            }
        ],
        "profiles": [
            {
                "key": "MINE",
                "name": "My workshop",
                "monthly_sales": 400_000,
                "cost_share": 0.8,
                "import_share": 0.2,
                "fx_to_price": 0.3,
                "inventory_days": 45,
                "rate_semi_elasticity": -0.5,
                "price_elasticity": -0.8,
                "loan": {
                    "amount": 500_000,
                    "benchmark": "EBLR",
                    "spread": 0.03,
                    "reset_months": 3,
                    "first_reset_month": 2,
                    "tenor_months": 24,
                },
            }
        ],
        "shift_bp": 50,
        "repo_bp": 25,
        "inr_pct": 2,
    }
    response = client.post("/api/impact", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert [h["name"] for h in data["retail"]["holdings"]] == ["7% 2035", "Dynamic bond fund"]
    mine = data["business"][0]
    assert mine["key"] == "MINE"
    assert mine["loan_rate_bp"][0] == 0.0  # before the first reset
    assert mine["loan_rate_bp"][1] == pytest.approx(25.0)
    bad = client.post(
        "/api/impact", json={"bonds": [{"name": "x", "face": 1, "coupon": 0.9, "years": 5}]}
    )
    assert bad.status_code == 422  # a 90% coupon is refused


def test_rupees_in_the_indian_grouping() -> None:
    from app.sim.events import inr

    assert inr(1_900_000) == "₹19,00,000"
    assert inr(123_456_789) == "₹12,34,56,789"
    assert inr(-34_000.4) == "−₹34,000"
    assert inr(999) == "₹999"
