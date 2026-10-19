# Assumptions

Every modelling assumption in SovereignDesk, and what is real data versus simulated. Sections are added as each phase lands; the plan is in [docs/PLAN.md](docs/PLAN.md).

## Data honesty

- A number is called real only if it was fetched from an official or public source with provenance (URL, retrieval date). Anything else is labelled SIMULATED or SYNTHETIC.
- Engine anchor tests use committed snapshots of official data, built by `scripts/fetch_engine_fixtures.py`:
  - TreasuryDirect auction results (bills, notes and bonds), for price, yield and accrued-interest formulas.
  - The Federal Reserve's Gürkaynak–Sack–Wright NSS parameters and fitted yields (`feds200628.csv`, two dates).
- Worked examples quoted from 31 CFR Part 356 Appendix B and the RBI primer *Government Securities Market in India* are also used as test anchors.

## US data sources (backend, Phase 3)

Values are stored exactly as published, with the source's units: yields in %, WALCL in USD millions, RRPONTSYD in USD billions, TIC holdings in USD billions. Series IDs are namespaced by source (`fred/…`, `ust/par/…`, `fiscal/…`, `tic/…`). The catalog is `backend/app/data/catalog.py`. Every FRED ID in it was checked against the FRED API on 2026-10-19.

| Source | What | Notes |
|---|---|---|
| FRED | 39 series: CMT yields, policy rates, Fed balance sheet, prices, GDP, MTS receipts and outlays, BEA interest payments, VIX, dollar index, Kim–Wright term premium, USD/INR, India 10Y | `"."` marks a missing observation (e.g. bond-market holidays) and is dropped |
| Treasury | Daily par yield curve, 14 tenors (1M … 30Y) | Columns are matched by header name, because tenors were added over time: 2M in 2018, 4M in 2022, 6W in 2025 |
| FiscalData | Debt to the penny, average interest rates (marketable), interest expense, MSPD table 3 (security level) | "Interest on public issues" is the sum of the *Interest expense on public issues* category; "total" adds Government Account Series. MSPD reports each CUSIP's outstanding amount on its first issue row only |
| TIC | Major foreign holders, monthly, from 2000 | `slt_table5.txt` (latest 13 months) is merged over `mfhhis01.txt` (history), and the newer table wins where they overlap. `mfh.txt` is stale since Jan 2023 and is not used |

How data flows:

- **Fetching.** Live data comes first. Requests retry 429, 5xx and transport errors with exponential backoff (4 attempts). A failed request falls back to the last good raw response on disk, and if there is none, the source is marked down.
- **Seed.** The committed seed (`data/seed`, built by `py tasks.py seed` from live responses only) fills series that have never been fetched.
- **Refresh.** Each refresh re-fetches the last two years so revisions land. Older history comes from the seed. Jobs run on weekdays (ET): FiscalData 16:30, TIC 16:45, FRED 17:30, Treasury 18:30. A catch-up for stale sources runs 5 s after startup.
- **Quality tags.** A series is **LIVE** if its source was fetched successfully within the last 36 h. It is **CACHED (age)** if the last success is older than that, or if the source is currently failing or served a cached raw response. It is **SEED (date)** if it has only ever come from the snapshot. A source outage can be demonstrated with `SD_FAIL_SOURCES=["fred"]`. Discontinued series stay SEED, because no refresh window reaches their last observation. Examples are IOER, which was replaced by IORB in July 2021, and TIC countries that have dropped out of the major-holders table.
- **Secrets.** The FRED key is sent only as a query parameter. It is excluded from cache keys, cache files, provenance URLs and the seed manifest, and redacted from logs and error messages.

## US simulator (Phase 4)

**Anchors.** Every starting value comes from stored real data (`backend/app/sim/anchors.py`), and a missing input stops the build:

- target range, IORB, ON RRP award rate and EFFR
- the Treasury par curve, bootstrapped and NSS-fitted
- the H.4.1 balance sheet, including currency, with the residual on each side
- bank assets
- the Kim–Wright term premium and the broad dollar index
- TIC holdings, debt held by the public, GDP, 12-month MTS receipts and deficit
- the MSPD security ladder

The runoff pace QT starts with is the one observed in the last 13 weeks of H.4.1 holdings (at the time of writing, $0 Treasuries and about $17bn a month MBS).

**Fitted to data.**

- *Reserve demand.* Weekly EFFR − IORB (IOER before 29 Jul 2021) is fitted against reserves / commercial-bank assets on data from 2017 onward: abundant −6.5 bp, scarce +1.9 bp, midpoint 11.5% of bank assets (AGLW report satiation above 12–13%), RMSE 2.4 bp. Weekly averages understate intraday scarcity spikes such as September 2019.
- *Debt service.* The ladder's rates are issue-amount-weighted yields at issue. Against FiscalData's average rates they come out at: bills 3.76% (official 3.87%), notes 3.38% (3.38%), bonds 3.47% (3.47%), TIPS 1.18% (1.15%).

**Assumptions, not fitted (all in `USModelParams`).**

