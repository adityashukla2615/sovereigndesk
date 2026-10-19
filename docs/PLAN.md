# SovereignDesk — Implementation Plan

> Resume note for later sessions: this plan is copied to `docs/PLAN.md` in `C:\dev\sovereigndesk`. The spec is `docs/BRIEF.md` (a copy of PROJECT_BRIEF.md with the API key removed). Continue from the first phase that has no commit.

## Context
The folder holds only `PROJECT_BRIEF.md`. The goal is **SovereignDesk**: a live, Bloomberg-style terminal that simulates the US Treasury market and the Indian money market. It has to show correct maths, use real data with an offline seed fallback, stream simulated intraday ticks, and look polished enough for a quant/finance portfolio. The brief is the spec (Modules A–D, data sources, stack, phases, quality bar). This plan sets the architecture, refines the phases, and records the decisions made so far. No code gets written until you approve it.

## Decisions locked
| Item | Decision |
|---|---|
| Location | `C:\dev\sovereigndesk` (outside OneDrive). The OneDrive folder stays as it is. |
| Git | `git init -b main`. Repo-local identity: `adityashukla2615` / `178527180+adityashukla2615@users.noreply.github.com` |
| GitHub | Private repo `adityashukla2615/sovereigndesk`, created with gh. Push after every phase. Making it public at the end is your call. |
| Checkpoints | Pause after the MVP and at the end. Every phase ends with green tests, a commit and a push. |
| Python | 3.14 locally (cp314 Windows wheels confirmed on PyPI for numpy, scipy, pandas, sklearn, statsmodels, pydantic-core, psycopg; XGBoost ships py3-none). `requires-python >=3.12` because XGBoost 3.x needs it, which still meets the brief's "3.11+". CI runs 3.12 and 3.14; Docker uses `python:3.12-slim`. |
| Node | 24 locally; CI runs 22 and 24; npm. |
| No Docker or make locally | Compose files and the Makefile still get written. The real task runner is a stdlib-only `tasks.py`, and the Makefile delegates to it. CI builds the images and runs make on Ubuntu, so both get exercised there. |
| Toolchain pins (Phase 1) | TypeScript stays on 5.9: TS 7's native compiler drops the JS API that typescript-eslint and openapi-typescript need. `xgboost-cpu` replaces `xgboost` everywhere except macOS (5 MB instead of 54 MB plus the CUDA NCCL wheel). The backend uses `httpx2`, the pydantic-maintained successor that Starlette 1.x's TestClient expects. Dev tools are pinned in `requirements-dev.txt`. |
| India sources (Phase 5) | CCIL needs no adapter of its own: RBI's daily Money Market Operations release carries call, TREPS and market repo ("Based on RBI / CCIL"). MOSPI CPI and RBI's MPC history move to Phase 8, FBIL G-sec par yields to Phase 7, and the Weekly Statistical Supplement and NSDL's history to Phase 9. T-bills come from FBIL's dated benchmarks, not the homepage cut-offs, which carry no auction date. RBI sets no call-money lending limits, so the brief's 25%/50% become a labelled board-limit assumption. The daily CRR minimum is 99% from 16 Oct 2026. |
| Probe findings | The FRED key works. The TIC holders table moved to `slt_table5.txt` (`mfh.txt` has been stale since Jan 2023). The RBI homepage shows current repo/SDF/MSF/CRR/SLR and T-bill cut-offs in scrapable form. The FiscalData MSPD security-level endpoint is live. Live values differ a lot from older memory, which is why nothing gets hardcoded. |

