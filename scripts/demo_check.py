"""End-to-end check of the terminal demo on the real seed: every beat answers and narrates.

    py tasks.py demo

Boots the whole app offline against data/seed (no network) in a throwaway database, connects
to /ws the way the terminal does, and walks the demo: the four startup panels, a Fed hike,
QT, a Japanese sale, then India: the G-sec curve, a repo cut (which moves it), a CRR change, a
reverse repo and the spread to Treasuries, run forward at a simulated day per second. Each beat
must succeed with its narrative in the event log, and the live ticks must keep EFFR inside the
Fed's range and WACR inside its band (RBI's corridor in policy mode; in realistic mode, the
default, as far outside it as WACR has printed).
"""

import io
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.config import REPO_ROOT, Settings
from app.main import create_app


@dataclass
class Beat:
    command: str
    panel: str | None = None
    narrates: str | None = None
    """Event code that must appear in the log after the command."""
    check: str = ""
    passed: bool = False
    detail: str = ""


@dataclass
class Session:
    ws: WebSocketTestSession
    us: dict[str, Any] = field(default_factory=dict)
    india: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def take(self, message: dict[str, Any]) -> None:
        topic, data = message["topic"], message["data"]
        if topic == "us.tick" and data:
            self.us = data
            c = data["corridor"]
            if not c["lower"] <= data["effr"] <= c["upper"]:
                self.violations.append(f"EFFR {data['effr']} outside {c['lower']}-{c['upper']}")
        elif topic == "in.tick" and data:
            self.india = data
            # Realistic mode (the default) lets WACR leave RBI's corridor, but only within the
            # band of what it has printed since April 2022; policy mode's band is the corridor.
            b = data["band"]
            if not b["lower"] - 1e-12 <= data["wacr"] <= b["upper"] + 1e-12:
                self.violations.append(f"WACR {data['wacr']} outside {b['lower']}-{b['upper']}")
        elif topic == "events":
            self.events.extend(data if isinstance(data, list) else [data])

    def command(self, text: str) -> dict[str, Any]:
        self.ws.send_text(json.dumps({"op": "command", "text": text}))
        for _ in range(500):
            message = json.loads(self.ws.receive_text())
            if message["topic"] == "command":
                reply: dict[str, Any] = message["data"]
                return reply
            self.take(message)
        raise TimeoutError(f"no reply to {text}")

    def drain(self, seconds: float) -> None:
        """Keep reading ticks and events for a while (the market runs meanwhile)."""
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.take(json.loads(self.ws.receive_text()))


BEATS = [
    Beat("PY 10Y", "PY", check="modified duration above 7 years"),
    Beat("FED", "FED", check="the reserve-demand fit is in the panel"),
    Beat("WACR", "WACR", check="the macro map is fitted on years of RBI releases"),
    Beat("UST", "UST", check="official close attached"),
    Beat("HIKE 25BP", "FED", "HIKE", "the target range moves 25 bp"),
    Beat("QT 95B", "FED", "QT", "a 24-month reserves path"),
    Beat("SHOCK JP 200B 10D LONG", "UST", "SHOCK", "long-run 10Y effect is positive"),
    Beat("GSEC", "GSEC", check="the event study on RBI's repo changes and a live NSS fit"),
    Beat("REPO -25BP", "WACR", "REPO", "the corridor and the G-sec curve move down"),
    Beat("CRR 3.5", "LAF", "CRR", "a drain from the next fortnight"),
    Beat("VRRR 50000CR 1D", "LAF", None, "queued for the next window"),
    Beat("SPRD", "SPRD", check="India 10Y against US 10Y since 2023, and now"),
    Beat("SPEED 1440X", None, None, "a simulated day per second"),
]


class DemoError(Exception):
    """A beat did not do what the demo needs."""


def expect(condition: bool, detail: object) -> None:
    if not condition:
        raise DemoError(str(detail))


