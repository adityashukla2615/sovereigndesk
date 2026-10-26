"""The simulated Indian money market: SYNTHETIC banks trading call money inside RBI's corridor.

The market runs on Indian time, as a schedule of discrete steps, so every simulation speed
processes the same day:

* 00:00  last night's SDF and MSF reverse; on business days yesterday's call loans are repaid;
         RBI operations due today mature; autonomous liquidity lands (tax receipts around the
         15th of Mar/Jun/Sep/Dec and the 20th of each month, the government spending them back,
         noise, payments between banks); a new reporting fortnight resets the CRR accounts.
* 09:30  RBI's auctions: any VRR/VRRR you ordered, else its fitted reaction function.
* 09:15 to 19:00, every 15 minutes: a uniform-price call auction. Each bank aims for its CRR
         target; borrowers bid and lenders offer around the macro-map rate, repo + s(surplus),
         with reservation rates bounded by the MSF (borrowers' outside option) and the SDF
         (lenders'), so WACR cannot leave the corridor. Participation limits trim every order,
         and each trimmed amount is logged with its reason.
* 19:00  standing facilities, once the call market has closed: surplus goes to the SDF,
         deficit is borrowed at the MSF up to each bank's capacity (excess SLR plus the 2% dip).

The call market's hours and the standing facilities' window are RBI's, from
``sovereign_engine.india.rules`` (call money until 7:00 PM since 1 Jul 2025).
* 23:59  end-of-day balances count toward the fortnight's CRR average; the daily floor is
         checked.

The G-sec curve (``gsec``) moves with the clearing rounds: its factors step every round, and
repo changes and the T-bills' liquidity spread reach it at once.

A US shock run through the linkage (``schedule_link``) lands from the next business day: each
day's rupee liquidity from RBI's dollar trades and its durable response joins the autonomous
flows at 00:00, its VRR/VRRR auctions run at 09:30, a repo hike moves the corridor, and the
rupee and the reserves follow the chain.

Business days are Monday to Friday (the simulator keeps no holiday calendar). Interest on
reserves and loans is not credited, so balances move only by principal.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np

from app.sim.events import EventKind, flow_bn, inr_cr
from app.sim.gsec import GsecCurve
from app.sim.india_anchors import (
    ADVANCE_TAX_DAY,
    ADVANCE_TAX_MONTHS,
    EVENT_HALF_WINDOW,
    GST_DAY,
    TBILL_TENORS,
    INAnchors,
)
from sovereign_engine.india.auctions import AuctionKind, AuctionResult, Bid, run_auction
from sovereign_engine.india.banks import (
    Bank,
    borrowing_caps,
    crr_daily_floor,
    crr_requirement,
    generate_universe,
    lending_caps,
    limit_check,
    limit_room,
    msf_capacity,
)
from sovereign_engine.india.call_market import Order, clear_call
from sovereign_engine.india.rules import (
    CALL_MARKET_HOURS,
    STANDING_FACILITY_HOURS,
    MoneyMarketRules,
    fortnight,
)
from sovereign_engine.linkage import ChainPath

IST = ZoneInfo("Asia/Kolkata")
WacrMode = Literal["realistic", "policy"]
ROUND_MINUTES = 15
SESSION_OPEN, SESSION_CLOSE = CALL_MARKET_HOURS
AUCTION_TIME = time(9, 30)
STANDING_TIME = STANDING_FACILITY_HOURS[0]
"""The window opens as the call market closes; it runs after the last round."""
EOD_TIME = time(23, 59)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


ROUNDS = (_minutes(SESSION_CLOSE) - _minutes(SESSION_OPEN)) // ROUND_MINUTES
"""Clearing rounds 09:15, 09:30, … 19:00."""
YEAR_DAYS = 365.25
TBILL_YEARS: dict[str, float] = {"3M": 0.25, "6M": 0.5, "12M": 1.0}


@dataclass(frozen=True, slots=True)
class IndiaModelParams:
    """Parameters that are assumptions rather than fits (listed in ASSUMPTIONS.md)."""

    bank_rate_sd: float = 0.0005
    """Spread of reservation rates across banks in a round (5 bp)."""
    round_rate_sd: float = 0.0008
    """Common noise of each round's centre rate (8 bp)."""
    urgency: float = 0.0010
    """How far reservation rates lean toward the facilities by the close (10 bp)."""
    idio_sd: float = 0.006
    """Stationary s.d. of a bank's own liquidity position (zero-sum across banks), as a share
    of its NDTL: large enough that someone lends even when the system is short (call volume
    then runs above RBI's; see ASSUMPTIONS.md)."""
    idio_half_life_days: float = 10.0
    noise_half_life_days: float = 30.0
    tax_hold_days: int = 10
    """Tax receipts stay with the government this long (event study: ~0% back after 10 days)."""
    tax_return_days: int = 14
    """…then come back evenly over this many days (event study: ~73% back after 20 days)."""
    pd_funding_nof: float = 1.0
    """Primary dealers' daily call funding need, × net owned funds."""
    order_pace: float = 1.5
    """Banks offer gap × min(1, pace / rounds left) each round."""
    initial_vrrr_days: int = 7
    """The release gives only the VRRR total outstanding; it is assumed to mature in a week."""
    reaction: bool = True
    mode: WacrMode = "realistic"
    """``realistic``: WACR may leave the corridor as far as it has since April 2022, as often as
    the calibrated deviations say; ``policy``: reservation rates are clamped to [SDF, MSF]."""
    stale_after_days: int = 3
    """Inputs older than this (calendar days) are flagged STALE, e.g. FBIL's lagged T-bills."""


@dataclass(slots=True)
class FxRun:
    """A linkage chain applied to the money market, one business day at a time."""

    path: ChainPath
    days: list[date]
    """The business day each of the chain's days lands on."""
    applied: int = 0


LINK_AUCTION_DAYS = 7
"""Tenor of the linkage's weekly VRR/VRRR auctions: each matures at the next."""


@dataclass(frozen=True, slots=True)
class Notice:
    kind: EventKind
    code: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BankBook:
    bank: Bank
    balance: float = 0.0
    """Cash with RBI, ₹ crore (unused for primary dealers)."""
    requirement: float = 0.0
    floor: float = 0.0
    target: float = 0.0
    eod_sum: float = 0.0
    eod_days: int = 0
    borrowed: float = 0.0
    """Call/notice borrowing outstanding (repaid the next business day)."""
    lent: float = 0.0
    borrow_sum: float = 0.0
    """Σ end-of-day borrowing this fortnight (for the average limit)."""
    lend_sum: float = 0.0
    sdf: float = 0.0
    msf: float = 0.0
    floor_breaches: int = 0

    @property
    def is_dealer(self) -> bool:
        return self.bank.kind == "PD"

    @property
    def gap(self) -> float:
        return self.balance - self.target


