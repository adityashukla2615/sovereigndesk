"""End to end on the real committed seed: anchors, live ticks over the socket, commands, REST.

Boots the whole app offline against ``data/seed`` (the same snapshot the Docker image ships),
so it also checks that the real data is complete enough to run the simulator.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.config import REPO_ROOT, Settings
from app.main import create_app


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    db: Path = tmp_path_factory.mktemp("live") / "live.db"
    settings = Settings(
        _env_file=None,
        env="test",
        fred_api_key=None,
        database_url=f"sqlite:///{db.as_posix()}",
        data_dir=REPO_ROOT / "data",
        scheduler_enabled=False,
        offline=True,
        sim_seed=5,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def _until(ws: WebSocketTestSession, topic: str, limit: int = 50) -> dict[str, Any]:
    for _ in range(limit):
        message: dict[str, Any] = json.loads(ws.receive_text())
        if message["topic"] == topic:
            return message
    raise AssertionError(f"no {topic} message within {limit} messages")


def test_simulator_anchors_to_the_real_seed(live: TestClient) -> None:
    status = live.get("/api/sim/status").json()
    assert status["running"] is True, status["error"]
    assert status["input_quality"] != ["LIVE"]  # offline: inputs come from the seed snapshot
    ten = live.get("/api/data/series/ust/par/10Y").json()
    anchored = status["anchored_as_of"]
    assert anchored == ten["dates"][-1]


def test_ticks_stream_after_the_snapshot(live: TestClient) -> None:
    ten_year = live.get("/api/data/series/ust/par/10Y").json()["values"][-1] / 100
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "subscribe", "topics": ["us.tick"]}))
        first = _until(ws, "us.tick")
        second = _until(ws, "us.tick")
    assert first["data"]["curve"]["10Y"] == pytest.approx(ten_year, abs=0.01)
    assert second["seq"] > first["seq"]
    assert second["data"]["sim_time"] > first["data"]["sim_time"]
    corridor = second["data"]["corridor"]
    assert corridor["lower"] <= second["data"]["effr"] <= corridor["upper"]


def test_commands_answer_and_narrate(live: TestClient) -> None:
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "subscribe", "topics": ["events"]}))
        _until(ws, "events")  # the snapshot: recent events
        ws.send_text(json.dumps({"op": "command", "text": "SHOCK JP 100B 5D LONG"}))
        reply = _until(ws, "command")
        event = _until(ws, "events")
    assert reply["data"]["ok"] is True, reply["data"]["message"]
    assert event["data"]["code"] == "SHOCK"
    assert "Japan sells $100bn" in event["data"]["text"]
    ws_reset = live.websocket_connect("/ws")
    with ws_reset as ws:
        ws.send_text(json.dumps({"op": "command", "text": "RESET"}))
        assert _until(ws, "command")["data"]["ok"] is True


def test_command_catalogue_endpoint(live: TestClient) -> None:
    commands = {c["code"]: c for c in live.get("/api/commands").json()}
    assert commands["PY"]["available"] is True
    assert commands["MPC"]["available"] is False
    assert "Phase 8" in commands["MPC"]["available_in"]


def test_india_anchors_to_the_real_seed_and_streams(live: TestClient) -> None:
    status = live.get("/api/sim/status").json()["india"]
    assert status["running"] is True, status["error"]
    assert status["input_quality"] != ["LIVE"]
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "subscribe", "topics": ["in.tick"]}))
        tick = _until(ws, "in.tick")["data"]
        ws.send_text(json.dumps({"op": "command", "text": "WACR"}))
        reply = _until(ws, "command")["data"]
    c = tick["corridor"]
    assert c["sdf"] < c["repo"] < c["msf"]
    assert c["sdf"] <= tick["map_rate"] <= c["msf"]
    assert tick["ndtl"] > 1e7  # ₹ crore: above ₹100 lakh crore
    assert reply["ok"] is True, reply["message"]
    assert reply["data"]["map"]["points"] > 500  # fitted on years of RBI releases


def test_gsec_curve_anchors_to_fbil_and_rbi(live: TestClient) -> None:
    """The real seed: FBIL's par yields, the event study on RBI's repo changes, the spread."""
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "subscribe", "topics": ["in.tick"]}))
        tick = _until(ws, "in.tick")["data"]["gsec"]
        ws.send_text(json.dumps({"op": "command", "text": "GSEC"}))
        gsec = _until(ws, "command")["data"]
        ws.send_text(json.dumps({"op": "command", "text": "SPRD"}))
        sprd = _until(ws, "command")["data"]
    assert gsec["ok"] is True, gsec["message"]
    assert tick["rmse_bp"] < 6
    points = tick["points"]
    assert 0.03 < points["3M"] < points["10Y"] < 0.12
    pt = gsec["data"]["passthrough"]
    assert len(pt["events"]) >= 11  # every repo change since 8 Apr 2022
    beta = {round(r["years"], 2): r["beta"] for r in pt["curve"]}
    assert abs(beta[0.25] - 1) < 1e-9
    assert beta[0.25] > beta[2.0] > beta[10.0] > 0  # the short end moves most
    assert all(e["day_beta"] < 0.5 for e in pt["estimates"])  # most changes were expected
    assert sprd["ok"] is True, sprd["message"]
    real = sprd["data"]["real"]
    assert len(real) > 500  # daily since February 2023
    assert all(0 < r["india"] - r["us"] < 0.06 for r in real)
