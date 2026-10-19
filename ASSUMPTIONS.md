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

## India data sources (backend, Phase 5)

Values are stored as published: amounts in ₹ crore, rates in %. Series IDs are `rbi/…`, `rbi/mmo/…`, `fbil/…` and `nsdl/fpi/…`.

| Source | What | Notes |
|---|---|---|
| RBI homepage | Policy repo, SDF, MSF, Bank Rate, fixed reverse repo, CRR, SLR; FBIL's INR/USD reference rate | Rates are stamped with the IST date the page is read, as the rates in force that day. The reference rate keeps the page's own "as at 1.00pm of <date>", and is a week fresher than FBIL's public JSON. The box's T-bill cut-offs are not stored: they carry no auction date (its "as on" footnote belongs to the G-sec yields) |
| RBI Money Market Operations | A release for every calendar day since 2024 (in 2022–23 most 2nd and 4th Saturdays and a few holidays have none): WACR with volume and range; TREPS, market repo, notice and term money; RBI's operations; net liquidity; banks' cash balances and the CRR requirement; government surplus cash; net durable liquidity | Crawled from 8 Apr 2022, when the SDF became the corridor floor. The press-release page lists only about the latest ten days; earlier days are listed month by month through the archive (an ASP.NET form). One request a second. CCIL's segments come from here: the release's footnote reads "Based on RBI / CCIL" |
| FBIL | T-bill benchmarks 7D–12M, overnight MIBOR, INR/USD reference rate | The public JSON the FBIL site itself reads (`/wasdm/<product>/fetchfiltered?authenticated=false`), in 31-day windows. The public data runs about a week behind: on 20 Oct 2026 it ended at 12 Oct. Over a holiday MIBOR is fixed for the whole break (a "4D" fixing, say); it is stored as that day's overnight rate |
| NSDL | Daily FPI net investment by class (equity, debt by route, hybrid, total), ₹ crore and US$ million | Current month only. NSDL's archive arrives with the linkage work (Phase 9) |

How a Money Market Operations release is read:

- **Facility amounts are stocks.** MSF, SDF, VRR, VRRR and the legacy long-term repos (LTRO, TLTRO, SLTRO) are summed over today's operations and the earlier ones still outstanding, so a Friday's 3-day SDF still counts on the Sunday. Read this way, the release's own net-liquidity row F equals MSF + VRR + long-term repos + SLF − SDF − VRRR to the crore. It holds on 1,595 of the 1,596 releases in the seed (8 Apr 2022 to 18 Oct 2026). The exception is 23 Dec 2024: RBI printed a ₹1,50,004 cr fine-tuning repo on the sub-header row, and the parser does not guess its direction, so VRR is understated that day.
- **Holidays.** Releases cover weekends and holidays too, because the SDF and MSF never close. On Sundays, bank holidays and non-working Saturdays the money markets are shut: volumes are 0 and no rates are stored.
- **Dates.** Values RBI dates separately keep their own "as on" date: cash balances (the release day), government surplus cash (0–4 days earlier) and net durable liquidity (13–33 days earlier). Releases write dates both as "October 24, 2023" and as "24/10/2023".
- **WACR leaves the corridor.** Of 1,214 trading days, real WACR printed below the SDF rate on 257 (222 of them in surplus, with RBI absorbing net) and above the MSF rate on 80 (66 in deficit, 50 of them in 2023). The widest gaps are thin Saturday sessions, policy-change days and financial-year ends: on 31 Mar 2023 WACR was 7.37% against an MSF of 6.75%.
- **Aggregate NDTL** is implied by the fortnight's reserve requirement: NDTL = CRR requirement ÷ CRR. For the fortnight ending 31 Oct 2026 that is ₹8,33,309 cr ÷ 3% ≈ ₹278 lakh crore.
- **Refresh.** Daily, IST: RBI 10:30, FBIL 18:15, NSDL 20:30. RBI looks back 7 days and FBIL 30, so a daily refresh never crawls the archive. A release never changes once published, so a copy saved by an earlier crawl is parsed rather than downloaded again.

Not yet, and where each arrives: MOSPI CPI and RBI's MPC decision history in Phase 8 (CPI was rebased to 2024 = 100 in Feb 2026 and must be chain-linked); FBIL G-sec par yields in Phase 7; RBI's Weekly Statistical Supplement (forex reserves, currency in circulation) and NSDL's history in Phase 9.

## Indian banks and RBI rules (engine, Phase 5)

**Rules** (`sovereign_engine/india/rules.py`), each checked against its source on 2026-10-20. CRR and SLR themselves come from RBI's data, never from code.

| Rule | Value | Source |
|---|---|---|
| Call/notice borrowing, scheduled commercial banks (incl. foreign banks and SFBs) | 100% of capital funds as a fortnightly daily average; 125% on any day | RBI/2021-22/61, Call, Notice and Term Money Markets Directions (25 Jun 2021), Table 1 |
| Call/notice borrowing, primary dealers | 225% of net owned funds, fortnightly average | same |
| Term money | within board-approved limits | same |
| Lending | RBI sets **no** limit; banks lend within board-approved internal limits. The model's 25% (fortnightly average) and 50% (any day) of capital funds are an **assumption**, the brief's figures | same |
| CRR | the fortnightly average must reach CRR × NDTL; the daily minimum is 99% of the requirement from the fortnight beginning 16 Oct 2026 (90% before), for all scheduled banks | RBI/2026-27/290 (9 Oct 2026) |
| MSF | banks may dip into the SLR by up to 2% of NDTL (restored from 3% on 1 Jan 2022); standalone PDs have no MSF access | RBI/2021-22/138 |

The participation check runs on every trade: it rejects a trade that would take the day's outstanding over the daily cap, or put the fortnight's daily average over the average cap even if every remaining day carried nothing. The rejection says which cap and by how much.

**Bank universe (SYNTHETIC).** 40 institutions with generic codes: 12 PSB, 16 PVT, 6 FGN, 4 SFB and 2 standalone PDs. Their NDTL adds up exactly to the real aggregate above. Everything else is illustrative and not fitted to any bank's data:

| Item | Choice |
|---|---|
| Group share of NDTL | PSB 55%, PVT 39%, FGN 4.5%, SFB 1.5% |
| Size within a group | lognormal, σ = 0.8, rescaled to the group's share; PSB-01 is the largest |
| Capital funds / NDTL | PSB 8.5%, PVT 13%, FGN 10%, SFB 14% |
| SLR holdings | the SLR plus 2.25–6.75% of NDTL (uniform); the excess backs repo and MSF |
| Primary dealers | NDTL 0; net owned funds ₹1,500–4,000 cr (uniform) |

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