@dataclass(slots=True)
class Operation:
    kind: AuctionKind
    amount: float
    rate: float
    start: date
    maturity: date
    by_bank: dict[str, float]


@dataclass(frozen=True, slots=True)
class RoundPrint:
    at: datetime
    rate: float
    volume: float
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class Rejection:
    at: datetime
    bank: str
    side: Literal["borrow", "lend"]
    amount: float
    reason: str


@dataclass(frozen=True, slots=True)
class DayRecord:
    day: date
    wacr: float | None
    volume: float
    high: float | None
    low: float | None
    repo: float
    surplus: float
    surplus_pct: float
    government: float = 0.0
    """Tax receipts the government holds at RBI beyond the anchor day's (₹ crore, end of day)."""
    vrr: float = 0.0
    """VRR allotted today (₹ crore)."""
    vrrr: float = 0.0
    """VRRR allotted today (₹ crore)."""


@dataclass(frozen=True, slots=True)
class AuctionRecord:
    at: datetime
    tenor_days: int
    manual: bool
    result: AuctionResult


def is_business_day(day: date) -> bool:
    return day.weekday() < 5


def next_business_day(day: date) -> date:
    nxt = day + timedelta(days=1)
    while not is_business_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def tax_drain(day: date, anchors: INAnchors) -> float:
    """Expected drain of the day from advance tax (13-17 of a quarter month) and GST (18-22)."""
    w = EVENT_HALF_WINDOW
    drain = 0.0
    if day.month in ADVANCE_TAX_MONTHS and abs(day.day - ADVANCE_TAX_DAY) <= w:
        drain += anchors.tax.advance_tax_drain / (2 * w + 1)
    if abs(day.day - GST_DAY) <= w:
        drain += anchors.tax.gst_drain / (2 * w + 1)
    return drain


