# Prompt for Claude Code — "SovereignDesk": Bond & Money Market Simulation Terminal

> Paste everything below this line into Claude Code, from the empty project folder.

---

You are building **SovereignDesk**, a full-stack, live, Bloomberg-style terminal that simulates the US Treasury market and the Indian money market. It is a portfolio project for a CSE + Economics student targeting quant/finance roles. It must look professional, run live (streaming ticks), use real data where available, and have correct financial maths. Read this whole brief, then **enter plan mode, propose the architecture and a phased plan, and wait for my approval before writing code.**

## 1. Core economic story the terminal must demonstrate

### Module A — US Treasuries, inflation and the Fed
1. **Price–yield inverse relationship.** Show live, for any bond: price, YTM, Macaulay/modified duration, convexity, DV01. A yield slider re-prices bonds in real time with a duration + convexity approximation overlaid on exact repricing.
2. **Inflation → Fed response.** When CPI runs above the 2% target, the Fed tightens in two ways:
   - **Rate hikes:** raise the Fed funds target range; IORB and the ON RRP rate move with it, and the effective Fed funds rate (EFFR) must stay inside the range.
   - **Quantitative tightening (QT):** the Fed lets Treasuries run off its balance sheet (or sells them). Private investors must absorb more supply → prices fall → yields rise. Bank reserves and liquidity fall.
3. **Government debt-servicing cost.** Higher yields raise the cost of rolling over maturing debt. Model the debt maturity profile, roll it over at simulated yields, and show net interest outlays in dollars, as % of GDP, and as % of federal tax revenue. This is the fiscal trade-off of fighting inflation through yields.
4. **Foreign holder sell-off scenario.** The user picks a country (Japan, China, UK, etc. — real holdings from Treasury TIC data) and a sell amount and pace. Simulate:
   - supply shock absorbed by the market via a price-impact model (yield change scales with sell size relative to market depth and dealer balance-sheet capacity),
   - curve reshaping (where on the curve the selling lands),
   - term-premium increase, effect on USD and on debt-servicing cost,
   - optional Fed response (pause QT, standing repo facility usage, buybacks).
5. **Fed funds market ≈ India's call money market.** Show a side-by-side panel explaining that both are overnight unsecured interbank markets where banks lend reserves to each other, and the central bank steers the rate inside a corridor.

### Module B — India money market and RBI liquidity management
1. **Three money-market segments** (unsecured interbank):
   - Call money — overnight
   - Notice money — 2 to 14 days
   - Term money — 15 days to 1 year
2. **NDTL (Net Demand and Time Liabilities).** Model a set of synthetic banks with NDTL, CRR (cash maintained with RBI) and SLR (government securities held). Show how a change in CRR or NDTL drains or adds system liquidity.
3. **Participation limits** (make these configurable; verify current RBI master direction values before hardcoding):
   - Scheduled commercial banks: borrowing up to 100% of capital funds on a fortnightly average basis (peak 125%); lending up to 25% average (peak 50%).
   - Primary dealers: borrowing up to 225% of net owned funds; lending up to 25%.
   - Enforce these in the simulator; breaching banks get rejected trades.
4. **Policy corridor (LAF).** SDF (floor) = repo − 25 bps, repo (policy rate), MSF (ceiling) = repo + 25 bps. Overnight rates must stay inside the corridor. Include variable-rate repo (VRR) and reverse repo (VRRR) auctions as RBI's fine-tuning tools.
5. **Rates panel:** call money rate (high/low/range), **Weighted Average Call Rate (WACR)** — RBI's operating target — plus TREPS and market repo rates (CCIL segments), and 91/182/364-day T-bill yields. Show the spreads WACR−repo and T-bill−repo as liquidity signals (positive spread = tight liquidity, negative = surplus).
6. **CCIL's role:** a visual of how call money trades on NDS-Call and how TREPS/market repo settle through CCIL as central counterparty.
7. **Quarterly liquidity cycle.** Advance-tax due dates are **15 June, 15 September, 15 December and 15 March** (plus GST payments around the 20th of each month). On these dates money moves from bank deposits into the government's account at RBI, so banking-system liquidity tightens and WACR spikes toward or above repo. Build a calendar heatmap and a simulation of the government cash balance at RBI vs system liquidity, and show how RBI responds with VRR auctions.
8. **India G-sec yield curve.** Build the full government securities curve (91D/182D/364D T-bills, then 2Y, 5Y, 10Y, 14Y, 30Y G-secs). Fit it with Nelson-Siegel-Svensson. Show how a repo change passes through the curve: short end moves most, long end less, with term-premium effects. Also show the US 10Y vs India 10Y spread as a live chart.
9. **Repo rate prediction.** Build a model to forecast the next MPC decision (cut / hold / hike and size):
   - Baseline: Taylor rule (inflation gap vs 4% target, output gap).
   - ML model: ordered logit or gradient boosting on CPI inflation, core CPI, WACR−repo spread, T-bill−repo spread, system liquidity, GDP growth, US Fed funds rate, INR/USD.
   - Backtest on historical MPC decisions, report accuracy and a confusion matrix, and show the probability distribution for the next meeting date.

