import json
from typing import Any

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession


def _recv(ws: WebSocketTestSession) -> dict[str, Any]:
    message: dict[str, Any] = json.loads(ws.receive_text())
    assert set(message) == {"topic", "ts", "seq", "data"}
    return message


def test_greets_then_echoes_commands(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        hello = _recv(ws)
        assert hello["topic"] == "status"
        assert hello["seq"] == 1
        assert hello["data"]["server"] == "sovereigndesk"

        ws.send_text(json.dumps({"op": "command", "text": "QT 95B"}))
        echo = _recv(ws)
        assert (echo["topic"], echo["seq"], echo["data"]) == ("echo", 2, {"text": "QT 95B"})


def test_subscribe_ack_and_ping(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        _recv(ws)
        ws.send_text(json.dumps({"op": "subscribe", "topics": ["us.tick", "events"]}))
        ack = _recv(ws)
        assert ack["topic"] == "status"
        assert ack["data"] == {"subscribed": ["events", "us.tick"]}

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