## Architecture
```
┌─────────────── frontend (React + TS + Vite + Tailwind) ───────────────┐
│ CommandBar · TickerTape · 4 resizable panel slots · EventLog · Teach  │
│ Zustand stores ◄── WS client (topics) / typed REST client (OpenAPI)   │
└───────────────┬───────────────────────────────▲───────────────────────┘
          REST /api/*                     WS /ws (snapshot + deltas)
┌───────────────▼───────────────────────────────┴───────────────────────┐
│ backend (FastAPI)                                                      │
│ commands/ parser ─► services/ ─► sim/ (MarketState, clock, tick loop) │
│ data/sources ─► cache ─► DB (SQLAlchemy 2 + Alembic; SQLite→PG/TSDB)  │
│ APScheduler refresh jobs · PubSub (in-memory default | Redis opt-in)  │
└───────────────┬────────────────────────────────────────────────────────┘
                │ pure function calls (no I/O)
┌───────────────▼────────────────────────────────────────────────────────┐
│ engine/ → sovereign_engine: bonds · curves · rates · us · india ·      │
│           linkage · predict · replay                                   │
└────────────────────────────────────────────────────────────────────────┘
data/seed (real snapshots + manifest) · data/replays/<ID>/v1 · data/cache (git-ignored)
```
```
sovereigndesk/
├─ engine/    pyproject.toml · src/sovereign_engine/{bonds,curves,rates,us,india,linkage,predict,replay}/ · tests/
├─ backend/   pyproject.toml · app/{main,config}.py · app/{api,ws,sim,commands,services,db,data/sources}/ · alembic/ · tests/ · .env (ignored) · .env.example
├─ frontend/  src/{app,components,panels,charts,store,ws,api,teach}/
├─ data/      seed/ · replays/ · cache/ (ignored)
├─ scripts/   build_seed.py · demo_check.py · screenshots
├─ docs/      PLAN.md · BRIEF.md (redacted) · architecture.md · img/
└─ ASSUMPTIONS.md · README.md · DEMO.md · tasks.py · Makefile · docker-compose.yml · .github/workflows/ci.yml
```
There is one `.venv` at the repo root, with engine and backend installed into it in editable mode. The backend depends on the engine; the engine depends only on numpy, scipy, pandas, statsmodels, scikit-learn and xgboost.

## Key designs

### 1. Engine (pure, typed with mypy strict, every formula in a docstring `Equation:` section)
- **bonds:** day counts (ACT/ACT ICMA, 30/360, ACT/360, ACT/365), coupon schedules, dirty and clean price, accrued interest, and YTM (Newton with an analytic derivative, Brent as fallback). Also Macaulay and modified duration, convexity, DV01, key-rate durations, and bill conventions (US discount/BEY, India T-bill 365-day yield). A per-market convention table is verified and cited in Phase 2.
- **Approximation overlay:** ΔP/P ≈ −D_mod·Δy + ½·C·Δy², plotted against exact repricing.
- **curves:** bootstrap from par yields to zero rates and forwards. NSS fit: solve β by linear least squares over a (λ1, λ2) grid, then refine with bounded `least_squares`, using multi-start and the constraints β0>0, β0+β1>0.
- **rates:**
  - Vasicek: exact OU step and closed-form P(t,T).
  - CIR: exact noncentral-χ² step, Feller-condition check, closed-form P.
  - Hull-White 1F: θ(t) fitted to today's curve, P(t,T) per Brigo–Mercurio.
  - Bounded OU for rates that live inside a corridor.
- **Tests:**
  - textbook anchors, e.g. Hull OFOD Table 4.6: a 3y 10% semiannual bond at 12% continuous compounding prices at 94.213 with duration 2.653
  - closed-form par-bond identities
  - closed form against Monte Carlo
  - HW reprices the input curve to 1e-10
  - Hypothesis property tests: price strictly decreasing and convex in yield, approximation error O(Δy³)
  - a meta-test that fails if a public engine function lacks an `Equation:` docstring

### 2. Data layer
- **Adapters** share one interface, `fetch(series, start, end) → tidy frame + provenance`:
  - **FRED:** the brief's list plus RRPONTSYAWARD, WRESBAL, WTREGEN, IOER (for pre-2021 replays), DEXINUS, INDIRLTLT01STM, VIXCLS, DTWEXBGS and THREEFYTP10. IDs get verified in Phase 3.
  - **FiscalData:** debt to the penny, average interest rates, interest expense, MTS, MSPD table 3 (security level).
  - **TIC:** `slt_table5.txt`, plus the historical MFH files.
  - **Treasury:** daily par-curve CSV.
  - **RBI:** homepage current rates; the daily Money Market Operations press releases (WACR, call high/low, TREPS, market repo, LAF ops); the WSS (NDTL, government balance at RBI, forex reserves); MPC decision history.
  - **FBIL:** T-bill benchmarks, MIBOR, G-sec par yields.
  - **CCIL**
  - **MOSPI:** CPI, chain-linked across base revisions.
  - **NSDL:** daily FPI flows.
  - **BoE:** gilt yield curves, for GILT2022.