def verify(beat: Beat, reply: dict[str, Any]) -> str:
    data = reply.get("data") or {}
    message = reply["message"]
    match beat.command.split()[0]:
        case "PY":
            expect(data["modified"] > 7, data["modified"])
        case "FED":
            expect(data["reserve_curve"]["width"] > 0, data["reserve_curve"])
        case "WACR":
            expect(data["map"]["points"] > 500, data["map"]["points"])
        case "UST":
            expect(set(data["official_close"]) >= {"2Y", "10Y", "30Y"}, data["official_close"])
        case "HIKE":
            expect("FOMC hike +25 bp" in message, message)
        case "QT":
            expect(len(data["reserves"]) == 24, len(data["reserves"]))
        case "SHOCK":
            expect(data["long_run"]["10Y"] > 0, data["long_run"])
        case "GSEC":
            expect(len(data["passthrough"]["events"]) >= 11, data["passthrough"]["events"])
            expect(data["now"]["rmse_bp"] < 6, data["now"]["rmse_bp"])
        case "REPO":
            expect("MPC cut" in message and "G-secs 2Y" in message, message)
        case "SPRD":
            expect(len(data["real"]) > 500, len(data["real"]))
            expect(data["now"]["spread"] is not None, data["now"])
        case "CRR":
            expect("fortnight beginning" in message, message)
        case "VRRR":
            expect("runs_at" in data, data)
    return str(message)


def main() -> int:
    # Narratives carry ₹, and Windows consoles default to cp1252.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as tmp:
        # No .env (the FRED key is not needed offline) and a throwaway database.
        overrides: dict[str, Any] = {
            "_env_file": None,
            "env": "test",
            "fred_api_key": None,
            "database_url": f"sqlite:///{(Path(tmp) / 'demo.db').as_posix()}",
            "data_dir": REPO_ROOT / "data",
            "scheduler_enabled": False,
            "offline": True,
            "sim_seed": 7,
        }
        settings = Settings(**overrides)
        with TestClient(create_app(settings)) as client:
            status = client.get("/api/sim/status").json()
            if not status["running"] or not status["india"]["running"]:
                print(f"simulator not running: {status['error']} / {status['india']['error']}")
                return 1
            with client.websocket_connect("/ws") as ws:
                s = Session(ws)
                ws.send_text(
                    json.dumps({"op": "subscribe", "topics": ["events", "us.tick", "in.tick"]})
                )
                for beat in BEATS:
                    reply = s.command(beat.command)
                    try:
                        if not reply["ok"]:
                            raise DemoError(reply["message"])
                        if beat.panel is not None and reply["panel"] != beat.panel:
                            raise DemoError(f"panel {reply['panel']}, expected {beat.panel}")
                        beat.detail = verify(beat, reply)
                        beat.passed = True
                    except (DemoError, KeyError, TypeError) as exc:
                        beat.detail = f"FAILED: {exc}"
                s.drain(4.0)  # four simulated days: the reverse repo runs, tax days may pass
                codes = {e.get("code") for e in s.events}
                for beat in BEATS:
                    if beat.passed and beat.narrates and beat.narrates not in codes:
                        beat.passed, beat.detail = False, f"no {beat.narrates} event in the log"
                ordered = any(
                    e.get("code") == "VRRR" and e.get("text", "").startswith("You ordered")
                    for e in s.events
                )
                end = s.command("CALL")
                reset = s.command("RESET")
    width = max(len(b.command) for b in BEATS)
    for beat in BEATS:
        mark = "ok " if beat.passed else "BAD"
        print(f"[{mark}] {beat.command:<{width}}  {beat.check}: {beat.detail[:110]}")
    checks = {
        "the ordered VRRR ran and was narrated": ordered,
        "CALL answers after four simulated days": bool(end["ok"]),
        "RESET restores the anchors": bool(reset["ok"]),
        "EFFR in the Fed's range and WACR in its band on every tick": not s.violations,
    }
    for name, ok in checks.items():
        print(f"[{'ok ' if ok else 'BAD'}] {name}")
    for violation in s.violations[:5]:
        print(f"      {violation}")
    passed = all(b.passed for b in BEATS) and all(checks.values())
    print("demo check passed" if passed else "demo check FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
