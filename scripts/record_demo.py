"""Record the static demo: the real simulator on the seed, its replies and ticks, for the web.

    py tasks.py record-demo

Boots the whole app offline against data/seed, as `demo_check.py` does, starts a run at a fixed
morning in Mumbai with seed 7, and records over the WebSocket:

* the opening ticks (a three-minute tape at one frame a second) and the event history;
* every view the terminal offers, from that opening state;
* each command that moves the markets, from a fresh RESET: its reply and narrative, a tape of
  the ticks after it, and the panels it changes, as they then read.

The static build of the terminal (``npm run build:demo``, published on GitHub Pages) plays these
back in the browser: nothing in the files is made up, but nothing is computed live either, and
the page says so.
"""

import io
import json
import math
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.config import REPO_ROOT, Settings
from app.main import create_app

OUT = REPO_ROOT / "frontend" / "demo" / "public"
START = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)  # Tuesday 09:30 in Mumbai, 00:00 in New York
SEED = 7
BASELINE_SECONDS = 180
TAPE_SECONDS = 12
FRAME_SECONDS = 1.0

CODES = (
    "PY", "UST", "FED", "HIKE", "CUT", "QT", "DEBT", "TIC", "SHOCK", "CORR", "CALL", "WACR", "LAF",
    "NDTL", "CRR", "REPO", "VRR", "VRRR", "TAXCAL", "CCIL", "GSEC", "SPRD", "MPC", "LINK",
    "IMPACT", "REPLAY", "HELP", "TEACH", "SPEED", "PAUSE", "RESUME", "RESET", "LAYOUT", "SAVE",
    "LOAD", "EXPORT",
)  # fmt: skip
VIEWS = [
    "PY 10Y", "PY 2Y", "PY 5Y", "PY 30Y", "FED", "WACR", "UST", "DEBT", "TIC", "CORR", "CALL",
    "LAF", "NDTL", "TAXCAL", "CCIL", "GSEC", "SPRD", "MPC", "LINK", "LINK VRR", "LINK OMO",
    "LINK SWAP", "LINK HIKE", "IMPACT", "IMPACT RETAIL", "IMPACT RETAIL +100BP",
    "IMPACT RETAIL +200BP", "IMPACT RETAIL -100BP", "IMPACT BUSINESS", "IMPACT BUSINESS SHOP",
    "IMPACT BUSINESS IMPORTER", "IMPACT BUSINESS +25BP INR+5",
    "IMPACT BUSINESS IMPORTER +25BP INR+5",
    "REPLAY", "REPLAY TAPER2013", "REPLAY DASH2020", "REPLAY GILT2022", "REPLAY HIKE2022",
    "REPLAY ADVTAX", "HELP", "TEACH", *(f"HELP {code}" for code in CODES),
]  # fmt: skip
# Each command that moves the markets, with the panels whose replies it changes.
ACTIONS: dict[str, list[str]] = {
    "QT 95B": ["FED", "UST", "DEBT"],
    "QT OFF": ["FED"],
    "HIKE 25BP": ["FED", "UST", "DEBT", "PY 10Y", "CORR"],
    "HIKE 50BP": ["FED", "UST", "DEBT", "PY 10Y", "CORR"],
    "CUT 25BP": ["FED", "UST", "DEBT", "PY 10Y", "CORR"],
    "CUT 50BP": ["FED", "UST", "DEBT", "PY 10Y", "CORR"],
    "SHOCK JP 200B 10D LONG": ["UST", "TIC", "DEBT", "PY 10Y"],
    "SHOCK JP 200B": ["UST", "TIC", "DEBT", "PY 10Y"],
    "SHOCK CN 100B 5D": ["UST", "TIC", "DEBT", "PY 10Y"],
    "SHOCK FED 50BP": ["LINK", "FED", "UST", "WACR", "CALL", "LAF", "SPRD", "CORR"],
    "SHOCK FED 50BP VRR": ["LINK", "FED", "WACR", "LAF"],
    "SHOCK FED 50BP OMO": ["LINK", "FED", "WACR", "LAF"],
    "SHOCK FED 50BP SWAP": ["LINK", "FED", "WACR", "LAF"],
    "SHOCK FED 50BP HIKE": ["LINK", "FED", "WACR", "LAF", "GSEC"],
    "REPO +25BP": ["WACR", "GSEC", "CALL", "LAF", "CORR", "SPRD", "MPC"],
    "REPO -25BP": ["WACR", "GSEC", "CALL", "LAF", "CORR", "SPRD", "MPC"],
    "CRR 3.5": ["LAF", "NDTL", "WACR"],
    "CRR 2.5": ["LAF", "NDTL", "WACR"],
    "VRR 50000CR 7D": ["LAF", "WACR", "CALL"],
    "VRRR 50000CR 7D": ["LAF", "WACR", "CALL"],
    "WACR POLICY": ["WACR", "CALL"],
}