- **Fetching and storage:** httpx plus tenacity (retries, backoff). Raw responses go to an on-disk cache, and parsed rows go to `observations(series_id, date, value, source, fetched_at, quality)`. A `source_status` table drives staleness.
- **Quality tags:** each series carries LIVE, CACHED(age), SEED(date), SIMULATED or SYNTHETIC. Panels show a **STALE / SEED DATA** badge whenever an input isn't fresh live data.
- **Fallback:** live, then cache, then seed. `scripts/build_seed.py` writes a snapshot of real data to `data/seed/*.csv` plus `manifest.json` (URL, fetched_at, row count, sha256).
- **Refresh:** APScheduler jobs run on each source's own cadence (daily, weekly or monthly).
- **Policy values are never hardcoded.** They are fetched. Any fallback in config carries `# VERIFY:`, a source URL and an as-of date.

### 3. Simulation engine (`backend/app/sim`)
- **State and loop:** one `MarketState` (US, India, FX, linkage). An asyncio tick loop starts in the FastAPI lifespan. Default speed is 1 wall-second = 1 sim-minute (adjustable with `SPEED`). Each sim day re-anchors to the latest real values.
- **Two outputs per shock:**
  1. Intraday stream: the immediate repricing, shown with blinking prices.
  2. Scenario projection: the full path over days, months or years, computed at once (e.g. QT shows reserves, EFFR spread and the 10Y over 24 months).
- **Paced shocks:** a shock with a pace (`SHOCK JP 200B 10D`) is scheduled into the sim calendar.
- **Model layers:**
  1. Stochastic drift: the HW1F short rate moves the whole US curve analytically, plus an OU term-premium factor; WACR follows a bounded OU.
  2. Deterministic shocks, triggered by commands.
- **Invariants asserted every tick:**
  - EFFR ∈ [L, U] and WACR ∈ [SDF, MSF]
  - the Fed balance-sheet identity holds
  - the India liquidity identity holds
- **Event log:** every shock writes a plain-language entry with computed numbers, e.g. "Japan sold $50B of 10Y → 10Y +18 bp → interest cost +$X bn/yr".
- **Scenarios:** a scenario is an ordered list of commands with a seeded RNG, which makes save, load and replay deterministic.

### 4. Module A — US
- **Fed corridor:** IORB = U − s₁ and ON RRP = L + s₂, with the offsets read from the latest data; the SRF minimum bid sits at U. EFFR = IORB + g(reserves/bank assets) + ε, where g is a reserve-demand curve after Afonso–Giannone–La Spada–Williams (NY Fed, 2022), clipped into [L, U].
- **QT:** monthly runoff caps. The SOMA decline drains ON RRP first, then reserves. The extra private duration supply (in 10y-equivalents) raises the term premium through an elasticity taken from the literature, cited and configurable. Falling reserves widen the EFFR spread.
- **Price impact:**
  - Permanent: Δy_k = λ·Q_k/D_k, spread across tenors by the kernel e^{−|τ−τ_k|/ℓ}.
  - Temporary: η·σ_k·√(q_t/V_k), decaying with half-life h.
  - D_k = dealer balance-sheet capacity plus other absorbers.
  - λ uses a literature default until Phase 10 calibrates it on GILT2022.
- **Foreign sell-off:** inputs are TIC holdings, amount, pace and tenor mix (SHORT/BELLY/LONG). Outputs are the yield path, term premium, USD move (flow elasticity) and debt-cost change. Optional responses: QT pause, SRF usage, buybacks (teach mode labels buybacks as a Treasury tool, not a Fed one).
- **Debt servicing:**
  - Mechanics: the MSPD security-level maturity ladder is rolled over at simulated yields using the issuance mix (default: recent auction mix), and deficits are financed with the same mix. TIPS and FRNs are approximated.
  - Outputs: net interest in $, as % of GDP and as % of receipts, shown as baseline vs shocked.
- **CORR:** the Fed funds market next to India's call money market. Both are overnight unsecured interbank markets with a corridor; corridor diagrams included.

