# SovereignDesk

A live, Bloomberg-style terminal that simulates the US Treasury market and the Indian money market. It is built on real data from FRED, US Treasury, TIC and RBI, uses a pure-Python quant engine, and streams intraday ticks from stochastic short-rate models.

> Work in progress. The build plan is in [docs/PLAN.md](docs/PLAN.md) and the spec in [docs/BRIEF.md](docs/BRIEF.md).

## Quick start

Needs Python 3.12+ and Node 22.12+. On Linux/macOS use `python3` instead of `py`, or `make <task>`.

```sh
py tasks.py setup                       # .venv, editable engine + backend, npm ci, git hooks
cp backend/.env.example backend/.env    # then add your free FRED API key
py tasks.py dev                         # API on :8000 (docs at /docs), terminal on :5173
py tasks.py check                       # secrets scan, lint, types, tests, build: what CI runs
```

With Docker: `docker compose up --build` (or `make up`) starts the backend, the nginx-served frontend, TimescaleDB and Redis; open http://localhost:8080.

## Layout

| Path | Contents |
|---|---|
| `engine/` | `sovereign_engine`: pure, typed quant maths with no I/O; every formula is documented and tested |
| `backend/` | FastAPI app: REST under `/api`, WebSocket at `/ws`, data adapters, simulator |
| `frontend/` | React + TypeScript terminal (Vite, Tailwind, Zustand); REST types generated from OpenAPI |
| `data/` | Real-data seed snapshots and versioned replay datasets |
| `tasks.py` | Stdlib-only task runner; the Makefile and CI delegate to it |