| Item | Choice |
|---|---|
| Curve dynamics | The anchored curve plus x·B(τ)/τ, where x is the Hull–White factor (a = 0.10, σ = 0.85%/√yr). It is evaluated at t = 0, so there is no risk-neutral roll toward the forwards: the curve moves only on shocks and noise. A fit correction makes the opening print equal the official par curve exactly. |
| Term premium | OU deviation (κ = 1/yr, σ = 0.6%/√yr) on top of the Kim–Wright level, with loading (1 − e^(−τ/7))/(1 − e^(−10/7)), equal to 1 at 10 years. |
| Policy pass-through | Loading (1 − e^(−κτ))/(κτ) with κ = 0.5/yr: about 1 at the front end and 0.2 at 10 years. EFFR moves with the range on the effective date. |
| EFFR | Logit-OU, κ = 250/yr, around IORB + the reserve-demand spread. It cannot leave the range. |
| QT | Runoff is spread evenly through the month and drains ON RRP first, then reserves. It halts at the reserves floor (default 0). The term premium rises 10 bp per 1% of GDP of 10-year equivalents absorbed (Crawley et al., 2022). Treasury runoff converts to 10-year equivalents at the issuance mix's par-bond durations. MBS duration is assumed to be 5.5 years. |
| Sell-off impact | Calibrated to Beltran et al.: $100bn in a month moves the bucket centre +20 bp permanently and +30 bp temporarily. The impact is scaled by debt held by the public in June 2010 relative to today, and the temporary part follows a square-root law in pace with a 5-day half-life. It spreads along the curve with kernel e^(−\|τ − τ_k\|/5y). Buckets are centred on SHORT 2y, BELLY 5y and LONG 20y. Defaults: pace 1 day, mix BELLY. |
| Dollar | −0.25% per $100bn sold by foreign holders. **Uncalibrated**, and labelled so in the event text. |
| Debt projection | Like-for-like rollover. Deficits (last 12 months) are financed at the stock/term mix. Both yield paths are held flat: today's curve against the simulated one. TIPS earn the real coupon plus 2.5% inflation and are reissued as nominal debt; FRNs pay the 3-month yield plus 10 bp. GDP and receipts grow 4% a year in nominal terms. |
| Clock | One wall-clock second is one simulated minute (SPEED changes this). Ticks run at 4 Hz, and each tick message carries the full US state. The markets re-anchor when newer real data arrives and keep their shocks. |

## Bond conventions (engine, Phase 2)

Each convention is defined in `engine/src/sovereign_engine/bonds/conventions.py`, with its sources and the date it was checked.

| Market | Instrument | Convention |
|---|---|---|
| US | Treasury notes/bonds | ACT/ACT ICMA, semiannual. The end-of-month rule applies when maturity is a month end. Street convention compounds the first fractional period. |
| US | Treasury auction awards | 31 CFR 356 App. B §II.D: (P + A)[1 + (r/s)(i/2)] = C/2 + (C/2)aₙ + 100vⁿ. A is rounded to 5 decimals per $1,000 before subtracting; P is published to 6 decimals. |
| US | Treasury bills | Bank discount on ACT/360. The investment rate uses 365 days, or 366 if the year after issue contains 29 February. Bills with more than half a year to run use the quadratic. |
| India | Dated G-secs | 30/360, semiannual (RBI primer Q25). The European 30/360 variant (Excel basis 4) is used, as RBI's Excel guidance implies. |
| India | T-bills | Implicit yield (100 − P)/P × 365/D. |

Simplifications:

- **Final coupon period.** When one cash flow remains it is discounted with simple interest under both conventions (SIA/Excel and App. B practice).
- **Odd coupons.** Odd first coupons (short or long) are not modelled. Pricing starts from the regular schedule rolled back from maturity, which is exact for secondary trading after the first coupon and for every TreasuryDirect issue in the test snapshot.
- **Unadjusted dates.** Coupon dates are not business-day adjusted. Payments slip to the next business day, but accrual runs between the unadjusted dates.
- **Settlement lag.** T+1 for US Treasuries is secondary-market practice. App. B does not specify it.
- **Risk measures.** Analytic duration, convexity and DV01 for dated bonds use the compound convention. `effective_risk` gives finite-difference measures under either convention.

## Curves (engine, Phase 2)

- **Bootstrap.**
  - Input: bond-equivalent par yields, linearly interpolated in tenor onto the semiannual coupon grid.
  - Tenors of up to one coupon period are money-market points with simple interest.
  - Interpolation between knots is log-linear in discount factors (piecewise-flat forwards).
  - Forwards are extrapolated flat at both ends.
- **NSS.**
  - Parameterisation: Gürkaynak–Sack–Wright (2007), fitted to continuously compounded zero rates.
  - Constraints: β₀ ≥ 0, β₀ + β₁ ≥ 0 and τ₁ < τ₂ (with a 0.05-year gap).
  - Fitting: a (τ₁, τ₂) grid with bounded linear least squares for β, then a polish of one seed per τ₁ row. Polishing only the global top seeds was tested and rejected: on the 2002 GSW curve all of them sat in a wrong basin, leaving a 0.6 bp error.

## Short-rate models (engine, Phase 2)

- **Vasicek and CIR.** Both use exact transitions: a Gaussian OU step for Vasicek and a scaled noncentral χ² draw for CIR. CIR bond prices are evaluated in an overflow-safe form.
- **Hull–White 1F.** The short rate is r = x + α(t), with x a zero-mean OU process (Brigo–Mercurio §3.3), so it reprices the initial curve exactly. θ(t) needs the forward-curve slope. It is exact for NSS curves and a finite difference otherwise. On a piecewise-flat curve, θ is not meaningful at the knots; α and bond prices still are.
- **Corridor rates (WACR, EFFR).** A logit-OU process keeps the rate strictly inside (L, U) by construction and reverts its median to the target. The logit volatility is set by the delta method from a target rate volatility.