class IndiaMarket:
    def __init__(
        self,
        anchors: INAnchors,
        rng: np.random.Generator,
        now: datetime,
        params: IndiaModelParams | None = None,
    ) -> None:
        self.anchors = anchors
        self.params = params or IndiaModelParams()
        self.rng = rng
        # A stream of its own (spawned, so the money market's draws are unchanged).
        self.gsec = None if anchors.gsec is None else GsecCurve(anchors.gsec, rng.spawn(1)[0])
        self.tbill_beta = {
            t: 1.0 if self.gsec is None else self.gsec.tbill_beta(y) for t, y in TBILL_YEARS.items()
        }
        """How much of a repo change each T-bill takes: the G-sec pass-through β(τ), else one."""
        self.repo, self.sdf, self.msf = anchors.repo, anchors.sdf, anchors.msf
        self.crr = anchors.crr
        self.rules = MoneyMarketRules(crr=anchors.crr, slr=anchors.slr)
        self.pending_crr: tuple[date, float] | None = None
        self.last_policy_change: float | None = None
        """The latest repo move made in the simulation (decimal), if any."""
        self.books: dict[str, BankBook] = {
            b.code: BankBook(b) for b in generate_universe(anchors.ndtl, self.rules, rng)
        }
        self.depositors = [b for b in self.books.values() if not b.is_dealer]
        self.dealers = [b for b in self.books.values() if b.is_dealer]
        weights = np.array([b.bank.ndtl for b in self.depositors])
        self.weights = weights / weights.sum()
        self.ndtl_scale = 1.0
        self.idio = self._own_positions()
        self.anchor_time = now
        self.now = now
        self._cursor: tuple[datetime, int] = (now, 10**6)
        """The last step run: steps at exactly ``now`` count as done."""
        self.autonomous = 0.0
        """Cumulative autonomous liquidity since the anchor (₹ crore)."""
        self.government = 0.0
        """Tax receipts held in the government's account at RBI beyond the anchor day's: what
        has drained from the banks on tax days and not yet been spent back (₹ crore)."""
        self.noise = 0.0
        self.mode: WacrMode = self.params.mode
        self.deviation = anchors.map_residual
        """Today's WACR deviation from the macro map: AR(1) across days, fitted."""
        self.returns: list[tuple[date, date, float]] = []
        self.operations: list[Operation] = []
        self.queued: list[tuple[AuctionKind, float, int]] = []
        self.auctions: list[AuctionRecord] = []
        self.rounds: list[RoundPrint] = []
        self.rejections: list[Rejection] = []
        self.history: list[DayRecord] = []
        self.standing_last: dict[str, float] = {"sdf": 0.0, "msf": 0.0}
        """Last night's SDF placements and MSF borrowing (the standing window), ₹ crore."""
        self.last_surplus_pct = anchors.surplus_pct
        self.auction_today = False
        self.pd_need: dict[str, float] = {}
        self.fx_runs: list[FxRun] = []
        self.inr: float | None = None
        """Rupees per dollar, once a linkage run has anchored it."""
        self.reserves_bn: float | None = None
        """RBI's foreign exchange reserves (US$ bn), likewise."""
        self.today = now.astimezone(IST).date()
        self.fortnight = fortnight(self.today)
        self._open_position()
        self.liquidity0 = self.system_liquidity()
        self._day_start(datetime.combine(self.today, time(0, 0), IST), opening=True)
        local = now.astimezone(IST)
        if is_business_day(self.today) and local.time() >= SESSION_OPEN:
            self._open(local)
        self._update_gsec()

    # ------------------------------------------------------------------ opening position

    def _open_position(self) -> None:
        """Last night as the latest release saw it: CRR met, surplus parked at RBI.

        The release's net absorption S splits into VRRR outstanding and the SDF − MSF residual;
        both are shared out by NDTL, and each bank's own position (drawn from its stationary
        spread, summing to zero) moves it to the SDF or the MSF.
        """
        a = self.anchors
        elapsed = (self.today - self.fortnight[0]).days
        for book in self.depositors:
            self._set_requirement(book)
            book.balance = book.requirement
            book.eod_sum, book.eod_days = book.requirement * elapsed, elapsed
        residual = a.surplus - a.vrrr_outstanding + a.vrr_outstanding
        for book, w, own in zip(self.depositors, self.weights, self.idio, strict=True):
            position = residual * w + own
            if position >= 0:
                book.sdf = position
            else:
                book.msf = min(-position, msf_capacity(book.bank, self.rules))
                book.balance += position + book.msf  # what the MSF could not cover
        opening: tuple[tuple[AuctionKind, float], ...] = (
            ("VRRR", a.vrrr_outstanding),
            ("VRR", a.vrr_outstanding),
        )
        self.standing_last = {
            "sdf": sum(b.sdf for b in self.depositors),
            "msf": sum(b.msf for b in self.depositors),
        }
        maturity = self.today + timedelta(days=self.params.initial_vrrr_days)
        for kind, amount in opening:
            if amount > 0:
                by_bank = {
                    b.bank.code: amount * w
                    for b, w in zip(self.depositors, self.weights, strict=True)
                }
                self.operations.append(
                    Operation(kind, amount, self.repo, self.today, maturity, by_bank)
                )

    def _set_requirement(self, book: BankBook) -> None:
        bank = replace(book.bank, ndtl=book.bank.ndtl * self.ndtl_scale)
        book.requirement = crr_requirement(bank, self.rules)
        book.floor = crr_daily_floor(bank, self.rules)

    # ------------------------------------------------------------------ the clock

    def _schedule(self, day: date) -> list[tuple[datetime, Callable[[datetime], list[Notice]]]]:
        def at(t: time) -> datetime:
            return datetime.combine(day, t, IST)

        items: list[tuple[datetime, Callable[[datetime], list[Notice]]]] = [
            (at(time(0, 0)), self._day_start)
        ]
        if is_business_day(day):
            items.append((at(SESSION_OPEN), self._open))
            items.append((at(AUCTION_TIME), self._auctions))
            opening = at(SESSION_OPEN)
            items += [
                (opening + timedelta(minutes=ROUND_MINUTES * k), self._round)
                for k in range(1, ROUNDS + 1)
            ]
        items += [(at(STANDING_TIME), self._standing), (at(EOD_TIME), self._end_of_day)]
        return sorted(items, key=lambda item: item[0])

    def _next_event(
        self, cursor: tuple[datetime, int]
    ) -> tuple[datetime, int, Callable[[datetime], list[Notice]]]:
        """The first step after ``cursor`` = (time, position in that day's schedule), so steps
        sharing a time (the 09:30 auction and round) all run, in schedule order."""
        day = cursor[0].astimezone(IST).date()
        for candidate in (day, day + timedelta(days=1)):
            for index, (when, handler) in enumerate(self._schedule(candidate)):
                if (when, index) > cursor:
                    return when, index, handler
        raise RuntimeError("unreachable: the next day always starts")

    def advance(self, until: datetime) -> list[Notice]:
        """Run every scheduled step after the last one run, up to and including ``until``."""
        notices: list[Notice] = []
        while True:
            when, index, handler = self._next_event(self._cursor)
            if when > until:
                break
            self._cursor = (when, index)
            self.now = when
            notices += handler(when)
        self.now = until
        return notices

    # ------------------------------------------------------------------ liquidity measures

    def outstanding(self, kind: AuctionKind) -> float:
        return sum(op.amount for op in self.operations if op.kind == kind)

    def ndtl(self) -> float:
        return self.anchors.ndtl * self.ndtl_scale

    def projected_surplus(self) -> float:
        """Net LAF absorption if every bank squared its position now (₹ crore).

        S = Σ gaps (heading to the SDF, or the MSF if negative) + VRRR − VRR outstanding.
        """
        gaps = sum(b.gap for b in self.depositors)
        return gaps + self.outstanding("VRRR") - self.outstanding("VRR")

    def surplus_pct(self) -> float:
        return self.projected_surplus() / self.ndtl() * 100

    def system_liquidity(self) -> float:
        """Banks' reserves plus their net claims on RBI: only autonomous flows change it."""
        reserves = sum(b.balance + b.sdf - b.msf for b in self.depositors)
        return reserves + self.outstanding("VRRR") - self.outstanding("VRR")

    def band(self) -> tuple[float, float]:
        """Where call prints may go: RBI's corridor in policy mode; in realistic mode, as far
        outside it as WACR has printed since April 2022."""
        if self.mode == "policy":
            return self.sdf, self.msf
        x = self.anchors.excursions
        return self.sdf + x.floor_gap, self.msf + x.ceiling_gap

    def map_rate(self) -> float:
        """Where the macro map, plus the day's deviation, puts WACR now (inside the band)."""
        rate = self.repo + float(self.anchors.liquidity_map.spread(self.surplus_pct()))
        lower, upper = self.band()
        return min(max(rate + self.deviation, lower), upper)

    def set_mode(self, mode: WacrMode) -> None:
        self.mode = mode

    # ------------------------------------------------------------------ day steps

    def _day_start(self, at: datetime, *, opening: bool = False) -> list[Notice]:
        notices: list[Notice] = []
        day = at.astimezone(IST).date()
        self.today = day
        self.auction_today = False
        span = fortnight(day)
        if span != self.fortnight:
            notices += self._new_fortnight(span)
        for book in self.depositors:
            book.balance += book.sdf - book.msf
            book.sdf = book.msf = 0.0
        if is_business_day(day) and not opening:
            dealer_repaid = 0.0
            for book in self.books.values():
                if book.is_dealer:
                    dealer_repaid += book.borrowed
                else:
                    book.balance += book.lent - book.borrowed
                book.borrowed = book.lent = 0.0
            self._spread(-dealer_repaid)  # dealers repay out of the securities they hold
        for op in [o for o in self.operations if o.maturity <= day]:
            sign = -1.0 if op.kind == "VRR" else 1.0
            for code, amount in op.by_bank.items():
                self.books[code].balance += sign * amount
            self.operations.remove(op)
            notices.append(
                Notice(
                    "info",
                    "LAF",
                    f"{op.kind} of {inr_cr(op.amount)} from {op.start:%d %b} reversed",
                )
            )
        if not opening:
            notices += self._autonomous(day)
            notices += self._fx_day(day)
        for book in self.depositors:
            self._set_target(book)
        return notices

    def _new_fortnight(self, span: tuple[date, date]) -> list[Notice]:
        notices: list[Notice] = []
        missed = [
            b
            for b in self.depositors
            if b.eod_days and b.eod_sum / b.eod_days < b.requirement - 1e-6
        ]
        if missed:
            short = sum(b.requirement - b.eod_sum / b.eod_days for b in missed)
            notices.append(
                Notice(
                    "warning",
                    "CRR",
                    f"{len(missed)} bank(s) missed the fortnight's average CRR by {inr_cr(short)}",
                )
            )
        self.fortnight = span
        years = (span[0] - self.anchor_time.astimezone(IST).date()).days / YEAR_DAYS
        self.ndtl_scale = math.exp(self.anchors.ndtl_growth * max(years, 0.0))
        if self.pending_crr is not None and self.pending_crr[0] <= span[0]:
            old = self.crr
            self.crr = self.pending_crr[1]
            self.rules = replace(self.rules, crr=self.crr)
            self.pending_crr = None
            notices.append(
                Notice(
                    "policy",
                    "CRR",
                    f"CRR {old * 100:.2f}% → {self.crr * 100:.2f}% of NDTL from today: banks "
                    f"must hold {inr_cr(abs(self.crr - old) * self.ndtl())} "
                    f"{'more' if self.crr > old else 'less'} with RBI",
                )
            )
        for book in self.books.values():
            book.eod_sum = book.borrow_sum = book.lend_sum = 0.0
            book.eod_days = 0
            if not book.is_dealer:
                self._set_requirement(book)
        return notices

    def _set_target(self, book: BankBook) -> None:
        """Balance needed tonight for the fortnight average still to be met."""
        start, end = self.fortnight
        days = (end - start).days + 1
        left = days - book.eod_days
        needed = (book.requirement * days - book.eod_sum) / left if left > 0 else book.requirement
        book.target = max(book.floor, needed)

    def _spread(self, amount: float) -> None:
        """Share a system-wide flow across banks by NDTL; the shares sum exactly to one."""
        if amount == 0:
            return
        for book, share in zip(self.depositors, self.weights, strict=True):
            book.balance += amount * float(share)

    def _own_positions(self, previous: np.ndarray | None = None) -> np.ndarray:
        """Banks' own liquidity positions: zero-sum, mean-reverting (OU), ₹ crore.

        x' = φ·x + σ·√(1 − φ²)·NDTLᵢ·ε,  φ = 2^(−1/half-life), then the NDTL-weighted sum is
        removed so the positions only move money between banks.
        """
        p = self.params
        sizes = np.array([b.bank.ndtl for b in self.depositors]) * self.ndtl_scale
        shocks = p.idio_sd * sizes * self.rng.standard_normal(sizes.size)
        if previous is None:
            drawn = shocks
        else:
            phi = 2 ** (-1 / p.idio_half_life_days)
            drawn = phi * previous + math.sqrt(1 - phi**2) * shocks
        return np.asarray(drawn - drawn.sum() * self.weights, dtype=np.float64)

    def _autonomous(self, day: date) -> list[Notice]:
        p, a = self.params, self.anchors
        notices: list[Notice] = []
        drain = tax_drain(day, a)
        if drain > 0:
            start = day + timedelta(days=p.tax_hold_days)
            self.returns.append(
                (start, start + timedelta(days=p.tax_return_days - 1), drain / p.tax_return_days)
            )
            w = EVENT_HALF_WINDOW
            starts = {GST_DAY - w: ("GST", a.tax.gst_drain)}
            if day.month in ADVANCE_TAX_MONTHS:
                starts[ADVANCE_TAX_DAY - w] = ("Advance tax", a.tax.advance_tax_drain)
            if day.day in starts:
                label, total = starts[day.day]
                notices.append(
                    Notice(
                        "info",
                        "TAX",
                        f"{label} season: about {inr_cr(total)} will leave banks for the "
                        f"government's account over the next {2 * w + 1} days, and come back as "
                        f"it is spent from about {p.tax_hold_days} days on",
                        {"label": label, "drain": total},
                    )
                )
        back = sum(amount for first, last, amount in self.returns if first <= day <= last)
        self.returns = [r for r in self.returns if r[1] >= day]
        self.government += drain - back
        phi = 2 ** (-1 / p.noise_half_life_days)
        previous = self.noise
        self.noise = phi * self.noise + a.noise_sd * float(self.rng.standard_normal())
        flow = -drain + back + (self.noise - previous)
        self.autonomous += flow
        self._spread(flow)
        if is_business_day(day):
            updated = self._own_positions(self.idio)
            for book, move in zip(self.depositors, updated - self.idio, strict=True):
                book.balance += float(move)
            self.idio = updated
        return notices

    def _fx_day(self, day: date) -> list[Notice]:
        """Today's step of each linkage run: liquidity, auctions, repo, the rupee, reserves."""
        notices: list[Notice] = []
        for run in self.fx_runs:
            if run.applied >= len(run.days) or run.days[run.applied] != day:
                continue
            k, p = run.applied, run.path
            run.applied += 1
            flow = float(p.drain_cr[k] + p.injection_cr[k])
            self.autonomous += flow
            self._spread(flow)
            inr_before = p.start.inr if k == 0 else float(p.inr[k - 1])
            reserves_before = p.start.reserves_bn if k == 0 else float(p.reserves_bn[k - 1])
            self.inr = (self.inr or p.start.inr) * float(p.inr[k]) / inr_before
            self.reserves_bn = (self.reserves_bn or p.start.reserves_bn) + (
                float(p.reserves_bn[k]) - reserves_before
            )
            if k == 0:
                if self.gsec is not None:
                    self.gsec.shift_term_premium(float(p.in10y_bp[0]) / 1e4)
                    self._update_gsec()
                total = float(p.fpi_bn.sum())
                notices.append(
                    Notice(
                        "info",
                        "LINK",
                        f"Day 1 of the US shock: India 10Y {float(p.in10y_bp[0]):+.1f} bp; "
                        f"FPI flows of about {flow_bn(total)} begin over the month; RBI "
                        f"{'sells' if total < 0 else 'buys'} {p.params.intervention:.0%} of them",
                    )
                )
            move = float(p.repo_bp[k] - (p.repo_bp[k - 1] if k else 0.0))
            if move:
                self.set_repo(move / 1e4)
                notices.append(
                    Notice(
                        "policy",
                        "REPO",
                        f"RBI answers the outflow with a repo hike of {move:+.0f} bp: "
                        f"repo {self.repo * 100:.2f}%, SDF {self.sdf * 100:.2f}%, "
                        f"MSF {self.msf * 100:.2f}%",
                    )
                )
            vrr = float(p.vrr_cr[k])
            if abs(vrr) >= 1.0:
                kind: AuctionKind = "VRR" if vrr > 0 else "VRRR"
                self.order_auction(kind, abs(vrr), LINK_AUCTION_DAYS)
                notices.append(
                    Notice(
                        "info",
                        "LINK",
                        f"RBI offers a {LINK_AUCTION_DAYS}-day {kind} of {inr_cr(abs(vrr))} at "
                        f"09:30 against the {'drain' if vrr > 0 else 'inflow'} so far",
                    )
                )
            injected = float(p.injection_cr[k])
            if abs(injected) >= 1.0:
                what = (
                    ("a buy/sell swap" if p.response == "swap" else "OMO purchases")
                    if injected > 0
                    else ("a sell/buy swap" if p.response == "swap" else "OMO sales")
                )
                notices.append(
                    Notice(
                        "info",
                        "LINK",
                        f"RBI {'injects' if injected > 0 else 'absorbs'} {inr_cr(abs(injected))} "
                        f"through {what}",
                    )
                )
            if run.applied == len(run.days):
                t = p.totals()
                notices.append(
                    Notice(
                        "info",
                        "LINK",
                        f"The US shock's {len(run.days)} business days are over: FPI "
                        f"{flow_bn(t['fpi_bn'])}, RBI's reserves {flow_bn(t['reserves_bn'])}, "
                        f"rupee {t['inr_pct']:+.2f}%, liquidity from RBI's dollar trades "
                        f"{inr_cr(t['drain_cr'])}",
                        t,
                    )
                )
        self.fx_runs = [r for r in self.fx_runs if r.applied < len(r.days)]
        return notices

    def schedule_link(self, path: ChainPath) -> list[date]:
        """Run a linkage chain from the next business day (a US move comes after India's close),
        on top of any still running; returns the business day of each chain day."""
        if self.inr is None or self.reserves_bn is None:
            self.inr, self.reserves_bn = path.start.inr, path.start.reserves_bn
        days, day = [], self._today()
        for _ in range(path.days):
            day = next_business_day(day)
            days.append(day)
        self.fx_runs.append(FxRun(path, days))
        return days

    def _open(self, at: datetime) -> list[Notice]:
        self.rounds = []
        for book in self.depositors:
            self._set_target(book)
        for book in self.dealers:
            self.pd_need[book.bank.code] = self.params.pd_funding_nof * book.bank.capital_funds
        return []

    def _auctions(self, at: datetime) -> list[Notice]:
        notices = self._run_queued(at)
        if self.params.reaction and not self.auction_today:
            r = self.anchors.reaction
            p_vrr = float(r.vrr.probability(self.last_surplus_pct))
            p_vrrr = float(r.vrrr.probability(self.last_surplus_pct))
            u = float(self.rng.uniform())
            if u < p_vrr:
                notices += self._auction("VRR", r.vrr_size, 1, at, manual=False)
            elif u < p_vrr + p_vrrr:
                notices += self._auction("VRRR", r.vrrr_size, 1, at, manual=False)
        return notices

    def _run_queued(self, at: datetime) -> list[Notice]:
        notices: list[Notice] = []
        while self.queued:
            kind, amount, tenor = self.queued.pop(0)
            notices += self._auction(kind, amount, tenor, at, manual=True)
        return notices

    def _auction(
        self, kind: AuctionKind, notified: float, tenor_days: int, at: datetime, *, manual: bool
    ) -> list[Notice]:
        rng = self.rng
        bids: list[Bid] = []
        for book in self.depositors:
            gap = book.gap
            if kind == "VRR" and gap < -1:
                rate = self.repo + float(rng.uniform(0.0001, 0.0020))
                bids.append(Bid(book.bank.code, -gap * float(rng.uniform(0.6, 1.2)), rate))
            elif kind == "VRRR" and gap > 1:
                rate = max(self.repo - float(rng.uniform(0.0001, 0.0024)), self.sdf + 0.0001)
                bids.append(Bid(book.bank.code, gap * float(rng.uniform(0.5, 1.0)), rate))
        result = run_auction(kind, notified, bids, self.repo)
        sign = 1.0 if kind == "VRR" else -1.0
        allotted = result.by_bank()
        for code, amount in allotted.items():
            self.books[code].balance += sign * amount
        day = at.astimezone(IST).date()
        maturity = next_business_day(day) if tenor_days <= 1 else day + timedelta(days=tenor_days)
        if result.allotted > 0:
            self.operations.append(
                Operation(
                    kind,
                    result.allotted,
                    result.weighted_average or self.repo,
                    day,
                    maturity,
                    allotted,
                )
            )
        self.auction_today = True
        self.auctions = [*self.auctions[-19:], AuctionRecord(at, tenor_days, manual, result)]
        verb = "injects" if kind == "VRR" else "absorbs"
        cut = (
            f"cut-off {result.cut_off * 100:.2f}%"
            if result.cut_off is not None
            else "no valid bids"
        )
        wavg = (
            f", weighted average {result.weighted_average * 100:.2f}%"
            if result.weighted_average is not None
            else ""
        )
        who = "You ordered" if manual else "RBI runs"
        text = (
            f"{who} a {tenor_days}-day {kind} of {inr_cr(notified)}: "
            f"bids {inr_cr(result.received)} "
            f"from {len(bids)} banks, {verb} {inr_cr(result.allotted)} ({cut}{wavg}); "
            f"reverses {maturity:%a %d %b}"
        )
        data = {
            "kind": kind,
            "notified": notified,
            "received": result.received,
            "allotted": result.allotted,
            "cut_off": result.cut_off,
            "weighted_average": result.weighted_average,
            "tenor_days": tenor_days,
            "maturity": maturity.isoformat(),
        }
        return [Notice("policy", kind, text, data)]

    def _update_gsec(self) -> None:
        if self.gsec is not None:
            self.gsec.update(self.tbills(), self.repo - self.gsec.anchors.repo)

    def _round(self, at: datetime) -> list[Notice]:
        if self.gsec is not None:
            self.gsec.step(1 / ROUNDS)
            self._update_gsec()
        notices: list[Notice] = []
        local = at.astimezone(IST)
        if self.queued and local.time() > AUCTION_TIME:
            notices += self._run_queued(at)
        p = self.params
        opened = datetime.combine(local.date(), SESSION_OPEN, IST)
        k = round((local - opened).total_seconds() / 60 / ROUND_MINUTES)
        left = max(ROUNDS - k + 1, 1)
        take = min(1.0, p.order_pace / left)
        lean = p.urgency * k / ROUNDS
        centre = self.map_rate() + p.round_rate_sd * float(self.rng.standard_normal())
        start, end = self.fortnight
        days = (end - start).days + 1
        today = local.date()
        carry = min((next_business_day(today) - today).days, (end - today).days + 1)
        bids: list[Order] = []
        offers: list[Order] = []

        lower, upper = self.band()

        def clamp(rate: float) -> float:
            return min(max(rate, lower), upper)

        def noise() -> float:
            return p.bank_rate_sd * float(self.rng.standard_normal())

        for book in self.books.values():
            if book.is_dealer:
                want = (self.pd_need.get(book.bank.code, 0.0) - book.borrowed) * take
                side: Literal["borrow", "lend"] = "borrow"
            elif book.gap < -1:
                want, side = -book.gap * take, "borrow"
            elif book.gap > 1:
                want, side = book.gap * take, "lend"
            else:
                continue
            if want < 1:
                continue
            if side == "borrow":
                avg, peak = borrowing_caps(book.bank, self.rules)
                outstanding, used = book.borrowed, book.borrow_sum
            else:
                avg, peak_lend = lending_caps(book.bank, self.rules)
                peak, outstanding, used = peak_lend, book.lent, book.lend_sum
            room = limit_room(
                outstanding=outstanding,
                fortnight_sum=used,
                avg_cap=avg,
                peak_cap=peak,
                fortnight_days=days,
                carry_days=carry,
            )
            if want > room + 1e-6:
                reason = limit_check(
                    outstanding=outstanding,
                    proposed=want,
                    fortnight_sum=used,
                    avg_cap=avg,
                    peak_cap=peak,
                    fortnight_days=days,
                    carry_days=carry,
                )
                self.rejections = [
                    *self.rejections[-199:],
                    Rejection(at, book.bank.code, side, want - room, reason or "limit reached"),
                ]
                want = room
            if want < 1:
                continue
            if side == "borrow":
                bids.append(Order(book.bank.code, want, clamp(centre + noise() + lean)))
            else:
                offers.append(Order(book.bank.code, want, clamp(centre + noise() - lean)))
        clearing = clear_call(bids, offers)
        if clearing.rate is None or clearing.volume <= 0:
            return notices
        dealer_cash = 0.0
        for code, amount in clearing.borrowed.items():
            book = self.books[code]
            book.borrowed += amount
            if book.is_dealer:
                dealer_cash += amount
            else:
                book.balance += amount
        for code, amount in clearing.lent.items():
            book = self.books[code]
            book.lent += amount
            book.balance -= amount
        self._spread(dealer_cash)  # dealers pay for securities: the cash returns to banks
        self.rounds.append(RoundPrint(at, clearing.rate, clearing.volume, lower, upper))
        return notices

    def _standing(self, at: datetime) -> list[Notice]:
        short: list[tuple[str, float]] = []
        for book in self.depositors:
            gap = book.gap
            if gap > 0:
                book.sdf, book.balance = gap, book.balance - gap
            elif gap < 0:
                borrow = min(-gap, msf_capacity(book.bank, self.rules))
                book.msf, book.balance = borrow, book.balance + borrow
                if -gap - borrow > 1:
                    short.append((book.bank.code, -gap - borrow))
        self.standing_last = {
            "sdf": sum(b.sdf for b in self.depositors),
            "msf": sum(b.msf for b in self.depositors),
        }
        if not short:
            return []
        total = sum(v for _, v in short)
        names = ", ".join(code for code, _ in short[:3])
        return [
            Notice(
                "warning",
                "MSF",
                f"{names}{' and others' if len(short) > 3 else ''} short {inr_cr(total)} after "
                "using all their MSF capacity: below their CRR target tonight",
            )
        ]

    def _end_of_day(self, at: datetime) -> list[Notice]:
        notices: list[Notice] = []
        day = at.astimezone(IST).date()
        breaches = []
        for book in self.books.values():
            book.borrow_sum += book.borrowed
            book.lend_sum += book.lent
            if book.is_dealer:
                continue
            book.eod_sum += book.balance
            book.eod_days += 1
            if book.balance < book.floor - 1e-6:
                book.floor_breaches += 1
                breaches.append(book.bank.code)
        if breaches:
            notices.append(
                Notice(
                    "warning",
                    "CRR",
                    f"{', '.join(breaches[:3])}{' and others' if len(breaches) > 3 else ''} "
                    f"below the daily CRR floor "
                    f"({self.rules.crr_daily_min_share:.0%} of the requirement)",
                )
            )
        surplus = (
            sum(b.sdf - b.msf for b in self.depositors)
            + self.outstanding("VRRR")
            - self.outstanding("VRR")
        )
        volume = sum(r.volume for r in self.rounds) if is_business_day(day) else 0.0
        wacr = self.wacr_today() if is_business_day(day) else None
        rates = [r.rate for r in self.rounds] if is_business_day(day) else []
        allotted = {"VRR": 0.0, "VRRR": 0.0}
        for rec in self.auctions:
            if rec.at.astimezone(IST).date() == day:
                allotted[rec.result.kind] += rec.result.allotted
        self.history = [
            *self.history[-399:],
            DayRecord(
                day,
                wacr,
                volume,
                max(rates) if rates else None,
                min(rates) if rates else None,
                self.repo,
                surplus,
                surplus / self.ndtl() * 100,
                government=self.government,
                vrr=allotted["VRR"],
                vrrr=allotted["VRRR"],
            ),
        ]
        self.last_surplus_pct = surplus / self.ndtl() * 100
        self.deviation = self.anchors.deviations.step(self.deviation, self.rng)
        if is_business_day(day):
            self.rounds = []
            if self.gsec is not None:
                self._update_gsec()
                self.gsec.close(day)
        return notices

    # ------------------------------------------------------------------ readings

    def wacr_today(self) -> float | None:
        volume = sum(r.volume for r in self.rounds)
        if volume <= 0:
            return None
        return sum(r.rate * r.volume for r in self.rounds) / volume

    def wacr(self) -> float:
        """Today's running WACR, else the last simulated day's, else the anchored print."""
        today = self.wacr_today()
        if today is not None:
            return today
        last = next((d.wacr for d in reversed(self.history) if d.wacr is not None), None)
        return last if last is not None else self.anchors.wacr

    def segment_rates(self) -> dict[str, float]:
        s = self.anchors.spreads
        w = self.wacr()
        return {
            "treps": w + s.treps,
            "market_repo": w + s.market_repo,
            "notice": w + s.notice,
            "term": w + s.term,
        }

    def tbills(self) -> dict[str, float]:
        """FBIL's benchmarks plus the repo change passed through by β(τ) and the liquidity
        spread's move."""
        a = self.anchors
        shift = self.repo - a.repo
        move = self.surplus_pct() - a.surplus_pct
        return {
            t: a.tbills[t] + self.tbill_beta[t] * shift + a.tbill_slopes[t] * move
            for t in TBILL_TENORS
        }

    def check_invariants(self) -> None:
        """Asserted on every tick; a failure is a bug, not a market event."""
        for print_ in self.rounds:
            if not print_.lower - 1e-12 <= print_.rate <= print_.upper + 1e-12:
                raise AssertionError(
                    f"call print {print_.rate:.6f} outside the corridor "
                    f"[{print_.lower}, {print_.upper}]"
                )
        borrowed = sum(b.borrowed for b in self.books.values())
        lent = sum(b.lent for b in self.books.values())
        if abs(borrowed - lent) > 1e-6 * max(1.0, lent):
            raise AssertionError(f"call market not zero-sum: borrowed {borrowed} vs lent {lent}")
        drift = self.system_liquidity() - self.liquidity0 - self.autonomous
        if abs(drift) > 1e-6 * self.ndtl():
            raise AssertionError(f"liquidity identity broken by ₹{drift:,.2f} cr")
        start, end = self.fortnight
        days = (end - start).days + 1
        for book in self.books.values():
            avg, peak = borrowing_caps(book.bank, self.rules)
            if peak is not None and book.borrowed > peak * (1 + 1e-9) + 1e-6:
                raise AssertionError(f"{book.bank.code} borrowed above its daily cap")
            if book.borrow_sum > avg * days * (1 + 1e-9) + 1e-6:
                raise AssertionError(f"{book.bank.code} breached its fortnightly borrowing average")
        if self.gsec is not None:
            self.gsec.check()

    # ------------------------------------------------------------------ policy and orders

    def set_repo(self, change: float) -> None:
        """An MPC decision: repo moves and the SDF and MSF move with it, at once; so do the
        T-bills and the G-sec curve, by the pass-through β(τ)."""
        self.repo += change
        self.sdf += change
        self.msf += change
        self.last_policy_change = change
        self._update_gsec()

    def schedule_crr(self, new_crr: float) -> tuple[date, float]:
        """A CRR change applies from the next reporting fortnight; returns (date, liquidity)."""
        if not 0 <= new_crr < 0.2:
            raise ValueError("CRR must be between 0% and 20% of NDTL")
        start = self.fortnight[1] + timedelta(days=1)
        self.pending_crr = (start, new_crr)
        return start, -(new_crr - self.crr) * self.ndtl()

    def order_auction(self, kind: AuctionKind, amount: float, tenor_days: int) -> datetime:
        """Queue a VRR/VRRR; it runs at the next 09:30 window or clearing round."""
        if amount <= 0:
            raise ValueError("the notified amount must be positive")
        if not 1 <= tenor_days <= 90:
            raise ValueError("tenor must be 1 to 90 days")
        self.queued.append((kind, amount, tenor_days))
        local = self.now.astimezone(IST)
        if is_business_day(local.date()) and local.time() < SESSION_CLOSE:
            if local.time() < AUCTION_TIME:
                return datetime.combine(local.date(), AUCTION_TIME, IST)
            for when, handler in self._schedule(local.date()):
                if when > self.now and handler == self._round:
                    return when
        return datetime.combine(next_business_day(local.date()), AUCTION_TIME, IST)

    # ------------------------------------------------------------------ panels

    def _today(self) -> date:
        return self.now.astimezone(IST).date()

    def call_panel(self) -> dict[str, Any]:
        today = self._today()
        rounds = self.rounds if is_business_day(today) else []
        volume = sum(r.volume for r in rounds)
        s = self.anchors.spreads

        def top(side: str) -> list[dict[str, Any]]:
            rows = [
                (b.bank.code, b.borrowed if side == "borrowed" else b.lent)
                for b in self.books.values()
            ]
            ranked = sorted((r for r in rows if r[1] > 0), key=lambda r: -r[1])[:8]
            return [{"bank": code, "amount": amount} for code, amount in ranked]

        rejected = [r for r in self.rejections if r.at.astimezone(IST).date() == today]
        return {
            "rounds": [
                {"time": r.at.astimezone(IST).strftime("%H:%M"), "rate": r.rate, "volume": r.volume}
                for r in rounds
            ],
            "borrowers": top("borrowed"),
            "lenders": top("lent"),
            "rejections": [
                {
                    "time": r.at.astimezone(IST).strftime("%H:%M"),
                    "bank": r.bank,
                    "side": r.side,
                    "amount": r.amount,
                    "reason": r.reason,
                }
                for r in rejected[-20:]
            ],
            "segments": self.segment_rates(),
            "segment_volumes": {
                "call": volume,
                "treps": volume * s.treps_volume,
                "market_repo": volume * s.market_repo_volume,
                "notice": volume * s.notice_volume,
                "term": volume * s.term_volume,
            },
        }

    def corridor_panel(self) -> dict[str, Any]:
        """WACR in the corridor: the fitted map, where the system is, real and simulated days."""
        a = self.anchors
        curve = a.liquidity_map
        grid = np.linspace(-2.0, 4.0, 61)
        lower, upper = self.band()
        rates = np.clip(self.repo + curve.spread(grid), lower, upper)
        return {
            "map": {
                "deficit": curve.deficit,
                "surplus": curve.surplus,
                "midpoint": curve.midpoint,
                "width": curve.width,
                "rmse_bp": a.map_rmse_bp,
                "points": a.map_points,
            },
            "curve": [
                {"surplus_pct": float(x), "rate": float(r)}
                for x, r in zip(grid, rates, strict=True)
            ],
            "now": {
                "surplus_pct": self.surplus_pct(),
                "map_rate": self.map_rate(),
                "wacr": self.wacr(),
            },
            "mode": self.mode,
            "band": {"lower": lower, "upper": upper},
            "excursions": {
                "trading_days": a.excursions.trading_days,
                "below_sdf": a.excursions.below_sdf,
                "above_msf": a.excursions.above_msf,
                "weekdays": a.excursions.weekdays,
                "weekday_below": a.excursions.weekday_below,
                "weekday_above": a.excursions.weekday_above,
                "simulated_below": a.excursions.simulated_below,
                "simulated_above": a.excursions.simulated_above,
            },
            "real": [{"date": d.isoformat(), "spread": s} for d, s in a.history[-90:]],
            "simulated": [
                {"date": d.day.isoformat(), "spread": d.wacr - d.repo}
                for d in self.history
                if d.wacr is not None
            ],
        }

    def laf_panel(self) -> dict[str, Any]:
        a = self.anchors
        r = a.reaction
        ell = self.last_surplus_pct
        return {
            "sdf": self.standing_last["sdf"],
            "msf": self.standing_last["msf"],
            "operations": [
                {
                    "kind": op.kind,
                    "amount": op.amount,
                    "rate": op.rate,
                    "start": op.start.isoformat(),
                    "maturity": op.maturity.isoformat(),
                }
                for op in self.operations
            ],
            "auctions": [
                {
                    "time": rec.at.astimezone(IST).isoformat(),
                    "kind": rec.result.kind,
                    "notified": rec.result.notified,
                    "received": rec.result.received,
                    "allotted": rec.result.allotted,
                    "cut_off": rec.result.cut_off,
                    "weighted_average": rec.result.weighted_average,
                    "tenor_days": rec.tenor_days,
                    "manual": rec.manual,
                }
                for rec in self.auctions[-10:]
            ],
            "surplus": self.projected_surplus(),
            "surplus_pct": self.surplus_pct(),
            "durable_liquidity": a.durable_liquidity,
            "durable_as_of": a.durable_as_of.isoformat(),
            "reaction": {
                "enabled": self.params.reaction,
                "vrr_probability": float(r.vrr.probability(ell)),
                "vrrr_probability": float(r.vrrr.probability(ell)),
                "vrr_size": r.vrr_size,
                "vrrr_size": r.vrrr_size,
            },
        }

    def banks_panel(self) -> list[dict[str, Any]]:
        rows = []
        for book in self.books.values():
            bank = book.bank
            avg, peak = borrowing_caps(bank, self.rules)
            rows.append(
                {
                    "code": bank.code,
                    "kind": bank.kind,
                    "ndtl": bank.ndtl * self.ndtl_scale,
                    "capital_funds": bank.capital_funds,
                    "requirement": book.requirement,
                    "balance": book.balance,
                    "target": book.target,
                    "slr_holdings": bank.slr_holdings,
                    "msf_capacity": 0.0 if book.is_dealer else msf_capacity(bank, self.rules),
                    "borrowed": book.borrowed,
                    "lent": book.lent,
                    "borrow_cap_avg": avg,
                    "borrow_cap_peak": peak,
                    "floor_breaches": book.floor_breaches,
                }
            )
        return rows

    def gsec_panel(self) -> dict[str, Any] | None:
        if self.gsec is None:
            return None
        return {**self.gsec.panel(), "now": self.gsec_tick()}

    def gsec_tick(self) -> dict[str, Any] | None:
        if self.gsec is None:
            return None
        return self.gsec.tick(self.stale_label(self.gsec.anchors.as_of))

    def heatmap(self, days_ahead: int = 120) -> dict[str, Any]:
        """Real WACR − repo by day; the simulated days so far, with the government's tax
        balance at RBI and RBI's auctions; and the days ahead from tax flows alone.

        The projection runs the expected tax drains and their spending back (no noise, no
        auctions): the government's balance rises as the system's surplus falls, rupee for
        rupee, and RBI's fitted reaction gives the chance of a VRR or VRRR at each surplus.
        """
        today = self._today()
        p, r = self.params, self.anchors.reaction
        upcoming = []
        for k in range(days_ahead):
            day = today + timedelta(days=k)
            drain = tax_drain(day, self.anchors)
            if drain > 0:
                upcoming.append({"date": day.isoformat(), "drain": drain})
        returns = list(self.returns)
        government, surplus, ndtl = self.government, self.projected_surplus(), self.ndtl()
        projection = []
        for k in range(1, days_ahead + 1):
            day = today + timedelta(days=k)
            drain = tax_drain(day, self.anchors)
            if drain > 0:
                start = day + timedelta(days=p.tax_hold_days)
                last_day = start + timedelta(days=p.tax_return_days - 1)
                returns.append((start, last_day, drain / p.tax_return_days))
            back = sum(amount for first, last, amount in returns if first <= day <= last)
            government += drain - back
            surplus -= drain - back
            share = surplus / ndtl * 100
            projection.append(
                {
                    "date": day.isoformat(),
                    "government": government,
                    "surplus": surplus,
                    "surplus_pct": share,
                    "p_vrr": float(r.vrr.probability(share)),
                    "p_vrrr": float(r.vrrr.probability(share)),
                }
            )
        tax = self.anchors.tax
        return {
            "real": [{"date": d.isoformat(), "spread": s} for d, s in self.anchors.history],
            "simulated": [
                {
                    "date": d.day.isoformat(),
                    "spread": None if d.wacr is None else d.wacr - d.repo,
                    "surplus": d.surplus,
                    "surplus_pct": d.surplus_pct,
                    "government": d.government,
                    "vrr": d.vrr,
                    "vrrr": d.vrrr,
                }
                for d in self.history
            ],
            "tax_days": upcoming,
            "projection": projection,
            "now": {
                "date": today.isoformat(),
                "government": self.government,
                "surplus": self.projected_surplus(),
                "surplus_pct": self.surplus_pct(),
            },
            "tax": {
                "advance_tax_drain": tax.advance_tax_drain,
                "gst_drain": tax.gst_drain,
                "events": tax.events,
                "hold_days": p.tax_hold_days,
                "return_days": p.tax_return_days,
            },
            "reaction": {
                "enabled": p.reaction,
                "vrr_size": r.vrr_size,
                "vrrr_size": r.vrrr_size,
            },
        }

    # ------------------------------------------------------------------ snapshots

    def snapshot(self) -> dict[str, Any]:
        local = self.now.astimezone(IST)
        today = self.rounds if is_business_day(local.date()) else []
        rates = [r.rate for r in today]
        start, end = self.fortnight
        return {
            "time": local.isoformat(),
            "session_open": is_business_day(local.date())
            and SESSION_OPEN <= local.time() <= SESSION_CLOSE,
            "corridor": {"sdf": self.sdf, "repo": self.repo, "msf": self.msf},
            "wacr": self.wacr(),
            "wacr_today": self.wacr_today(),
            "last_print": today[-1].rate if today else None,
            "map_rate": self.map_rate(),
            "call": {
                "volume": sum(r.volume for r in today),
                "high": max(rates) if rates else None,
                "low": min(rates) if rates else None,
                "rounds": len(today),
            },
            "surplus": self.projected_surplus(),
            "surplus_pct": self.surplus_pct(),
            "ndtl": self.ndtl(),
            "laf": {
                "sdf": self.standing_last["sdf"],
                "msf": self.standing_last["msf"],
                "vrr": self.outstanding("VRR"),
                "vrrr": self.outstanding("VRRR"),
            },
            "segments": self.segment_rates(),
            "tbills": self.tbills(),
            "crr": self.crr,
            "pending_crr": (
                {"from": self.pending_crr[0].isoformat(), "crr": self.pending_crr[1]}
                if self.pending_crr
                else None
            ),
            "fortnight": {"start": start.isoformat(), "end": end.isoformat()},
            "rejected_today": sum(
                1 for r in self.rejections if r.at.astimezone(IST).date() == local.date()
            ),
            "mode": self.mode,
            "band": {"lower": self.band()[0], "upper": self.band()[1]},
            "tbills_as_of": self.anchors.tbill_as_of.isoformat(),
            "tbills_stale": self.stale_label(self.anchors.tbill_as_of),
            "gsec": self.gsec_tick(),
            "fx": (
                None
                if self.inr is None
                else {"inr": self.inr, "reserves_bn": self.reserves_bn, "runs": len(self.fx_runs)}
            ),
            "as_of": self.anchors.as_of.isoformat(),
        }

    def stale_label(self, as_of: date) -> str | None:
        """``STALE 8d`` when an input's own date is older than the threshold, else None."""
        age = (self._today() - as_of).days
        return f"STALE {age}d" if age > self.params.stale_after_days else None
