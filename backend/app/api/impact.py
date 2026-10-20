"""Module E over REST: the simulated (or a hypothetical) shock applied to a portfolio and to
businesses the user describes. The IMPACT command shows the illustrative presets; the panel
posts its edits here."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.sim import get_sim
from app.sim.impact import impact_panel, market_bond, read_shock
from app.sim.simulator import Simulator
from sovereign_engine.impact import BusinessProfile, FundHolding, LoanTerms

router = APIRouter(tags=["impact"])


class BondIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    face: float = Field(gt=0, le=1e12)
    coupon: float = Field(ge=0, le=0.3, description="Annual coupon, decimal")
    years: float = Field(gt=0, le=50)
    spread_bp: float = Field(0.0, ge=-500, le=2000, description="Over the G-sec curve")


class FundIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    value: float = Field(gt=0, le=1e12)
    modified_duration: float = Field(ge=0, le=40)
    convexity: float = Field(ge=0, le=3000)


class LoanIn(BaseModel):
    amount: float = Field(ge=0, le=1e12)
    benchmark: Literal["EBLR", "MCLR"]
    spread: float = Field(ge=-0.05, le=0.2)
    reset_months: int = Field(ge=1, le=36)
    first_reset_month: int = Field(ge=0, le=36)
    tenor_months: int = Field(ge=1, le=360)


class ProfileIn(BaseModel):
    key: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=80)
    monthly_sales: float = Field(gt=0, le=1e12)
    cost_share: float = Field(ge=0, le=1)
    import_share: float = Field(ge=0, le=1)
    fx_to_price: float = Field(ge=0, le=1)
    inventory_days: float = Field(ge=0, le=730)
    rate_semi_elasticity: float = Field(ge=-50, le=0)
    price_elasticity: float = Field(ge=-20, le=0)
    loan: LoanIn


class ImpactRequest(BaseModel):
    bonds: list[BondIn] | None = Field(None, max_length=50)
    funds: list[FundIn] | None = Field(None, max_length=50)
    profiles: list[ProfileIn] | None = Field(None, max_length=10)
    shift_bp: float | None = Field(None, ge=-1000, le=1000, description="Hypothetical yields")
    repo_bp: float | None = Field(None, ge=-500, le=500, description="Hypothetical repo move")
    inr_pct: float | None = Field(None, ge=-50, le=50, description="Hypothetical rupee move")


@router.post("/impact", operation_id="postImpact")
async def impact(
    request: ImpactRequest, sim: Annotated[Simulator, Depends(get_sim)]
) -> dict[str, Any]:
    """Both Module E views for the given portfolio and businesses (the presets when omitted)."""
    model = await sim.impact_model()
    if model is None:
        raise HTTPException(status_code=503, detail=f"impact unavailable: {sim.impact_error}")
    if sim.india is None:
        raise HTTPException(status_code=503, detail="the India market is not running")
    try:
        shock = read_shock(
            sim.india,
            inr_base=sim.link.inr if sim.link is not None else None,
            shift_bp=request.shift_bp,
            repo_bp=request.repo_bp,
            inr_pct=request.inr_pct,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"impact unavailable: {exc}") from exc
    bonds = None
    if request.bonds is not None:
        bonds = [
            market_bond(b.name, b.face, b.coupon, b.years, b.spread_bp, shock)
            for b in request.bonds
        ]
    funds = (
        None
        if request.funds is None
        else [FundHolding(f.name, f.value, f.modified_duration, f.convexity) for f in request.funds]
    )
    profiles = None
    if request.profiles is not None:
        profiles = {
            p.key: BusinessProfile(
                name=p.name,
                monthly_sales=p.monthly_sales,
                cost_share=p.cost_share,
                import_share=p.import_share,
                fx_to_price=p.fx_to_price,
                inventory_days=p.inventory_days,
                rate_semi_elasticity=p.rate_semi_elasticity,
                price_elasticity=p.price_elasticity,
                loan=LoanTerms(
                    p.loan.amount,
                    p.loan.benchmark,
                    p.loan.spread,
                    p.loan.reset_months,
                    p.loan.first_reset_month,
                    p.loan.tenor_months,
                ),
            )
            for p in request.profiles
        }
    try:
        return impact_panel(model, sim.india, shock, bonds=bonds, funds=funds, profiles=profiles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
