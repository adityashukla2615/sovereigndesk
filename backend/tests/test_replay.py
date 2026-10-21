"""Module D on the committed replay datasets: loading, each episode's runner, the gilt λ and its
specifications, and the REPLAY command."""

import asyncio
import math
from datetime import UTC, date, datetime

import pytest

from app.commands import execute
from app.config import REPO_ROOT
from app.sim.linkage import LinkAssumptions, LinkModel
from app.sim.replay import (
    episode_ids,
    gilt_lambda,
    load_episode,
    replay_panel,
    run_advtax,
    run_dash,
    run_gilt,
    run_hike,
    run_taper,
)
from app.sim.simulator import Simulator
from sovereign_engine.linkage import LinkParams
from tests.support import make_india_anchors, make_us_anchors

ROOT = REPO_ROOT / "data" / "replays"
LINK = LinkParams(
    spillover=0.16,
    debt_flow=0.26,
    equity_flow=-4.0,
    risk_flow=-0.33,
    intervention=0.59,
    inr_per_bn=0.17,
)
MAP = make_india_anchors().liquidity_map


def test_every_episode_loads_with_its_provenance() -> None:
    ids = episode_ids(ROOT)
    assert ids == ["TAPER2013", "DASH2020", "HIKE2022", "GILT2022", "ADVTAX"]  # by start date
    for i in ids:
        ep = load_episode(ROOT, i)
        assert ep.start < ep.end
        assert ep.annotations, i
        for name, entry in ep.manifest.items():
            assert entry["url"], (i, name)
            assert entry["rows"] == len(ep.series(name)), (i, name)
    with pytest.raises(Exception, match="no replay"):
        load_episode(ROOT, "NOPE")


def _finite(values: list[float | None]) -> int:
    return sum(1 for v in values if v is not None and math.isfinite(v))


def test_taper_drives_the_chain_with_2013s_moves() -> None:
    result = run_taper(load_episode(ROOT, "TAPER2013"), LINK)
    keys = [t.key for t in result.targets]
    assert keys == ["fpi", "inr", "reserves"]
    fpi = result.targets[0]
    assert _finite(fpi.actual) > 90
    assert fpi.scores["chain"].end_model < 0  # money left as US yields rose
    assert fpi.scores["chain"].end_actual < 0
    assert result.facts["us10y_change_bp"] > 50
    assert any("direction" in line for line in fpi.summary)


def test_gilt_lambda_leaves_the_announcement_out_and_reports_every_spec() -> None:
    ep = load_episode(ROOT, "GILT2022")
    base, net, dy = gilt_lambda(ep)
    with_day, _, _ = gilt_lambda(ep, announcements=True)
    assert base.n == with_day.n - 1  # 28 Sep left out
    assert dy[datetime(2022, 9, 28)] < -100  # the announcement's own move
    assert base.lam > 0
    assert base.low < base.lam < base.high
    assert net[datetime(2022, 10, 14)] < 0  # the Bank outbought the forced sellers at the end
    result = run_gilt(ep)
    grid = result.facts["lambda"]["profiles"]
    assert len(grid) == 6  # three profiles, with and without the announcement day
    assert result.facts["lambda"]["bp_per_bn_gbp"] == pytest.approx(base.lam / 12.0)
    assert result.targets[0].key == "gilt30y"


def test_dash_prices_net_selling_two_ways() -> None:
    gilt = load_episode(ROOT, "GILT2022")
    result = run_dash(load_episode(ROOT, "DASH2020"), gilt)
    assert [t.key for t in result.targets] == ["us10y", "us30y"]
    for t in result.targets:
        assert {m.name for m in t.models} == {"gilt λ", "US impact model"}
    assert (
        result.facts["fed_purchases_bn"] > result.facts["foreign_sales_bn"]
    )  # the Fed bought more
    assert result.targets[0].scores["gilt λ"].end_model < 0  # net buying: yields down


def test_hike_and_advtax_use_the_macro_map() -> None:
    hike = run_hike(load_episode(ROOT, "HIKE2022"), MAP)
    assert [t.key for t in hike.targets] == ["us2y", "us10y", "wacr"]
    assert hike.facts["fed_change_bp"] == pytest.approx(525.0)
    assert hike.targets[0].scores["policy + QT"].end_model > 2  # the 2Y follows the Fed up
    tax = run_advtax(load_episode(ROOT, "ADVTAX"), MAP)
    assert len(tax.facts["segments"]) == 3
    assert all(s["peak_bp"] > 0 for s in tax.facts["segments"])


def test_panel_shape() -> None:
    result = run_gilt(load_episode(ROOT, "GILT2022"))
    panel = replay_panel(result, [{"id": "GILT2022", "title": "x"}])
    t = panel["targets"][0]
    assert len(t["dates"]) == len(t["actual"]) == len(t["models"][0]["values"])
    assert panel["episode"]["sources"]["gilt30y"].startswith("https://www.bankofengland.co.uk/")
    assert panel["annotations"][0]["source"].startswith("https://")


MORNING = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)


def test_replay_command() -> None:
    sim = Simulator(None, seed=3, clock=lambda: MORNING)
    sim.load(make_us_anchors(), make_india_anchors())
    listing = asyncio.run(execute(sim, "REPLAY"))
    assert listing.ok
    assert "TAPER2013" in listing.message
    gilt = asyncio.run(execute(sim, "REPLAY GILT2022"))
    assert gilt.ok, gilt.message
    assert gilt.panel == "REPLAY"
    assert gilt.data is not None
    assert gilt.data["episode"]["id"] == "GILT2022"
    taper = asyncio.run(execute(sim, "REPLAY TAPER2013"))
    assert not taper.ok  # no data service, so no calibrated linkage
    assert "needs the linkage" in taper.message
    sim.link = LinkModel(
        LINK, (), 88.0, date(2026, 10, 19), 700.0, date(2026, 10, 16), LinkAssumptions()
    )
    assert asyncio.run(execute(sim, "REPLAY taper2013")).ok  # ids in any case
    unknown = asyncio.run(execute(sim, "REPLAY 2008"))
    assert not unknown.ok
    assert "Unknown replay 2008" in unknown.message
