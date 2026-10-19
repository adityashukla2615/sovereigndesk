import asyncio
from datetime import UTC, datetime, timedelta

from app.sim.simulator import DEFAULT_SPEED, Simulator
from tests.support import make_us_anchors

START = datetime(2026, 10, 19, 13, 30, tzinfo=UTC)


def _sim() -> Simulator:
    sim = Simulator(None, seed=3, clock=lambda: START)
    sim.load(make_us_anchors())
    return sim


def test_tick_advances_the_clock_and_publishes() -> None:
    sim = _sim()
    sub = sim.bus.subscribe()
    sub.topics.add("us.tick")
    sim.tick(1.0)
    assert sim.sim_time == START + timedelta(seconds=DEFAULT_SPEED)
    topic, payload = sub.queue.get_nowait()
    assert topic == "us.tick"
    assert payload["sim_time"] == sim.sim_time.isoformat()
    assert set(payload["curve"]) >= {"2Y", "10Y", "30Y"}


def test_snapshots_for_new_subscribers() -> None:
    sim = _sim()
    assert sim.snapshot("us.tick")["effr"] == sim.us.state.effr  # type: ignore[union-attr]
    events = sim.snapshot("events")
    assert events[0]["code"] == "ANCHOR"
    assert sim.snapshot("status")["running"] is True
    assert sim.snapshot("unknown") is None


def test_loop_runs_pauses_and_survives_invariant_failures() -> None:
    async def scenario() -> tuple[int, bool, str]:
        sim = _sim()
        sim.tick_seconds = 0.005
        sub = sim.bus.subscribe()
        sub.topics.update({"us.tick", "events"})
        sim.start()
        await asyncio.sleep(0.1)
        ticks = sub.queue.qsize()

        def broken() -> None:
            raise AssertionError("EFFR outside the range")

        assert sim.us is not None
        sim.us.check_invariants = broken  # type: ignore[method-assign]
        await asyncio.sleep(0.05)
        await sim.stop()
        warning = next(e for e in sim.events.recent() if e.code == "INVARIANT")
        return ticks, sim.paused, warning.text

    ticks, paused, warning = asyncio.run(scenario())
    assert ticks >= 5
    assert paused
    assert "EFFR outside the range" in warning


def test_slow_subscribers_lose_old_messages_not_the_simulator() -> None:
    sim = _sim()
    sub = sim.bus.subscribe()
    sub.topics.add("us.tick")
    for _ in range(300):
        sim.tick(0.25)
    assert sub.queue.qsize() == 256
    assert sub.dropped == 44
