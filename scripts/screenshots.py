"""Capture terminal screenshots into docs/screenshots, driving a headless Chrome.

    py tasks.py screenshots

Starts the backend offline on the real seed (port 8077) and the Vite dev server (port 5177,
proxying to it), opens the terminal in the Chrome already installed on this machine (headless,
over the DevTools protocol; nothing is downloaded), types the demo's commands into the
command bar and saves a PNG after each step.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from websockets.sync.client import ClientConnection, connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
BACKEND_PORT, FRONTEND_PORT, DEVTOOLS_PORT = 8077, 5177, 9333
WIDTH, HEIGHT = 1680, 1050
CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path("/usr/bin/google-chrome"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
)


def wait_for(url: str, seconds: float = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):  # noqa: S310 - a local URL we started
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"{url} did not come up")


@contextmanager
def process(args: list[str], env: dict[str, str], cwd: Path) -> Iterator[subprocess.Popen[bytes]]:
    proc = subprocess.Popen(
        args, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        yield proc
    finally:
        if sys.platform == "win32":  # npm and uvicorn spawn children: end the whole tree
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
            )
        else:
            proc.terminate()
        proc.wait(timeout=30)


class DevTools:
    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self.next_id = 0

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                result: dict[str, Any] = message.get("result", {})
                return result

    def type_command(self, text: str) -> None:
        self.call(
            "Runtime.evaluate",
            expression="document.querySelector('input[aria-label=command]').focus()",
        )
        self.call("Input.insertText", text=text)
        for kind in ("keyDown", "keyUp"):
            self.call(
                "Input.dispatchKeyEvent",
                type=kind,
                key="Enter",
                code="Enter",
                windowsVirtualKeyCode=13,
                nativeVirtualKeyCode=13,
            )

    def focus(self, slot: int) -> None:
        """Alt+N: the next command's panel opens in slot N."""
        for kind in ("keyDown", "keyUp"):
            self.call(
                "Input.dispatchKeyEvent",
                type=kind,
                modifiers=1,  # Alt
                key=str(slot),
                code=f"Digit{slot}",
                windowsVirtualKeyCode=48 + slot,
                nativeVirtualKeyCode=48 + slot,
            )

    def shoot(self, name: str) -> Path:
        data = self.call("Page.captureScreenshot", format="png")["data"]
        path = OUT / f"{name}.png"
        path.write_bytes(base64.b64decode(data))
        print(f"wrote {path.relative_to(ROOT)}")
        return path


STEPS: list[tuple[str, list[str], float]] = [
    ("mvp-1-startup", [], 8.0),
    ("mvp-2-us-shock", ["HIKE 25BP", "QT 95B", "SHOCK JP 200B 10D LONG"], 4.0),
    ("mvp-3-india", ["SPEED 30X", "REPO -25BP", "VRR 50000CR 7D", "CRR 3.5"], 12.0),
    ("mvp-4-teach", ["TEACH"], 2.0),
    # "@N" focuses slot N: the G-sec curve after the cut above, and the spread to Treasuries.
    ("gsec-1-curve", ["TEACH", "@1", "GSEC", "@2", "SPRD"], 6.0),
    # The predictor's first fit runs its backtest: give it time.
    ("mpc-1-forecast", ["@3", "MPC"], 25.0),
]


def main() -> int:
    chrome = next((p for p in CHROME_PATHS if p.exists()), None)
    if chrome is None:
        print("no Chrome or Edge found; install one to take screenshots", file=sys.stderr)
        return 2
    npm = shutil.which("npm")
    if npm is None:
        print("npm not found", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "SD_OFFLINE": "true",
            "SD_SCHEDULER_ENABLED": "false",
            "SD_DATABASE_URL": f"sqlite:///{(Path(tmp) / 'shots.db').as_posix()}",
            "SD_DATA_DIR": str(ROOT / "data"),
            "SD_SIM_SEED": "7",
            "SD_BACKEND_URL": f"http://127.0.0.1:{BACKEND_PORT}",
        }
        backend = [
            sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
            "--host", "127.0.0.1", "--port", str(BACKEND_PORT),
        ]  # fmt: skip
        frontend = [
            npm,
            "run",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(FRONTEND_PORT),
            "--strictPort",
        ]
        browser = [
            str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
            f"--remote-debugging-port={DEVTOOLS_PORT}", f"--user-data-dir={Path(tmp) / 'chrome'}",
            f"--window-size={WIDTH},{HEIGHT}", "about:blank",
        ]  # fmt: skip
        with (
            process(backend, env, ROOT / "backend"),
            process(frontend, env, ROOT / "frontend"),
            process(browser, env, ROOT),
        ):
            wait_for(f"http://127.0.0.1:{BACKEND_PORT}/api/health")
            wait_for(f"http://127.0.0.1:{FRONTEND_PORT}/")
            wait_for(f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version")
            with urllib.request.urlopen(f"http://127.0.0.1:{DEVTOOLS_PORT}/json/list") as r:
                page = next(t for t in json.load(r) if t["type"] == "page")
            with connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
                tools = DevTools(ws)
                tools.call("Page.enable")
                tools.call(
                    "Emulation.setDeviceMetricsOverride",
                    width=WIDTH,
                    height=HEIGHT,
                    deviceScaleFactor=1,
                    mobile=False,
                )
                tools.call("Page.navigate", url=f"http://127.0.0.1:{FRONTEND_PORT}/")
                for name, commands, settle in STEPS:
                    for text in commands:
                        if text.startswith("@"):
                            tools.focus(int(text[1:]))
                        else:
                            tools.type_command(text)
                        time.sleep(0.6)
                    time.sleep(settle)
                    tools.shoot(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
