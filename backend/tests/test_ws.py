"""WebSocket protocol behaviour; the simulator here has no data, so markets are unavailable."""

import json
from typing import Any

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession


def _recv(ws: WebSocketTestSession) -> dict[str, Any]:
    message: dict[str, Any] = json.loads(ws.receive_text())
    assert set(message) == {"topic", "ts", "seq", "data"}
    return message


def test_greets_with_status_and_answers_commands(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        hello = _recv(ws)
        assert hello["topic"] == "status"
        assert hello["seq"] == 1
        assert hello["data"]["server"] == "sovereigndesk"
        assert hello["data"]["sim"]["running"] is False  # empty seed in this fixture

        ws.send_text(json.dumps({"op": "command", "text": "QT 95B"}))
        reply = _recv(ws)
        assert (reply["topic"], reply["seq"]) == ("command", 2)
        assert reply["data"]["ok"] is False
        assert "not running" in reply["data"]["message"]

        ws.send_text(json.dumps({"op": "command", "text": "HELP"}))
        help_reply = _recv(ws)
        assert help_reply["data"]["ok"] is True
        assert any(c["code"] == "SHOCK" for c in help_reply["data"]["data"]["commands"])


def test_subscribe_ack_snapshot_and_ping(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        _recv(ws)
        ws.send_text(json.dumps({"op": "subscribe", "topics": ["us.tick", "status"]}))
        ack = _recv(ws)
        assert ack["topic"] == "status"
        assert ack["data"] == {"subscribed": ["status", "us.tick"]}
        snapshot = _recv(ws)  # no market, so us.tick has no snapshot; status does
        assert snapshot["topic"] == "status"
        assert snapshot["data"]["running"] is False

        ws.send_text(json.dumps({"op": "ping"}))
        assert _recv(ws)["topic"] == "pong"


def test_invalid_messages_get_an_error_and_keep_the_socket_open(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        _recv(ws)
        for bad in ("not json", '{"op": "launch"}', '{"op": "command", "text": ""}'):
            ws.send_text(bad)
            error = _recv(ws)
            assert error["topic"] == "error"
            assert error["data"]["reason"] == "invalid message"

        ws.send_text(json.dumps({"op": "ping"}))
        pong = _recv(ws)
        assert pong["topic"] == "pong"
        assert pong["seq"] == 5
