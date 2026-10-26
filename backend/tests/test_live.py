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
    assert commands["MPC"]["available"] is True
    assert commands["LINK"]["available"] is True
    assert commands["IMPACT"]["available"] is True
    assert commands["REPLAY"]["available"] is True
    assert commands["CCIL"]["available"] is True
    assert commands["SAVE"]["available"] is False
    assert "Phase 13" in commands["SAVE"]["available_in"]


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


def test_mpc_predictor_fits_on_rbi_mospi_and_fred(live: TestClient) -> None:
    """The real seed: every repo decision since 2014, MoSPI's CPI and GDP, RBI's money markets."""
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "command", "text": "MPC"}))
        reply = _until(ws, "command", limit=200)["data"]
    assert reply["ok"] is True, reply["message"]
    panel = reply["data"]
    assert panel["sample"]["first"].startswith("2014")
    assert panel["sample"]["decisions"] >= 70
    assert panel["sample"]["off_cycle"] >= 4  # Jan and Mar 2015, Mar and May 2020, May 2022
    assert panel["backtest"]["forecasts"] >= 45
    assert panel["next_meeting"] is not None
    for probabilities in panel["probabilities"].values():
        assert abs(sum(probabilities) - 1) < 1e-9
    missing = [f["key"] for f in panel["features"] if f["last"] is None]
    assert not missing, missing  # every feature known at the last decision
    weights = {w["base"]: w for w in panel["core_weights"]}
    # MoSPI's published 2012 weights: food and beverages 45.86, fuel and light 6.84.
    assert abs(weights["2012"]["excluded"]["food_beverages"] - 0.4586) < 0.01
    assert abs(weights["2012"]["excluded"]["fuel_light"] - 0.0684) < 0.01


def test_linkage_calibrates_and_runs_a_fed_shock(live: TestClient) -> None:
    """The real seed: NSDL's flows, RBI's reserves and FRED's rates calibrate every link, and a
    50 bp Fed hike runs through to India's money market in plausible sizes."""
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "command", "text": "LINK"}))
        preview = _until(ws, "command", limit=200)["data"]
        assert preview["ok"] is True, preview["message"]
        ws.send_text(json.dumps({"op": "command", "text": "SHOCK FED 50BP"}))
        shock = _until(ws, "command", limit=200)["data"]
        ws.send_text(json.dumps({"op": "command", "text": "RESET"}))
        assert _until(ws, "command", limit=200)["data"]["ok"] is True
    assert shock["ok"] is True, shock["message"]
    estimates = {e["key"]: e for e in preview["data"]["estimates"]}
    assert 0 < estimates["spillover"]["used"] < 1
    assert estimates["spillover"]["n"] >= 150  # weeks of FBIL's daily coverage
    assert 0 <= estimates["intervention"]["used"] <= 1
    assert estimates["intervention"]["n"] >= 600  # weeks since 2014
    assert estimates["debt_flow"]["n"] >= 140  # months since 2014
    assert estimates["equity_flow"]["used"] < 0  # a rising US 10Y takes equity money out
    assert estimates["risk_flow"]["used"] < 0  # and so does a rising VIX
    nodes = {n["key"]: n["value"] for n in shock["data"]["nodes"]}
    assert 0 < nodes["us10y"] < 50
    assert -5 < nodes["fpi"] < 0  # US$ bn over a month
    assert 0 < nodes["inr"] < 1  # per cent weaker
    assert -50_000 < nodes["liquidity"] < 0  # ₹ crore drained
    assert 0 <= nodes["wacr"] < 10  # bp
    anchors = shock["data"]["anchors"]
    assert 50 < anchors["inr"] < 150
    assert 300 < anchors["reserves_bn"] < 1500


def test_impact_on_the_real_seed(live: TestClient) -> None:
    """Module E: the MCLR's pass-through fitted on RBI's monthly lending-rate releases, and both
    views for a hypothetical move."""
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "command", "text": "IMPACT RETAIL +100BP"}))
        retail = _until(ws, "command", limit=200)["data"]
        ws.send_text(json.dumps({"op": "command", "text": "IMPACT BUSINESS +25BP INR+5"}))
        business = _until(ws, "command", limit=200)["data"]
    assert retail["ok"] is True, retail["message"]
    assert business["ok"] is True, business["message"]
    pt = retail["data"]["passthrough"]
    assert 0.2 < pt["mclr_per_repo"] < 1.2  # RBI's own figure for 2022-23: 152 of 250 bp
    assert 0.25 < pt["mclr_months"] < 36
    assert pt["mclr_fit"]["n"] >= 40  # months since June 2022
    assert 0.05 < pt["mclr_now"] < 0.15
    totals = retail["data"]["retail"]["totals"]
    assert -10 < totals["change_pct"] < 0
    rows = {b["key"]: b for b in business["data"]["business"]}
    assert rows["SHOP"]["loan_rate_bp"][0] == pytest.approx(25.0)
    assert rows["IMPORTER"]["summary"]["margin"] < 0


def test_every_replay_runs_on_the_real_data(live: TestClient) -> None:
    """Module D: each committed episode replays through the running app, with scores."""
    with live.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"op": "command", "text": "REPLAY"}))
        listing = _until(ws, "command", limit=200)["data"]
        assert listing["ok"] is True, listing["message"]
        replies = {}
        for episode in ("TAPER2013", "DASH2020", "HIKE2022", "GILT2022", "ADVTAX"):
            ws.send_text(json.dumps({"op": "command", "text": f"REPLAY {episode}"}))
            replies[episode] = _until(ws, "command", limit=200)["data"]
    for episode, reply in replies.items():
        assert reply["ok"] is True, (episode, reply["message"])
        for target in reply["data"]["targets"]:
            assert target["summary"], (episode, target["key"])
            for s in target["scores"].values():
                assert s["n"] > 10, (episode, target["key"])
    lam = replies["GILT2022"]["data"]["facts"]["lambda"]
    assert lam["low_bp"] < lam["lam_bp"] < lam["high_bp"]
    assert lam["n"] == 15  # three weeks of operations, the announcement day left out