class Recorder:
    def __init__(self, ws: WebSocketTestSession) -> None:
        self.ws = ws
        self.us: dict[str, Any] | None = None
        self.india: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []

    def _take(self, message: dict[str, Any]) -> dict[str, Any] | None:
        topic, data = message["topic"], message["data"]
        if topic == "us.tick" and data:
            self.us = data
        elif topic == "in.tick" and data:
            self.india = data
        elif topic == "events":
            self.events.extend(data if isinstance(data, list) else [data])
        elif topic == "command":
            reply: dict[str, Any] = data
            return reply
        return None

    def command(self, text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        before = len(self.events)
        self.ws.send_text(json.dumps({"op": "command", "text": text}))
        for _ in range(5000):
            reply = self._take(json.loads(self.ws.receive_text()))
            if reply is not None:
                return reply, self.events[before:]
        raise TimeoutError(f"no reply to {text}")

    def tape(self, seconds: float) -> list[dict[str, Any]]:
        """Frames of both markets, from the first ticks after this call (not older ones)."""
        self.us = self.india = None
        frames: list[dict[str, Any]] = []
        until = time.monotonic() + seconds
        next_frame = time.monotonic()
        while time.monotonic() < until:
            self._take(json.loads(self.ws.receive_text()))
            if time.monotonic() >= next_frame and self.us and self.india:
                frames.append({"us": self.us, "india": self.india})
                next_frame += FRAME_SECONDS
        return frames


def _ok(reply: dict[str, Any]) -> dict[str, Any]:
    keep = ("ok", "code", "message", "panel", "data", "narrated", "sim_time", "command")
    return {k: reply.get(k) for k in keep}


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as tmp:
        overrides: dict[str, Any] = {
            "_env_file": None,
            "env": "test",
            "fred_api_key": None,
            "database_url": f"sqlite:///{(Path(tmp) / 'record.db').as_posix()}",
            "data_dir": REPO_ROOT / "data",
            "scheduler_enabled": False,
            "offline": True,
            "sim_seed": SEED,
        }
        app = create_app(Settings(**overrides))
        with TestClient(app) as client:
            sim = app.state.sim
            sim.clock = lambda: START  # every RESET starts the run at the same morning
            with client.websocket_connect("/ws") as ws:
                rec = Recorder(ws)
                ws.send_text(
                    json.dumps({"op": "subscribe", "topics": ["events", "us.tick", "in.tick"]})
                )
                rec.command("RESET")
                rec.events = []
                print("recording the opening tape …", flush=True)
                baseline = rec.tape(BASELINE_SECONDS)
                history = list(rec.events)
                status = client.get("/api/sim/status").json()
                health = client.get("/api/health").json()
                commands = client.get("/api/commands").json()
                replies: dict[str, Any] = {}
                for text in VIEWS:
                    reply, events = rec.command(text)
                    if reply["ok"]:
                        replies[text] = {"reply": _ok(reply), "events": events}
                    else:
                        print(f"  skipped {text}: {reply['message']}")
                print(f"{len(replies)} views recorded", flush=True)
                actions: dict[str, Any] = {}
                for text, panels in ACTIONS.items():
                    rec.command("RESET")
                    reply, events = rec.command(text)
                    if not reply["ok"]:
                        print(f"  skipped {text}: {reply['message']}")
                        continue
                    tape = rec.tape(TAPE_SECONDS)
                    after = {}
                    for view in panels:
                        shown, _ = rec.command(view)
                        if shown["ok"]:
                            after[view] = _ok(shown)
                    actions[text] = {
                        "reply": _ok(reply),
                        "events": events,
                        "tape": tape,
                        "after": after,
                    }
                    print(f"  {text}: {len(tape)} frames, {len(after)} panels", flush=True)
                reset, reset_events = rec.command("RESET")
    session = {
        "recorded": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": SEED,
        "start": START.isoformat(),
        "history": history,
        "baseline": baseline,
        "replies": replies,
        "actions": actions,
        "reset": {"reply": _ok(reset), "events": reset_events},
    }
    write_demo(session, status=status, health=health, commands=commands)
    return 0


def _compact(value: Any) -> Any:
    """Floats to 7 significant digits: more than any panel shows, and a third of the size."""
    if isinstance(value, float):
        return float(f"{value:.7g}") if math.isfinite(value) else value
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def write_demo(session: dict[str, Any], **extra: Any) -> None:
    """The recording as the web demo reads it: the session split into files under 1 MB."""
    session = _compact(session)
    actions = session.pop("actions")
    files = {
        "session.json": {k: v for k, v in session.items() if k != "baseline"},
        "baseline.json": session["baseline"],
        "tapes.json": {text: a.pop("tape") for text, a in actions.items()},
        "actions.json": actions,
        **{f"{name}.json": payload for name, payload in extra.items()},
    }
    demo = OUT / "demo"
    if demo.exists():
        shutil.rmtree(demo)
    demo.mkdir(parents=True)
    for name, payload in files.items():
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        (demo / name).write_text(text + "\n", encoding="utf-8", newline="\n")
    shutil.copy(REPO_ROOT / "frontend" / "public" / "favicon.svg", OUT / "favicon.svg")
    sizes = {p.name: p.stat().st_size for p in demo.iterdir()}
    print(
        f"wrote {demo.relative_to(REPO_ROOT)}: "
        + ", ".join(f"{n} {s / 1e3:.0f} kB" for n, s in sizes.items())
    )
    if max(sizes.values()) > 1_000_000:
        raise SystemExit("a demo file is over 1 MB: shorten the tapes or split it further")


if __name__ == "__main__":
    sys.exit(main())
