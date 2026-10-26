#!/usr/bin/env python3
"""SovereignDesk task runner (stdlib only, so it works before anything is installed).

Run with `py tasks.py <task>` on Windows or `python3 tasks.py <task>` elsewhere; `make <task>`
delegates here.

tasks:
  setup          create .venv, install engine + backend (editable) + dev tools, npm ci, git hooks
  dev            backend on :8000 (auto-reload) and frontend on :5173; --offline boots from seed
  test           pytest (engine, backend) and vitest
  lint           ruff, ruff format --check, mypy (strict), eslint, tsc
  fmt            ruff format + ruff check --fix
  api            regenerate frontend/src/api/{openapi.json,schema.d.ts}; --check fails on drift
  build          production build of the frontend
  check          check-secrets, lint, api --check, test, build: everything CI's check job runs
  e2e            Playwright smoke test: backend on the seed + Vite, in the installed Chrome
  seed           snapshot real data into data/seed; --sources picks some
  demo           walk the terminal demo end to end on the real seed (scripts/demo_check.py)
  mpc-report     write docs/MPC_BACKTEST.md: the MPC predictor's backtest on the real seed
  replays        build data/replays: the episodes' series from the seed and the Bank of England
  screenshots    drive a headless Chrome through the demo into docs/screenshots
  check-secrets  scan files git would commit for secrets; --staged scans only the index
  clean          remove caches and build output
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
ENGINE = ROOT / "engine"
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
API_DIR = FRONTEND / "src" / "api"
IS_WINDOWS = os.name == "nt"
PY_INSTALL = ["-r", "requirements-dev.txt", "-e", "engine", "-e", "backend"]


class TaskError(Exception):
    pass


# --------------------------------------------------------------------------- helpers


def venv_python() -> Path:
    path = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    if not path.exists():
        raise TaskError("no .venv yet: run `tasks.py setup` first")
    return path


def npm() -> str:
    path = shutil.which("npm")
    if path is None:
        raise TaskError("npm not found on PATH (Node 22+ is required)")
    return path


def run(cmd: Sequence[str | Path], cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    args = [str(c) for c in cmd]
    where = cwd.relative_to(ROOT).as_posix() if cwd != ROOT else "."
    print(f"\n>> [{where}] {' '.join([Path(args[0]).name, *args[1:]])}", flush=True)
    if subprocess.run(args, cwd=cwd, env=env).returncode != 0:
        raise TaskError(f"command failed: {' '.join(args)}")


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


# --------------------------------------------------------------------------- tasks


def task_setup(args: argparse.Namespace) -> None:
    if not VENV.exists():
        run([sys.executable, "-m", "venv", VENV])
    python = venv_python()
    run([python, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run([python, "-m", "pip", "install", *PY_INSTALL])
    if not args.no_frontend:
        run([npm(), "ci" if (FRONTEND / "package-lock.json").exists() else "install"], cwd=FRONTEND)
    if not args.no_hooks and (ROOT / ".git").exists():
        run([python, "-m", "pre_commit", "install"])


def task_dev(args: argparse.Namespace) -> None:
    env = dict(os.environ)
    if args.offline:
        env["SD_OFFLINE"] = "true"
    backend = [
        str(venv_python()), "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", "8000",
        "--reload", "--reload-dir", "app", "--reload-dir", str(ENGINE / "src"),
    ]  # fmt: skip
    procs = {
        "backend": subprocess.Popen(backend, cwd=BACKEND, env=env),
        "frontend": subprocess.Popen([npm(), "run", "dev"], cwd=FRONTEND, env=env),
    }
    print("\nbackend  http://127.0.0.1:8000/docs")
    print("frontend http://localhost:5173\nCtrl+C stops both.")
    died: list[str] = []
    try:
        while not died:
            time.sleep(0.5)
            died = [name for name, p in procs.items() if p.poll() is not None]
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        for p in procs.values():
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    if died:
        raise TaskError(f"{', '.join(died)} exited on its own; the other was stopped")


def task_test(args: argparse.Namespace) -> None:
    if not args.js_only:
        python = venv_python()
        run([python, "-m", "pytest"], cwd=ENGINE)
        run([python, "-m", "pytest"], cwd=BACKEND)
    if not args.py_only:
        run([npm(), "run", "test"], cwd=FRONTEND)


def task_lint(_: argparse.Namespace) -> None:
    python = venv_python()
    run([python, "-m", "ruff", "check", "."])
    run([python, "-m", "ruff", "format", "--check", "."])
    run([python, "-m", "mypy"], cwd=ENGINE)
    run([python, "-m", "mypy"], cwd=BACKEND)
    run([python, "-m", "mypy", "--strict", "tasks.py", "scripts"])
    run([npm(), "run", "lint"], cwd=FRONTEND)
    run([npm(), "run", "typecheck"], cwd=FRONTEND)


def task_fmt(_: argparse.Namespace) -> None:
    python = venv_python()
    run([python, "-m", "ruff", "format", "."])
    run([python, "-m", "ruff", "check", "--fix", "."])


def _openapi_spec() -> str:
    code = "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))"
    result = subprocess.run(
        [str(venv_python()), "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        raise TaskError(f"could not build the OpenAPI schema:\n{result.stderr}")
    return result.stdout


def _write_api(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    spec = target / "openapi.json"
    spec.write_text(_openapi_spec(), encoding="utf-8", newline="\n")
    schema = target / "schema.d.ts"
    run([npm(), "exec", "--no", "--", "openapi-typescript", spec, "-o", schema], cwd=FRONTEND)


def task_api(args: argparse.Namespace) -> None:
    if not args.check:
        _write_api(API_DIR)
        return
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp)
        _write_api(fresh)
        stale = [
            name
            for name in ("openapi.json", "schema.d.ts")
            if not (API_DIR / name).exists()
            or (API_DIR / name).read_bytes() != (fresh / name).read_bytes()
        ]
    if stale:
        raise TaskError(f"generated API files are stale ({', '.join(stale)}): run `tasks.py api`")
    print("API types are up to date.")


def task_build(_: argparse.Namespace) -> None:
    run([npm(), "run", "build"], cwd=FRONTEND)


def task_check(args: argparse.Namespace) -> None:
    task_check_secrets(argparse.Namespace(staged=False))
    task_lint(args)
    task_api(argparse.Namespace(check=True))
    task_test(argparse.Namespace(py_only=False, js_only=False))
    task_build(args)
    print("\nAll checks passed.")


def task_e2e(_: argparse.Namespace) -> None:
    # The config starts the backend with this interpreter and the dev server; no browser is
    # downloaded (Playwright drives the system's Chrome, or Edge with SD_BROWSER_CHANNEL=msedge).
    env = {**os.environ, "SD_PYTHON": str(venv_python())}
    run([npm(), "exec", "--no", "--", "playwright", "test"], cwd=FRONTEND, env=env)


def task_seed(args: argparse.Namespace) -> None:
    script = ROOT / "scripts" / "build_seed.py"
    if not script.exists():
        raise TaskError("scripts/build_seed.py arrives in Phase 3 (US data)")
    run([venv_python(), script, *(["--sources", args.sources] if args.sources else [])])


def task_demo(_: argparse.Namespace) -> None:
    run([venv_python(), ROOT / "scripts" / "demo_check.py"])


def task_mpc_report(_: argparse.Namespace) -> None:
    run([venv_python(), ROOT / "scripts" / "mpc_report.py"])


def task_replays(args: argparse.Namespace) -> None:
    run([venv_python(), ROOT / "scripts" / "build_replays.py", *args.episodes])


def task_screenshots(_: argparse.Namespace) -> None:
    run([venv_python(), ROOT / "scripts" / "screenshots.py"])


def task_clean(_: argparse.Namespace) -> None:
    junk = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}
    for dirpath, dirnames, _files in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", ".venv", "node_modules"}]
        for d in [d for d in dirnames if d in junk]:
            shutil.rmtree(Path(dirpath) / d, ignore_errors=True)
            dirnames.remove(d)
    shutil.rmtree(FRONTEND / "dist", ignore_errors=True)
    print("Cleaned caches and build output.")


# --------------------------------------------------------------------------- secrets

SECRET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("fred-api-key", re.compile(r"(?i)\b(?:fred_)?api_key\s*[=:]\s*['\"]?[0-9a-f]{32}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
]
NEVER_COMMIT = {".env", "PROJECT_BRIEF.md"}
MUST_BE_IGNORED = ("backend/.env", ".env", "PROJECT_BRIEF.md")
PLACEHOLDERS = {"", "your_key_here", "changeme"}


def _local_secret_values() -> list[str]:
    """Secret-looking values from local .env files, searched for literally. Never printed."""
    values = []
    for env_file in (ROOT / ".env", BACKEND / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            value = value.strip().strip("'\"")
            secretish = re.search(r"KEY|TOKEN|SECRET|PASSWORD", name, re.I) is not None
            if sep and secretish and len(value) >= 12 and value.lower() not in PLACEHOLDERS:
                values.append(value)
    return values


def _candidate_files(staged: bool) -> Iterator[tuple[str, bytes]]:
    if staged:
        names = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").split(b"\0")
        for raw in filter(None, names):
            name = raw.decode()
            yield name, git("show", f":{name}")
    else:
        names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
        for raw in filter(None, names):
            name = raw.decode()
            path = ROOT / name
            if path.is_file() and path.stat().st_size < 5_000_000:
                yield name, path.read_bytes()


def task_check_secrets(args: argparse.Namespace) -> None:
    problems: list[str] = []
    for path in MUST_BE_IGNORED:
        if subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode != 0:
            problems.append(f"{path}: not git-ignored")

    known = _local_secret_values()
    scanned = 0
    for name, blob in _candidate_files(args.staged):
        if Path(name).name in NEVER_COMMIT:
            problems.append(f"{name}: this file must never be committed")
        if b"\0" in blob[:8192]:
            continue  # binary
        scanned += 1
        text = blob.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            hits = [rule for rule, pattern in SECRET_RULES if pattern.search(line)]
            if any(value in line for value in known):
                hits.append("value from a local .env file")
            problems.extend(f"{name}:{lineno}: {rule}" for rule in hits)

    if problems:
        print("Possible secrets (values not shown):")
        print("\n".join(f"  {p}" for p in problems))
        raise TaskError(f"check-secrets found {len(problems)} problem(s)")
    scope = "staged" if args.staged else "tracked + untracked"
    print(f"check-secrets: {scanned} {scope} text files clean; .env and brief are git-ignored.")


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tasks.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="task", required=True, metavar="task")

    def add(name: str, fn: Callable[[argparse.Namespace], None]) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        p.set_defaults(func=fn)
        return p

    p = add("setup", task_setup)
    p.add_argument("--no-frontend", action="store_true", help="skip npm install")
    p.add_argument("--no-hooks", action="store_true", help="skip installing the pre-commit hook")
    add("dev", task_dev).add_argument("--offline", action="store_true", help="seed data only")
    p = add("test", task_test)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--py-only", action="store_true")
    group.add_argument("--js-only", action="store_true")
    add("lint", task_lint)
    add("fmt", task_fmt)
    add("api", task_api).add_argument("--check", action="store_true", help="fail on drift")
    add("build", task_build)
    add("check", task_check)
    add("demo", task_demo)
    add("e2e", task_e2e)
    add("mpc-report", task_mpc_report)
    add("replays", task_replays).add_argument("episodes", nargs="*", help="episode ids (all)")
    add("screenshots", task_screenshots)
    add("seed", task_seed).add_argument(
        "--sources", help="comma-separated subset of fred,treasury,fiscaldata,tic"
    )
    add("check-secrets", task_check_secrets).add_argument("--staged", action="store_true")
    add("clean", task_clean)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except TaskError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