### 5. Module B — India money market
- **Synthetic bank universe:** about 40 banks with generic names (PSB-03, PVT-11, FGN-02, SFB-01, PD-01), lognormal sizes scaled to the real aggregate NDTL. Each has capital funds or NOF, CRR (fortnightly average plus a daily minimum share), SLR and an MSF dip limit. All rules live in config, and Phase 5 verifies them against RBI's current call/notice/term directions with citations.
- **Two consistent rate layers:**
  - (a) Macro map: WACR − repo = f(liquidity % NDTL), a logistic curve fitted on real RBI history.
  - (b) Micro clearing: each bank's reserve gap becomes an order. Reservation rates centre on (a) and are bounded by SDF (lenders' outside option) and MSF (borrowers' outside option). A uniform-price call auction clears each tick and produces trades, WACR (volume-weighted) and the high/low. Notice and term segments add term spreads.
- **Participation limits:** average and peak limits are checked on every trade. Rejected trades are logged with the reason.
- **LAF:** SDF and MSF are standing facilities. VRR/VRRR auctions have a notified amount, tenor, bids and a cut-off (auction format verified and set in config). An RBI reaction function runs automatically, or you trigger it by hand (`VRR 50000CR 7D`).
- **Rates panel:** TREPS and market repo = WACR + calibrated spreads. 91/182/364-day T-bills = latest cut-offs + a liquidity spread. The panel shows the spreads WACR−repo and T-bill−repo.
- **Sign convention:** surplus = net LAF absorption > 0. Liquidity drivers: government cash at RBI, currency in circulation, FX operations, OMOs, CRR changes.
- **Tax cycle:** advance tax on 15 Jun/Sep/Dec/Mar plus GST outflows around the 20th. The government balance rises, liquidity falls, WACR spikes, and RBI responds with VRR. The calendar heatmap is simulated, with real WACR history overlaid where it was scraped.
- **CCIL panel:** an SVG of NDS-Call trading and of TREPS/market repo settling through CCIL as central counterparty.

### 6. G-sec curve and MPC predictor
- **G-sec curve:** 91D through 30Y with an NSS fit. Repo pass-through β(τ) comes from an event study on MPC dates and decays with maturity, plus a term-premium term. A live chart shows the US10Y–IN10Y spread.
- **MPC predictor:**
  - Classes: {big cut, cut, hold, hike, big hike}.
  - Features: those in the brief, joined as-of with publication lags so there is no look-ahead. The output gap uses a one-sided HP filter.
  - Models: a Taylor-rule baseline (π* = 4%, r* in config), an ordered logit (statsmodels `OrderedModel`) and a regularised XGBoost.
  - Backtest: walk-forward with an expanding window, reporting accuracy, macro-F1, a confusion matrix and the Brier score against naive baselines (repeat last decision, always hold).
  - Sample: the MPC era from Oct 2016 plus pre-MPC RBI decisions, with a regime dummy.
  - Next meeting: the date comes from RBI's published schedule (fetched, or config marked VERIFY).

### 7. Module C — US → India linkage
Each node is a pure function with configurable parameters:
1. ΔUS10Y, or a Fed hike passed through the curve → Δdiff = β_IN·ΔUS10Y − ΔUS10Y
2. FPI debt and equity flows = φ·Δdiff + ψ·Δrisk (VIX)
3. ΔUSD/INR = κ·(FPI outflow − RBI USD sales)
4. RBI USD sales = θ·pressure (the intervention share)
5. Rupee liquidity drain = sales × spot × (1 − sterilised share)
6. ΔWACR and ΔT-bill yields, via the Module B maps
7. RBI's choice: let rates rise | VRR | OMO purchase | FX buy/sell swap | repo hike

Parameters are calibrated by regression on real data (NSDL FPI flows, DEXINUS, RBI monthly FX intervention, yields) where it exists; otherwise literature defaults apply. All of them are listed in ASSUMPTIONS.md. The UI is an animated SVG flow diagram with live numbers on each node. `LINK` shows the chain; `SHOCK FED 50BP` runs it step by step along a timeline.

### 8. Module D — Historical replay
- **Dataset format:** `data/replays/<ID>/v1/{episode.yaml, series/*.csv, manifest.json}`. The yaml holds the window, drivers, targets, and annotations with source URLs.
- **Comparison:** the model is driven by the actual exogenous inputs from the episode start, and its path is compared with what happened: RMSE, MAE, direction accuracy and peak error, plus an auto-generated "what the model got right/wrong" summary. Controls: play, pause, speed, scrub, and an annotated timeline.
- **Episodes:**
  - `TAPER2013`
  - `DASH2020`
  - `GILT2022`, which also calibrates λ: least squares of daily Δ30Y against net forced flow ((estimated LDI sales − BoE purchases) / depth), with a bootstrap CI, transferred to Treasuries by the depth ratio
  - `HIKE2022`
  - `ADVTAX`: 2–3 quarters picked from the data (largest WACR−repo around the 15th), not from memory

### 9. Frontend
- **Look:** black background, amber primary text, green/red ticks, monospace fonts from `@fontsource` so it works offline. Colours are Tailwind tokens.
- **Layout:**
  - Top: the command bar (autocomplete from the backend registry, ↑/↓ history) and a status strip (ET and IST clocks, sim speed, data-quality summary).
  - Below it: the ticker tape.
  - Main area: four resizable slots (`react-resizable-panels`), each able to load any function.
  - Bottom: the event log.
- **Keyboard:** `/` focuses the command bar, Ctrl+1..4 focuses a panel, Esc and Enter work as expected.
- **Charts:**
  - `lightweight-charts` for time series and replays.
  - Tree-shaken ECharts for curves, the tax heatmap, the confusion matrix, probability bars and the price–yield chart.
  - Custom SVG for the corridors, the LINK flow and the CCIL diagram.
- **Behaviour:** values blink on change, STALE/SEED badges appear where needed, and teach mode adds notes to every panel. TypeScript types are generated from the FastAPI OpenAPI schema with `openapi-typescript`.
- **Commands** (the backend registry is the single source of truth):
  - US: `PY [tenor]` `UST` `FED` `HIKE|CUT 25BP` `QT 95B|QT OFF` `DEBT` `TIC` `SHOCK JP 200B [10D] [LONG]` `CORR`
  - India: `CALL` `WACR` `LAF` `NDTL` `CRR 3.5` `REPO +25BP` `VRR|VRRR 50000CR 7D` `TAXCAL` `GSEC` `SPRD` `MPC` `CCIL`
  - Cross-market: `LINK` `SHOCK FED 50BP` `REPLAY TAPER2013|DASH2020|GILT2022|HIKE2022|ADVTAX`
  - System: `HELP [code]` `TEACH` `SPEED 10X` `PAUSE` `RESUME` `RESET` `SAVE|LOAD name` `EXPORT CSV|PNG`
- **WebSocket protocol:**
  - Client sends `{op:"subscribe",topics}` or `{op:"command",text}`.
  - Server sends `{topic,ts,seq,data}` on the topics `us.tick`, `in.tick`, `fx.tick`, `events`, `link`, `replay.<id>` and `status`.
  - A subscription gets a snapshot first, then deltas at up to 4 Hz.

## Secrets and data honesty
- `.gitignore` exists before the first commit and covers `.env`, `**/.env`, `PROJECT_BRIEF.md`, `.venv`, `node_modules`, `data/cache` and `backend/var`. `git check-ignore` confirms it.
- `backend/.env` holds the FRED key, copied from the brief by script and never printed. `.env.example` has the placeholder. `docs/BRIEF.md` is the brief with the key removed; the original brief is not copied into the new repo.
- The key never appears in source, tests, README or commit messages. A logging filter redacts `api_key=`, and the cache strips it. gitleaks runs in CI, and `tasks.py check-secrets` runs before every commit.
- Nothing is called "real" unless it was fetched from an official or public source and has provenance. If a series can't be obtained, it is marked model-only, its comparison is skipped and the gap is documented. Nothing is invented. The bank universe is labelled SYNTHETIC everywhere.

## Phases
**Step 0** (this session, right after approval):
1. Create `C:\dev\sovereigndesk`.
2. Write `.gitignore`.
3. `git init`, then set the repo-local identity.
4. Write `backend/.env` (key copied from the brief by script) and `.env.example` (placeholder).
5. Add `docs/BRIEF.md` (key removed) and `docs/PLAN.md` (this plan).
6. Run the secret check, then make the first commit.
7. `gh repo create sovereigndesk --private --source . --push`.

Then you reopen VS Code at `C:\dev\sovereigndesk` and say "continue docs/PLAN.md from Phase 1".

| # | Phase | Deliverables | Exit criteria |
|---|---|---|---|
| 1 | Scaffold | Engine and backend pyprojects; FastAPI health check plus WS echo; Vite + Tailwind shell talking to the WS; `tasks.py` (setup/dev/test/lint/check/seed/check-secrets); Makefile; Compose plus Dockerfiles (backend, frontend+nginx, timescaledb, redis); CI (ruff, mypy, pytest, eslint, tsc, vitest, build, docker build, gitleaks); pre-commit | `py tasks.py check` green locally; CI green on GitHub |
| 2 | Engine: bonds, curves, short-rate models | §1 | Textbook and property tests pass; docstring meta-test passes |
| 3 | US data | FRED, FiscalData, TIC and par-curve adapters; cache; DB + Alembic; real seed snapshot; scheduler; `/api/data/status` | Offline tests on recorded fixtures pass; seed built from live data |
| 4 | US simulator | Corridor/EFFR, QT, price impact, sell-off, debt rollover, tick loop, WS topics, US command parser, event narratives | EFFR stays in range over 10k ticks; identity tests pass |
| 5 | India data + banks | RBI, FBIL, CCIL, MOSPI and NSDL adapters plus seed; participation limits, MSF and CRR rules verified with citations; synthetic banks scaled to real NDTL | Parser tests on saved pages; limit tests |
| 6 | India simulator | Call/notice/term clearing, limit enforcement, WACR, LAF, VRR/VRRR plus reaction function, TREPS/repo, T-bills, tax cycle, heatmap data, macro map fitted on real history | WACR stays in the corridor; rejected-trade tests pass |
| **MVP** | Terminal MVP | Command bar, ticker, 4-panel grid, event log and badges; polished **PY**, **FED/QT shock** and **WACR-corridor** panels with teach notes | Live demo works end to end; `demo_check.py` passes; screenshots → **PAUSE for your review** |
| 7 | G-sec curve | India NSS curve, pass-through, US–IN 10Y spread; GSEC and SPRD panels | Tests pass |
| 8 | MPC predictor | Dataset build, Taylor rule, ordered logit, XGBoost, walk-forward report, MPC panel | Backtest report committed |
| 9 | Linkage | Chain engine, calibration, LINK flow panel, `SHOCK FED` | Chain tests pass (signs, magnitudes, conservation) |
| 10 | Replays | Five episode datasets, replay engine, metrics, GILT λ calibration, REPLAY panel | Metric tests pass; λ and its CI recorded in ASSUMPTIONS |
| 11 | Terminal completion | Remaining panels (UST, DEBT, TIC, CORR, CALL, LAF, NDTL, TAXCAL, CCIL, HELP), saved layouts, full keyboard navigation, teach mode on every panel | vitest plus Playwright smoke test pass |
| 12 | Polish | Scenario save/load, CSV/PNG export, README (mermaid diagram, screenshots), complete ASSUMPTIONS.md, DEMO.md (3-minute script covering all seven demo beats) | Full check green; **PAUSE (end)** |

Change from the brief: after the MVP, each module phase ships its own panel as a vertical slice, so Phase 11 finishes the UX instead of building every panel at once.

## Verification
- **Every phase:** `py tasks.py check`, which runs ruff, mypy, pytest (engine and backend, offline on recorded fixtures), eslint, tsc, vitest and the vite build. Then commit, push, and confirm CI is green.
- **Financial correctness:** textbook anchors, closed form against Monte Carlo, curve repricing, Hypothesis properties, and invariants asserted while the sim runs.
- **End to end:** `py tasks.py dev` starts the backend on :8000 and the frontend on :5173. `scripts/demo_check.py` drives the WebSocket through the demo commands and asserts:
  - a QT shock moves the 10Y up and reserves down
  - `SHOCK JP` raises yields and debt cost
  - WACR stays inside the corridor
  - a tax-date squeeze raises WACR−repo
  - `REPLAY` produces metrics
- **Offline:** `--offline` boots from the seed only and shows SEED badges; a simulated source failure shows the STALE badge.
- **Final:** walk through DEMO.md live.

## Risks and mitigations
- **India sources may resist scraping** (the DBIE single-page app, NSDL, FBIL's JavaScript pages). Each source gets fallbacks (RBI press releases, PDF/Excel files), and the seed is compiled once from official files with provenance. Gaps are documented, never invented.
- **The MPC sample is small** (~110 decisions). Report honest metrics against naive baselines, regularise, and don't overclaim.
- **LDI flow data for the gilt crisis is only partly public.** Use cited estimates and report sensitivity and a CI for λ.
- **The scope is large.** The MVP checkpoint comes first, and every phase can ship on its own.