### Module C — Cross-market linkage (US → India transmission)
Connect Modules A and B so that one US shock flows through to the Indian money market, step by step and visible on screen:

1. **Fed hike / QT or US yield spike** → US–India yield differential narrows.
2. **FPI outflows** from Indian bonds and equities (model the flows as a function of the yield differential and global risk appetite).
3. **Rupee depreciates** (USD/INR moves).
4. **RBI intervenes**: it sells USD from forex reserves to defend the rupee.
5. **Rupee liquidity drains**: when RBI sells dollars, banks pay in rupees, so system liquidity falls.
6. **WACR rises** toward or above repo, and T-bill yields rise.
7. **RBI response choice**: let rates rise, inject liquidity via VRR / OMO purchases / FX swaps, or hike repo.

Show this chain as an animated flow diagram with live numbers at each node. Each node's parameters (elasticities, intervention share) must be configurable and calibrated where possible. Command: `LINK` (shows the chain), `SHOCK FED 50BP` (runs it end to end).

### Module D — Historical replay mode
Let the user replay real episodes using real historical data, then compare the model's predicted path against what actually happened (side-by-side chart + error metrics such as RMSE and direction accuracy).

Episodes to include:
- **2013 Taper Tantrum** (May–Sep 2013): a Fed taper signal → US yields up → FPI outflows from India → rupee crash → RBI's emergency liquidity tightening.
- **March 2020 Treasury "dash for cash"**: forced Treasury selling, liquidity collapse, Fed intervention.
- **September 2022 UK gilt / LDI crisis**: forced pension-fund bond selling, yield spike, Bank of England emergency purchases. Use it as the closest real analogue to the foreign sell-off scenario and to **calibrate the price-impact parameter**.
- **2022–23 Fed hiking cycle**: inflation → hikes + QT → curve inversion; the RBI's parallel hikes.
- **India advance-tax liquidity crunches**: pick 2–3 real quarters where WACR spiked around the 15th.

Each replay has play/pause/speed controls, an event timeline with annotations, and a "what the model got right/wrong" summary. Command: `REPLAY TAPER2013`, `REPLAY GILT2022`, and so on.

## 2. Data sources

Use real data where possible, with a cached snapshot fallback so the app always works offline. Put keys in `.env`; never commit them.

**My FRED API key:** `[REDACTED]`
Write it into `backend/.env` as `FRED_API_KEY=[REDACTED]`. Make sure `.env` is in `.gitignore` before the first commit. Put only a placeholder (`FRED_API_KEY=your_key_here`) in `.env.example`. Never write the key into source code, tests, the README or commit messages.

**US**
- FRED API (free key): `DGS1MO, DGS3MO, DGS6MO, DGS1, DGS2, DGS5, DGS10, DGS30, EFFR, SOFR, DFEDTARU, DFEDTARL, IORB, RRPONTSYD, WALCL, TREAST, CPIAUCSL, CPILFESL, PCEPILFE, GDP, FDHBFIN`
- US Treasury FiscalData API (no key): debt to the penny, average interest rates, interest expense, monthly Treasury statement
- Treasury TIC data: major foreign holders by country
- Treasury daily par yield curve

**India**
- RBI Database on Indian Economy (DBIE) and RBI press releases: repo/SDF/MSF, WACR, CRR/SLR, LAF operations, MPC decision history
- CCIL / FBIL: TREPS, market repo, T-bill benchmark rates, MIBOR
- MOSPI: CPI inflation
- CCIL / FBIL / RBI: G-sec yields across tenors (2Y–30Y) and historical G-sec curve data
- NSDL: daily FPI flows (debt and equity)
- RBI weekly statistical supplement: forex reserves, RBI FX intervention data
- FRED: `DEXINUS` (USD/INR) and `INDIRLTLT01STM` (India 10Y yield) as a backup source
- Historical episode data for replay mode: store each episode as a versioned seed dataset in `data/replays/`
- Where no clean API exists, write a robust scraper with retries + caching, and ship a CSV seed dataset so the app runs without it. **Do not hardcode current policy rates from memory — fetch them or put them in config with a clear "verify" comment.**

**Live feed:** real data updates daily, so the terminal's live feel comes from a simulation engine. It starts each day from the latest real values and streams intraday ticks using stochastic short-rate models (Vasicek / CIR / Hull-White for rates, mean-reverting WACR within the corridor) plus user-triggered shocks.

## 3. Tech stack

- **Backend:** Python 3.11+, FastAPI, WebSockets for live ticks, Pydantic models, APScheduler for data refresh jobs, SQLite → PostgreSQL/TimescaleDB-ready via SQLAlchemy, Redis optional for pub/sub. NumPy, pandas, SciPy, statsmodels, scikit-learn/XGBoost.
- **Quant engine (separate package `engine/`):** bond pricing, duration, convexity, DV01, Nelson-Siegel-Svensson curve fitting, bootstrapping, short-rate models, supply-shock price-impact model, debt rollover model, liquidity model, repo predictor. Pure functions, fully unit-tested.
- **Frontend:** React + TypeScript + Vite, Tailwind, a dark Bloomberg-style theme (amber/green on black, monospace data), TradingView `lightweight-charts` for time series, ECharts for curves/heatmaps. Zustand for state.
- **Terminal UX:**
  - A command bar with function codes, e.g. `UST` (US curve), `FED` (Fed panel), `SHOCK JP 200B` (Japan sells $200B), `QT 95B` (QT pace), `CALL` (India call market), `WACR`, `LAF`, `NDTL`, `TAXCAL` (quarterly liquidity), `MPC` (repo forecast), `HELP`.
  - Resizable multi-panel layout, keyboard navigation, ticker tape, live blinking prices, and an event/news log that explains each shock in plain language ("Japan sold $50B of 10Y → 10Y yield +18 bps → interest cost +$X bn/yr").
  - A "teach mode" toggle that annotates each panel with the economics behind it (for viva/interview demos).
- **DevOps:** Docker Compose (backend, frontend, db, redis), Makefile, `.env.example`, GitHub Actions CI (lint + tests), README with architecture diagram, screenshots, and assumptions.

## 4. Build phases (propose and refine these in your plan)

1. Scaffold the monorepo (`backend/`, `engine/`, `frontend/`, `data/seed/`), Docker Compose, CI.
2. Quant engine for bond maths + curve fitting, with tests checked against known textbook values.
3. US data ingestion (FRED, FiscalData, TIC) + caching + seed CSVs.
4. US simulator: Fed hikes, QT, foreign sell-off, debt-servicing panel.
5. India data ingestion + synthetic bank universe with NDTL/CRR/SLR and participation limits.
6. India simulator: call/notice/term market, WACR, LAF corridor, VRR/VRRR, quarterly tax-cycle liquidity.
7. India G-sec yield curve + repo pass-through + US–India 10Y spread.
8. Repo prediction model with backtest report.
9. Cross-market linkage engine (Module C): FPI flows → INR → RBI intervention → liquidity → WACR.
10. Historical replay mode (Module D), including calibration of the price-impact parameter on the 2022 gilt crisis.
11. Frontend terminal: command bar, panels, live WebSocket charts, flow diagram, replay controls, teach mode.
12. Polish: scenario save/load, export charts and CSV, README, demo script.

**MVP rule:** Before phases 7–12, get one end-to-end demo working and polished: price–yield panel, Fed QT shock, and the WACR-in-corridor panel, all live in the terminal UI. Only then continue.

## 5. Quality bar

- Every formula has a docstring with the equation and a unit test.
- Every model assumption is listed in `ASSUMPTIONS.md`, with what is real data vs simulated.
- No silent failures: if a data source is down, show a "STALE / SEED DATA" badge in the UI.
- Commit after each phase with a clear message, and run tests before moving on.
- At the end, give me a 3-minute demo script that walks through: price–yield, Fed QT shock, Japan sell-off, the US → India transmission chain, a Taper Tantrum replay, India advance-tax liquidity squeeze, and the repo forecast.

Start now by exploring the empty folder, then enter plan mode and present the plan.
