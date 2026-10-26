# Assumptions

Every modelling assumption in SovereignDesk, and what is real data versus simulated, in the order the phases built them. The plan and the decisions taken along the way are in [docs/PLAN.md](docs/PLAN.md); the walk-through is [DEMO.md](DEMO.md).

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
| Clock | One wall-clock second is one simulated minute (SPEED changes this). Ticks run at 4 Hz, and each tick message carries the full US state. The US market itself steps once per simulated minute, on a fixed grid from the run's start (since Phase 13), so its path depends on simulated time and not on how the ticks happen to fall. The markets re-anchor when newer real data arrives and keep their shocks. |

## India data sources (backend, Phase 5)

Values are stored as published: amounts in ₹ crore, rates in %. Series IDs are `rbi/…`, `rbi/mmo/…`, `fbil/…` and `nsdl/fpi/…`.

| Source | What | Notes |
|---|---|---|
| RBI homepage | Policy repo, SDF, MSF, Bank Rate, fixed reverse repo, CRR, SLR; FBIL's INR/USD reference rate | Rates are stamped with the IST date the page is read, as the rates in force that day. The reference rate keeps the page's own "as at 1.00pm of <date>", and is a week fresher than FBIL's public JSON. The box's T-bill cut-offs are not stored: they carry no auction date (its "as on" footnote belongs to the G-sec yields) |
| RBI Money Market Operations | A release for every calendar day since 2024 (in 2022–23 most 2nd and 4th Saturdays and a few holidays have none): WACR with volume and range; TREPS, market repo, notice and term money; RBI's operations; net liquidity; banks' cash balances and the CRR requirement; government surplus cash; net durable liquidity | Crawled from 8 Apr 2022, when the SDF became the corridor floor. The press-release page lists only about the latest ten days; earlier days are listed month by month through the archive (an ASP.NET form). One request a second. CCIL's segments come from here: the release's footnote reads "Based on RBI / CCIL" |
| FBIL | T-bill benchmarks 7D–12M, overnight MIBOR, INR/USD reference rate | The public JSON the FBIL site itself reads (`/wasdm/<product>/fetchfiltered?authenticated=false`), in 31-day windows. The public data runs about a week behind: on 20 Oct 2026 it ended at 12 Oct. Over a holiday MIBOR is fixed for the whole break (a "4D" fixing, say); it is stored as that day's overnight rate |
| FBIL G-sec | The daily G-sec valuation's par-yield curve (3M to 30Y stored) | Phase 7: see the G-sec curve section below |
| NSDL | Daily FPI net investment by class (equity, debt by route, hybrid, total), ₹ crore and US$ million | Daily from January 2014: the current month's report, earlier months through NSDL's archive form (one request per month). The classes changed over the years: equity and one debt class until 2019, then the VRR (2019), hybrid, the FAR (reported inside debt until September 2024), mutual funds and AIFs. Each day's classes add up to its total; the archive's monthly and yearly totals and its derivatives table are not read |
| RBI Weekly Statistical Supplement | Foreign exchange reserves: total, foreign currency assets and gold (US$ million), weekly | From the weekly press release "Bulletin Weekly Statistical Supplement – Extract", table 2: 668 weeks from Dec 2013. Dates are printed as "January 24, 2014", "April 1 2016" or "Aug. 29, 2025" |

How a Money Market Operations release is read:

- **Facility amounts are stocks.** MSF, SDF, VRR, VRRR and the legacy long-term repos (LTRO, TLTRO, SLTRO) are summed over today's operations and the earlier ones still outstanding, so a Friday's 3-day SDF still counts on the Sunday. Read this way, the release's own net-liquidity row F equals MSF + VRR + long-term repos + SLF − SDF − VRRR to the crore. It holds on 1,595 of the 1,596 releases in the seed (8 Apr 2022 to 18 Oct 2026). The exception is 23 Dec 2024: RBI printed a ₹1,50,004 cr fine-tuning repo on the sub-header row, and the parser does not guess its direction, so VRR is understated that day.
- **Holidays.** Releases cover weekends and holidays too, because the SDF and MSF never close. On Sundays, bank holidays and non-working Saturdays the money markets are shut: volumes are 0 and no rates are stored.
- **Dates.** Values RBI dates separately keep their own "as on" date: cash balances (the release day), government surplus cash (0–4 days earlier) and net durable liquidity (13–33 days earlier). Releases write dates both as "October 24, 2023" and as "24/10/2023".
- **WACR leaves the corridor.** Of 1,214 trading days, real WACR printed below the SDF rate on 257 (222 of them in surplus, with RBI absorbing net) and above the MSF rate on 80 (66 in deficit, 50 of them in 2023). The widest gaps are thin Saturday sessions, policy-change days and financial-year ends: on 31 Mar 2023 WACR was 7.37% against an MSF of 6.75%.
- **Aggregate NDTL** is implied by the fortnight's reserve requirement: NDTL = CRR requirement ÷ CRR. For the fortnight ending 31 Oct 2026 that is ₹8,33,309 cr ÷ 3% ≈ ₹278 lakh crore.
- **Refresh.** Daily, IST: RBI 10:30, FBIL 18:15, FBIL's G-sec workbooks 20:00, NSDL 20:30. RBI looks back 7 days, FBIL 30 and the G-sec workbooks 14, so a daily refresh never crawls an archive. A release or workbook never changes once published, so a copy saved by an earlier crawl is parsed rather than downloaded again.

MoSPI's CPI and GDP and RBI's policy record arrived with the MPC predictor (Phase 8), and NSDL's history and RBI's weekly reserves with the linkage (Phase 9); both are described below. RBI's monthly intervention data is not used (see the linkage's limitations), and neither is currency in circulation.

## Indian banks and RBI rules (engine, Phase 5)

**Rules** (`sovereign_engine/india/rules.py`), each checked against its source on 2026-10-20. CRR and SLR themselves come from RBI's data, never from code.

| Rule | Value | Source |
|---|---|---|
| Call/notice borrowing, small finance banks | 100% of capital funds as a fortnightly daily average; 125% on any day | Call, Notice and Term Money Markets Directions, 2021, Table 1, as amended on 8 Jun 2023 (FMRD.DIRD.02/14.01.001/2023-24) |
| Call/notice borrowing, other scheduled commercial banks (incl. foreign banks) | Since 8 Jun 2023, board-approved limits inside the prudential limits for inter-bank liabilities. The model keeps the 100% and 125% of capital funds RBI set before as those board limits: an **assumption** | same |
| Call/notice borrowing, primary dealers | 225% of net owned funds, fortnightly average | same |
| Term money | within board-approved limits | same |
| Lending | RBI sets **no** limit; banks lend within board-approved internal limits. The model's 25% (fortnightly average) and 50% (any day) of capital funds are an **assumption**, the brief's figures | same |
| CRR | the fortnightly average must reach CRR × NDTL; the daily minimum is 99% of the requirement from the fortnight beginning 16 Oct 2026 (90% before), for all scheduled banks | RBI/2026-27/290 (9 Oct 2026) |
| MSF | banks may dip into the SLR by up to 2% of NDTL (restored from 3% on 1 Jan 2022); standalone PDs have no MSF access | RBI/2021-22/138 |
| Reporting fortnight | the 1st-15th and the 16th to the month's end since 16 Dec 2025 (13-15 Dec 2025 a transition period); Saturday to the second following Friday before | RBI/2025-26/148 (11 Dec 2025) |
| CRR history (for NDTL in the fits) | 4.00% until 20 May 2022, 4.50% from 21 May 2022, 4.25% from 14 Dec 2024, 4.00% from 28 Dec 2024, then 3.75%, 3.50%, 3.25% and 3.00% from 6 Sep, 4 Oct, 1 Nov and 29 Nov 2025 | RBI/2022-23/46, RBI/2024-25/95, RBI/2025-26/46 |
| Incremental CRR | 10% on NDTL growth between 19 May and 28 Jul 2023, released 9 Sep-7 Oct 2023: requirement ÷ CRR overstates NDTL then, so 10 Aug-20 Oct 2023 is left out of the fits | Press release 2023-2024/886 |
| VRR / VRRR auctions | multiple-price: VRR bids ranked by rate descending and VRRR ascending, cut-off where the notified amount fills, each winning bid at its own rate, pro rata at the cut-off; VRR bids at or below repo and VRRR bids at or above it rejected; minimum bid ₹1 crore | Press releases 2021-2022/1572 (VRR) and 2019-2020/1947 (VRRR) |

The participation check runs on every order: an order that would take the day's outstanding over the daily cap, or put the fortnight's daily average over the average cap even if every remaining day carried nothing, is trimmed to the room left and the trimmed amount is logged with the reason. A position taken on a Friday counts for Saturday and Sunday too, because non-working days carry the previous day's balance.

**Bank universe (SYNTHETIC).** 40 institutions with generic codes: 12 PSB, 16 PVT, 6 FGN, 4 SFB and 2 standalone PDs. Their NDTL adds up exactly to the real aggregate above. Everything else is illustrative and not fitted to any bank's data:

| Item | Choice |
|---|---|
| Group share of NDTL | PSB 55%, PVT 39%, FGN 4.5%, SFB 1.5% |
| Size within a group | lognormal, σ = 0.8, rescaled to the group's share; PSB-01 is the largest |
| Capital funds / NDTL | PSB 8.5%, PVT 13%, FGN 10%, SFB 14% |
| SLR holdings | the SLR plus 2.25–6.75% of NDTL (uniform); the excess backs repo and MSF |
| Primary dealers | NDTL 0; net owned funds ₹1,500–4,000 cr (uniform) |

## India simulator (Phase 6)

**Anchors.** Every starting value comes from stored real data (`backend/app/sim/india_anchors.py`), and a missing input stops the build:

- repo, SDF, MSF, CRR and SLR from RBI's homepage
- from the latest Money Market Operations release: net absorption, VRR and VRRR outstanding, the CRR requirement (hence NDTL), WACR and net durable liquidity
- FBIL's 3M, 6M and 12M T-bill benchmarks

**Fitted to data**, again each time the anchors are built. Values on the October 2026 seed:

| Item | Fit |
|---|---|
| Macro map | WACR − repo against surplus as % of NDTL, on weekdays from 8 Apr 2022 to 17 Oct 2026 (I-CRR weeks left out). Repo each day is the midpoint of the SDF and MSF rates, which sit at repo ∓ 25 bp on every day of the data. Logistic: deficit +25.3 bp, surplus −45.2 bp, midpoint 0.79%, width 0.95 point; RMSE 17.4 bp over 1,045 days |
| Daily deviation | Each day's WACR deviates from the map by an AR(1) (ρ = 0.29, from the fit's residuals) whose innovations are resampled from the 1,044 historical ones, downward ones scaled by 0.93 and upward ones by 1.14. The two scales are solved so that, run over the historical liquidity path, the share of weekdays below the SDF and above the MSF matches RBI's releases (see WACR modes below) |
| Other segments | Last year's medians against WACR: TREPS −14 bp, market repo −12 bp, notice −5 bp, term +54.5 bp. Volumes as multiples of call volume: TREPS 27.7×, market repo 11.3× |
| Tax cycle | The median fall in surplus across the 13th-17th of Mar, Jun, Sep and Dec (advance tax) is ₹1.28 lakh crore, and across the 18th-22nd of other months (GST) ₹88,000 crore, over 54 episodes. Measured: 3% of an advance-tax drain back after 10 days, 73% after 20. Simulated: each drain is spread over its five days, held for 10 days, then returned evenly over 14 |
| Autonomous noise | A mean-reverting (OU) component of system liquidity with a daily s.d. of ₹23,900 crore: 1.4826 × the median absolute daily change away from tax dates. The 30-day half-life is an assumption |
| NDTL growth | 11.8% a year (implied NDTL over the last year), applied at each fortnight start |
| RBI's reaction | Logistic regressions of "a new VRR (VRRR) was held" on the previous day's surplus ℓ: VRR p = 1/(1 + e^−(−2.20 − 1.05ℓ)) from 136 such days, VRRR p = 1/(1 + e^−(−2.80 + 0.52ℓ)) from 128. Each runs at the median size of new operations (₹34,500 crore and ₹33,500 crore), overnight |
| T-bills | FBIL's 3M, 6M and 12M benchmarks (a week behind; see above), moved by repo through the G-sec pass-through β (1, 0.95 and 0.86 at 3, 6 and 12 months; one for one when the G-sec curve is unavailable) and by the fitted slope of T-bill − repo on surplus: 3M −8.8 bp and 6M −3.5 bp per point of NDTL. The 12M fit (+4.9 bp) has the wrong sign, mixing in rate expectations, and is set to zero |

**Assumptions, not fitted (all in `IndiaModelParams`).**

| Item | Choice |
|---|---|
| Calendar | Business days are Monday to Friday; there is no holiday calendar. Clearing rounds every 15 minutes from 09:15 to 19:00 IST, RBI's auctions at 09:30, the SDF and MSF at 19:00 every day, CRR accounting at 23:59. The hours are RBI's, in `sovereign_engine.india.rules` with VERIFY: call money trades 9:00 AM to 7:00 PM from 1 Jul 2025 (RBI Bulletin, 23 Jul 2025, footnote 15; 5:00 PM before), and the SDF and MSF open at 7:00 PM (press release 2025-2026/625, 30 Jun 2025; 5:30 PM before). Phase 12 moved the simulator from the old hours |
| Call market | A uniform-price auction each round, settling at the midpoint of the marginal bid and offer. Reservation rates are the map rate plus the day's deviation, round noise (8 bp) and bank noise (5 bp), leaning up to 10 bp toward the facilities by the close. They are bounded by the mode's band (below). Banks offer gap × min(1, 1.5 / rounds left) each round |
| Banks' own positions | Zero-sum and mean-reverting: a stationary s.d. of 0.6% of each bank's NDTL and a 10-day half-life, so somebody can lend even when the system is short. Call volume runs high: over ten runs of 90 simulated days from the October 2026 anchors the median weekday volume is ₹22,000 crore, against ₹16,100 crore in RBI's releases over the year to 18 Oct 2026 (re-checked in Phase 12; it was ₹17,500 crore on the Phase 6 seed). An s.d. of 0.52% would match the volume, but then the call market falls silent once the system is short by about 1.3% of NDTL, a deficit the data has seen. System-wide flows are shared by NDTL |
| CRR behaviour | Each bank aims for the balance that still meets the fortnight average, never below the daily floor. In the evening surplus goes to the SDF and deficit to the MSF, up to excess SLR plus 2% of NDTL; what the MSF cannot cover leaves the bank short (flagged) |
| Primary dealers | Borrow 1 × net owned funds of call money each business day; the cash pays for securities and returns to banks by NDTL; the loans are repaid the next business day |
| Opening position | Banks start at their requirement, with the release's SDF − MSF residual and its VRRR shared by NDTL plus their own positions. The release gives the VRRR total but not maturities, so it is assumed to mature in a week |
| Not modelled | Interest on reserves and loans (balances move by principal only); currency in circulation; FX intervention and OMOs except through the linkage (`SHOCK FED`, Phase 9); bank holidays. The India market re-anchors to new RBI data on RESET only |

**WACR modes.** `WACR REALISTIC` (the default) or `WACR POLICY` switches; the WACR panel has the same toggle.

- *Realistic*: WACR may leave RBI's corridor, as it does in the data. Of 1,214 trading days since 8 Apr 2022, WACR printed below the SDF rate on 257 and above the MSF rate on 80. Thin Saturday sessions account for 106 and 10 of those; the simulator trades Monday to Friday, so the calibration target is the weekdays: 151 below and 70 above of 1,045 (14.4% and 6.7%). Over the historical liquidity path, the calibrated deviations give 14.3% and 6.9%. Prints are bounded by the furthest WACR has gone: 113 bp below the SDF and 140 bp above the MSF.
- *Policy*: reservation rates are clamped to [SDF, MSF], so WACR cannot leave the corridor: the plan's original design, and RBI's operating intention.

**Known limitations.**

- *RBI's fine-tuning auctions barely move the map.* The map's liquidity is RBI's whole net position, operations included, because that fits better: on the overnight part alone (SDF − MSF) the RMSE is 17.9 bp against 17.4. So a VRR that only replaces MSF borrowing leaves the map where it was, and its effect on WACR comes only through the call market itself, by changing who still needs to borrow. In the simulator, repo moves, CRR changes and tax days move WACR more than VRR and VRRR auctions do.
- *Deep deficits can silence the call market.* Banks' own positions have a stationary s.d. of 0.6% of NDTL, so when the system is short by much more than about 1.5% of NDTL every synthetic bank is short, nobody lends, and the shortfall goes to the MSF. The data's deepest deficit was 1.7%.
- *T-bills are a week old.* FBIL's public data runs about a week behind, so the T-bill anchors are flagged STALE in the WACR panel and on the ticker whenever their own date is more than 3 days old (`stale_after_days`). The G-sec curve is flagged the same way.

Commands: `REPO ±25BP` moves repo, SDF and MSF together at once; `CRR 3.5` takes effect from the next reporting fortnight; `VRR 50000CR 7D` and `VRRR …` run at 09:30 or the next round, with banks bidding their gaps in a multiple-price auction.

## India G-sec curve (Phase 7)

**Data.** FBIL's daily G-sec valuation workbook ("FBIL GOI Prices including Par Yield, Special and Note on FRB and IIB"), sheet "Par Yield": FBIL's base/par yield curve every quarter year out to 40–50 years, semi-annual par yields except the 3-month point, which is a simple (money-market) yield. Workbooks are downloaded anonymously from `/wasdm/gsec/downloadPublished?date=…`; `/wasdm/gsec/fetchfiltered` lists the dates published in a window. Values are stored as published (%), at 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 14Y, 20Y and 30Y (`fbil/gsec/par/<tenor>`).

- *Coverage.* Daily from 13 Feb 2023, FBIL's first .xlsx workbook. Before that FBIL served legacy .xls files of about 0.75 MB each (a "Par-Yield" sheet, more decimals), so for 2022 and early 2023 only the publications around each repo change are fetched: the one before, the day, the one after. The seed has 902 days per tenor, to 13 Oct 2026.
- *Crawl.* One request a second. A workbook never changes once published, so a saved copy is parsed instead of downloaded again. A workbook whose printed date differs from the one requested is refused.
- *Lag.* Like FBIL's other public data, about a week behind: on 20 Oct 2026 the latest workbook was 13 Oct. The GSEC panel shows a STALE badge when the curve's date is more than 3 days old.
- *Conventions check* (engine test): bootstrapping FBIL's par curve with these conventions reproduces FBIL's own published zero-coupon curve (the ZCYC sheet of its STRIPS workbook) on 12 Oct 2026 within 0.7 bp RMSE, and 2.0 bp at worst, out to 30 years.

**The curve.** The market points are the 91, 182 and 364-day T-bills at FBIL's T-bill benchmarks (the money market's, so the same numbers as the WACR panel), then FBIL's par yields from 2Y to 30Y. FBIL's par curve has its own 3, 6 and 12-month points, values of its fitted curve that can differ from the benchmarks by several basis points: the event study uses them (one curve from one source), the live curve uses the bills. The two can carry different dates (12 and 13 Oct 2026 on the seed). Nelson–Siegel–Svensson is fitted to the eleven points as quotes, bills at their simple yield (ACT/365) and bonds at par with semi-annual coupons, by bounded least squares on the yield errors: cold when the anchors are built, then warm-started from the last fit on every update (about 2 ms). On the seed the fit is within 2.9 bp RMSE of the points. NSS is smoother than FBIL's own curve: fitted to the eleven quoted tenors on 12 Oct 2026, it is within 9 bp RMSE (17 bp at worst) of FBIL's zero curve, which wiggles between them.

**Repo pass-through: the event study** (`sovereign_engine/india/passthrough.py`).

- *Events.* Every day the repo rate changed since 8 Apr 2022: 11 of them (six hikes from May 2022 to Feb 2023, cuts in Feb, Apr, Jun and Dec 2025, a hike on 7 Oct 2026). Repo each day is the midpoint of the SDF and MSF in RBI's releases. Each par yield's move is measured from FBIL's previous publication to the event day's close. The MPC announces in the morning; the intermeeting hike of 4 May 2022 came at 2 pm, and its 1-year point moved only the next day.
- *Same-day slopes* on the actual change, b(τ) = Σ Δr·Δy(τ) / Σ Δr²: 0.20 at 3 months, 0.15 at 1 year, 0.13 at 10 years and 0.09 at 30 years. They are small because most changes were expected and priced before the meeting.
- *Response per unit of policy surprise*, ρ(τ) = b(τ) / b(3M): the 3-month yield's move measures the surprise and the actual change instruments it, so day-to-day noise in the 3-month yield does not bias the ratio towards zero. 1 at 3 months by construction, 0.80 at 6 months, 0.76 at 1 year, 0.73 at 2 years, 0.65 at 10 and 0.46 at 30.
- *Uncertainty.* 2,000 bootstrap resamples of the 11 events give 90% bands, e.g. 0.24–1.94 at 2 years and 0.10–1.45 at 10. They are wide: the events are few, and the 4 May 2022 surprise weighs heavily (without it ρ at 10 years is 0.44).
- *Fit.* β(τ) = (A(τ; κ) + γ·T(τ)) / (A(3M; κ) + γ·T(3M)). Here A(τ; κ) = (1 − e^(−κτ))/(κτ) is the expected path of a surprise that fades at rate κ, and T(τ) = (1 − e^(−τ/7))/(1 − e^(−10/7)) is a term-premium loading (the US curve's, scale 7 years, an assumption). Weighted least squares, weights 1/s.d.² from the bootstrap. κ = 0.62 a year, a half-life of 1.1 years (band 0.07 to the bound of 5); γ = 0.35 (band −0.04 to 0.63). The fitted β is 1.00 at 3 months, 0.95 at 6 months, 0.86 at 1 year, 0.73 at 2 years, 0.58 at 5, 0.54 at 10 and 0.54 at 30; at 10 years 0.17 of it is expectations and 0.37 term premium. Band for β at 10 years: 0.06–1.26.
- *Use.* A repo change moves the T-bills by β at their maturity and each coupon tenor by β(τ)·Δrepo, at once: the simulator treats it as a surprise. Hold decisions are not in the sample, and with the actual change as the instrument they would carry no weight (Δrepo = 0); neither the partly expected part of a change nor a path signal (June 2025's −50 bp came with a neutral stance, and the 10-year rose 4 bp) is modelled separately.

**Day-to-day moves.** Two factors with the pass-through's own loadings, expectations A(τ; κ) and term premium T(τ), move the coupon tenors. Their daily shocks come from regressing each day's par-yield changes (2Y to 30Y) on the two loadings over 880 days of FBIL's daily coverage, repo-change days left out: an s.d. of 5.3 bp a day for the expectations factor (whose loading is 0.57 at 2 years and 0.16 at 10) and 1.8 bp for the term premium (one at 10 years), correlation +0.27. What the two loadings leave unexplained, 1.5 bp RMS per tenor and day, is not simulated. The factors step with every clearing round (09:15–17:00 IST on business days) as OU processes with a half-life of 125 business days, about six months: an **assumption** (`GsecParams.factor_half_life_days`). Without news the curve so drifts back to FBIL's close plus the policy moves. The bills move with the money market only (repo and liquidity).

**SPRD.** FBIL's 10-year par yield against Treasury's 10-year par yield (both semi-annual), on the dates both published: 853 days from 7 Feb 2023 to 13 Oct 2026 on the seed, during which the spread fell from 361 bp to 218 bp. In the simulation each business day's G-sec close (23:59 IST) is paired with the US 10-year at that moment, and the panel adds the live spread. The two markets move each other only through the US → India chain (`SHOCK FED`, `LINK`; Phase 9).

**Invariants** (every tick): every point is finite and between −5% and 50%, and the NSS refit stays within 25 bp RMSE of the points.

## MPC predictor (Phase 8)

The full backtest, every forecast and the forecast for the next meeting are in [docs/MPC_BACKTEST.md](docs/MPC_BACKTEST.md), generated from the seed by `py tasks.py mpc-report`.

**Data.**

| Source | What | Notes |
|---|---|---|
| RBI press releases (`rbi_policy`) | Every repo decision since 1 Apr 2014; the MPC's meeting schedules and the notices that move a meeting; the 91-day T-bill cut-off of the last auction before each decision; and, until 8 Apr 2022, WACR, call volume, net liquidity and the CRR requirement from the Money Market Operations releases of the 14 days before each decision | Listed month by month through the press-release archive from Jan 2014, one request a second; a release never changes, so saved copies are parsed again rather than downloaded. Stored as `rbi/mpc/…`, `rbi/tbill91/cutoff` and `rbi/hist/…`. From 8 Apr 2022 the daily Money Market Operations series (Phase 5) take over |
| MoSPI (`mospi`) | All-India CPI (rural + urban): base 2012 general index, its six groups and inflation from Jan 2013; base 2024 general index, its 12 COICOP divisions, the housing groups 04.1–04.5 and inflation from Jan 2025. Quarterly GDP at constant prices and its growth, bases 2011-12 and 2022-23 | Through MoSPI's official MCP server (`mcp.mospi.gov.in`), the machine-access route MoSPI's `llms.txt` and agent manifest name. The website (www.mospi.gov.in, cpi.mospi.gov.in) failed TLS revocation checks (CRYPT_E_REVOKED) when this was built and is not used; its REST API returns at most 10 records without registration. Values as published: indices, % year on year, ₹ crore |
| FRED | Effective federal funds rate (`DFF`); rupees per dollar, the Fed's H.10 noon rate in New York (`DEXINUS`) | From the Phase 3 seed |

How RBI's record is read:

- *Decisions.* The decision releases are the MPC's resolutions (from 4 Oct 2016), the Governor's bi-monthly policy statements before them, and his statements on the intermeeting cuts of 15 Jan and 4 Mar 2015. The repo rate comes from the sentence that sets it: "keep (maintain, retain, leave) the policy repo rate unchanged at 6.50 per cent", "reduce the policy repo rate by 25 basis points from 6.50 per cent to 6.25 per cent". Releases that announce a statement, minutes and schedules are not decisions.
- *Off-cycle decisions.* A decision is scheduled if its day is a meeting's decision day in RBI's schedules (from 2017-18), or, before April 2017, if it came in a bi-monthly statement. Five are off-cycle: 15 Jan and 4 Mar 2015, 27 Mar and 22 May 2020, and 4 May 2022.
- *Meeting calendar.* A yearly schedule's table gives each meeting's days, and the decision comes on the last. A notice that moves a meeting gives its new days after the old ones ("rescheduled to August 4 – 6, 2025", "will now be held on June 4-6, 2018"). Releases are read in the order RBI issued them, and a day within 14 days of a known meeting replaces it. The next meeting is the first calendar day on or after today: 4 Dec 2026 on the seed.
- *T-bills.* The cut-off yield of the last weekly 91-day auction strictly before the decision day (the decision-day auction closes after the morning announcement). If RBI rejected every bid, as on 25 Mar 2026, the auction before counts.
- *Money markets before 8 Apr 2022.* Amounts were printed in ₹ billion until 2019 and are converted to ₹ crore. Net liquidity was printed only from mid-2019; before that it is summed from the LAF legs as RBI's later footnote defines it, repo + MSF + SLF − reverse repo, which matches the printed figure in Aug 2019. Surplus is −net liquidity ÷ NDTL, and NDTL = CRR requirement ÷ the CRR in force (`CRR_SCHEDULE`, from Feb 2013), leaving out the incremental-CRR fortnights (Nov–Dec 2016 and Aug–Oct 2023).

**Features**, each as known the day before the decision:

| Feature | Definition |
|---|---|
| CPI inflation | MoSPI's year-on-year rate for the latest month released. A month's CPI comes out on the 12th of the next and counts from the 13th. Base 2012 to Dec 2025, base 2024 from Jan 2026 |
| Core inflation | CPI excluding food and beverages and fuel and light (base 2024: division 01 and group 04.5), year on year (below) |
| WACR − repo | Mean over the weekdays of the 14 days before, each against the repo then in force (bp) |
| T-bill − repo | The 91-day cut-off above against the repo on its auction day (bp) |
| System liquidity | Mean surplus over the 14 days before, % of NDTL |
| GDP growth | Real, year on year, for the latest quarter released: it counts from the first day of the third month after the quarter (MoSPI publishes at the end of the second). Base 2011-12 to Jul–Sep 2025, base 2022-23 after |
| Fed funds | DFF on the last day before, and its change over 91 days (bp) |
| Rupee | The change in DEXINUS over 91 days (%) |
| MPC era | 1 from 4 Oct 2016 (the brief's regime dummy), 0 for the Governor's decisions |
| Previous decision | The previous change (bp); unknown for the first decision in the sample |

The Taylor rule also reads the output gap: real GDP over four quarters (which removes the seasonal pattern of India's unadjusted quarterly GDP), the two bases spliced by their mean ratio where they overlap, in logs, minus a one-sided HP trend (λ = 1600, re-filtered each quarter on data up to that quarter only).

**Core CPI weights.** MoSPI's data carries no weights, so they are recovered from the indices. A fixed-base Laspeyres index is the weighted sum of its components, I = Σ wᵢ Iᵢ with Σ wᵢ = 1, so the weights are bounded least squares on the published indices. Core is then the general index with the excluded components taken out, (I − Σₑ wₑ Iₑ) / (1 − Σₑ wₑ), and its year-on-year rate. On the seed, base 2012 (146 months): food and beverages 45.91% and fuel and light 6.92%, against MoSPI's published 45.86% and 6.84%, and the other four groups within 0.06 points of theirs; the weights rebuild the general index within 0.04 index points RMSE. Base 2024 (21 months, Jan 2025 to Sep 2026): food and beverages 36.73%, against the 36.75% reported when the series was launched; electricity, gas and other fuels (04.5) 5.22%, the housing division's 17.15% times 04.5's 30.4% share of it; rebuild error 0.003 points. Core inflation joins the two bases at Jan 2026, like headline.

**Models.** Five classes: big cut (more than 25 bp), cut, hold, hike, big hike.

- *Taylor rule*, i* = r* + π + 0.5(π − π*) + 0.5·gap. The baseline moves repo a quarter of the way to i* at each decision, rounded to 25 bp steps (halves away from zero) and capped at 50 bp. It is deterministic, so its Brier score counts every miss in full.
- *Ordered logit*: a cumulative logit on standardised features, L2-penalised on the slopes (λ = 1) and fitted directly by L-BFGS with an analytic gradient. Without the penalty it reproduces statsmodels' `OrderedModel` (engine test). Missing features take the training window's mean.
- *XGBoost*: 200 trees of depth 2, learning rate 0.05, row and column subsampling 0.8, L2 leaf penalty 5; missing features go down XGBoost's learned default branch.
- A class a training window has never seen gets zero probability.

**Backtest.** Expanding window: the 25th decision onwards is forecast by models fitted only on the decisions before it. Baselines are "repeat last" (the previous decision's class) and "always hold". On the seed, 54 forecasts from 7 Feb 2018 to 7 Oct 2026:

| Forecast | Hit rate | Macro-F1 | Brier |
|---|---:|---:|---:|
| Ordered logit | 57% | 0.38 | 0.59 |
| XGBoost | 57% | 0.21 | 0.58 |
| Taylor rule | 22% | 0.21 | 1.56 |
| Repeat last | 69% | 0.52 | 0.63 |
| Always hold | 63% | 0.15 | 0.74 |

- *Neither model calls decisions better than repeating the last one.* RBI moves in runs, and both models miss the turns: the first hike of 2018 got no probability at all, because none of the 24 training decisions was a hike.
- *Both give better probabilities than either baseline* (Brier 0.58–0.59 against 0.63 and 0.74).
- *The ordered logit* called four of the five big hikes of 2022 and both emergency cuts of 2020. *XGBoost* almost always says hold.
- *The Taylor rule* is mechanical, on headline CPI. It prescribed hikes through 2020–24 while RBI held, and calls 19 of the 34 holds big hikes.
- *No tuning.* The penalty and XGBoost's settings were set before the backtest was run on the real data, and have not been tuned to it.

**Assumptions** (`MpcParams`, each with its source and check date in the code):

| Item | Choice |
|---|---|
| r* | 1.5% real, within RBI's published estimates: 1.6–1.8% (Q4 2014-15) and 0.8–1.0% (Q3 2021-22) in the RBI Bulletin of 16 Jun 2022, and 1.4–1.9% (Q4 2023-24) in its July 2024 update. **VERIFY** |
| π* | 4%, the target notified under section 45ZA of the RBI Act (2–6% band). **VERIFY** |
| Windows | 14 days of money markets before each decision; 91 days for the Fed and rupee changes |
| Penalty and start | L2 λ = 1; the first 24 decisions train the first forecast |
| Output gap | HP λ = 1600 (quarterly), one-sided |

**In the terminal.** `MPC` uses the model fitted on the stored data (refitted when the data changes) and today's features. The simulation replaces four of them: WACR − repo and liquidity from the simulated money market, the 91-day bill from the simulated 3-month T-bill (FBIL's benchmark, not an auction cut-off), and the Fed funds rate from the US simulation. The previous decision is the simulation's own repo move if there has been one.

**Known limitations.**

- *Revised data.* CPI and GDP are today's vintage, not what was printed at the time: MoSPI revises GDP for years, and final CPI replaces provisional CPI a month later. The backtest so knows slightly more than the MPC did.
- *A small sample.* 78 decisions: 51 holds, 13 cuts, 4 hikes, and 5 each of big cuts and big hikes; 54 are forecast. With four or five cases in a class, one call moves macro-F1 by several points. A class not yet seen in a training window gets no probability at all.
- *What is left out.* The MPC's stance and guidance, its minutes and votes, the government's borrowing, oil prices and forecasts of inflation (the MPC targets the forecast, not today's print).
- *The live T-bill differs from the backtest's*: FBIL's 3-month benchmark against the auction cut-off.
- *Calendar edge cases.* A meeting moved without a notice in the archive keeps its old day: June 2020's meeting, brought forward to 20–22 May, still lists 5 Jun 2020. Past days do not matter, and a missed notice could only misdate the next meeting.

## US → India linkage (Phase 9)

`LINK` shows the chain and `SHOCK FED 50BP [NONE|VRR|OMO|SWAP|HIKE] [VIX+10]` runs it end to end: the Fed moves in the US simulation, the US 10Y's own response starts the chain, and India's money market takes it from the next business day. The chain is in `sovereign_engine/linkage/chain.py`, the calibration in `backend/app/sim/linkage.py`.

    Fed → US 10Y → IN−US 10Y differential → FPI flows → RBI's dollar trades and the rupee → rupee liquidity → WACR and T-bills → RBI's response

**Data** (all in the seed):

| Series | Source | Use |
|---|---|---|
| Daily FPI net investment by class, US$ million | NSDL, from January 2014 (see India data sources) | flows, summed by month and by week |
| Foreign exchange reserves: total, foreign currency assets (FCA), gold | RBI's weekly Statistical Supplement extract, Dec 2013 on | RBI's absorption; the reserves the chain starts from |
| India 10-year G-sec yield, monthly | the OECD's, via FRED (`INDIRLTLT01STM`) | the differential, 2014 on |
| FBIL's 10-year par yield, daily | FBIL, from Feb 2023 | the spillover |
| US 10-year (`DGS10`), VIX (`VIXCLS`), broad dollar index (`DTWEXBGS`), rupees per dollar (`DEXINUS`) | FRED | the US side, risk appetite, valuation, the rupee |
| INR/USD reference rate | FBIL | the rupee the chain starts from |

**Calibration.** Each link is an OLS with Newey–West errors (3 lags monthly, 4 weekly). On the seed, with 90% intervals:

| Link | Regression | Estimate (90% interval) | Sample |
|---|---|---|---|
| Spillover | weekly ΔIN10Y on ΔUS10Y (FBIL, DGS10) | 0.16 (0.12–0.20); R² 0.13 | 191 weeks, Feb 2023–Oct 2026 |
| FPI debt flows | monthly debt flows on Δ(IN10Y − US10Y) and ΔVIX | +$0.26bn per point (−1.01 to +1.53); R² 0.04 | 152 months, Feb 2014–Sep 2026 |
| FPI equity flows | monthly equity flows on ΔUS10Y and ΔVIX | −$3.99bn per point (−6.73 to −1.26); R² 0.16 | same |
| Risk appetite | the two VIX slopes, summed | −$0.33bn per VIX point (−0.43 to −0.22) | same |
| RBI's absorption | weekly ΔFCA on weekly FPI flows and the dollar's valuation effect (ΔDTWEXBGS × last week's FCA) | 59% of each flow (40–79%); R² 0.30 | 667 weeks, Jan 2014–Oct 2026 |
| The rupee | weekly %ΔINR on weekly FPI flows and %ΔDTWEXBGS, divided by 1 − s | 0.17% weaker per US$ bn not absorbed (0.10–0.25); R² 0.17 | same |

The debt-flow slope has the expected sign but is not distinguishable from zero: in this sample debt flows were driven more by access and index changes (the FAR route from 2020, JP Morgan's index inclusion from June 2024) than by yield gaps. It is used as estimated, so the yield channel is weak and most of a Fed shock's outflow comes through equity and the VIX.

**How the chain runs** (assumptions, in `LinkAssumptions` and `LinkParams`):

| Item | Choice |
|---|---|
| Flow timing | A month's flow arrives over 21 business days, front-loaded with a 5-day half-life; the chain is followed for 30 business days |
| When India responds | From the next business day after the shock (US moves come after India's close) |
| RBI's absorption | The share s of each day's flow, at once; the rest moves the rupee |
| Rupee liquidity | Dollars RBI sells or buys × that day's rupee rate (₹ crore = US$ bn × ₹/$ × 100) |
| Money market | The liquidity map and the 3M T-bill's slope on liquidity from the India simulator (Phase 6) for the chain's preview; in the simulation itself WACR comes out of the call market as usual |
| India's 10Y | Moves by the spillover through the G-sec curve's term-premium factor, which then decays like any other move of it |
| VIX | Unchanged unless given (`VIX+10`): the Fed's effect on risk appetite is not estimated |
| Responses | VRR (VRRR after inflows): weekly 7-day auctions of the drain so far, run as real auctions in the simulator. OMO: weekly outright purchases (sales) of the drain not yet offset. Swap: a buy/sell swap on the first day for the dollars RBI expects to sell. Hike: repo +25 bp on the first day, which also lifts India's 10Y by the G-sec curve's β(10Y) and so slows the outflow |

**Accounting.** The engine checks the chain's books on every run: FPI flow = RBI's part + the market's part each day; reserves = start + RBI's trades + swaps; each day's liquidity = RBI's dollars × the rate; surplus = start + liquidity + durable injections. In the simulator the FX liquidity joins the autonomous flows, so the market's own identity (system liquidity = start + autonomous flows) still holds on every tick.

**Why VRR does not move the map.** Surplus is RBI's net liquidity position, as RBI reports it and as the map was fitted: net absorption through the LAF, VRR and VRRR included. A VRR funds a shortfall at the repo rate instead of the MSF, but leaves the net position, and so the map, where it was; OMO purchases and a buy/sell swap are durable and restore it. This is the known limitation the MVP review accepted (fine-tuning auctions barely move the map), and the simulator shows the VRR's effect only through the call market.

**On the seed.** A 50 bp Fed hike, to which the US simulation answers with +11.8 bp at 10 years: India's 10Y +1.9 bp, the differential −9.9 bp; FPI −$0.50bn over the month; RBI sells $0.30bn; the rupee 0.04% weaker; ₹2,829 crore drained (0.010% of NDTL); WACR +0.2 bp. With a 10-point rise in the VIX as well: FPI −$3.76bn, RBI sells $2.23bn, the rupee 0.27% weaker, ₹21,426 crore drained (0.077% of NDTL), WACR +1.4 bp and the 3M T-bill +0.7 bp. Weekly OMOs or a swap offset the drain; a repo hike adds 25 bp to WACR and trims the outflow by $0.04bn.

**Known limitations.**

- *Not RBI's intervention data.* RBI publishes its monthly dollar purchases and sales (the Bulletin's "Sale/Purchase of U.S. Dollar by the RBI") only as files on rbidocs.rbi.org.in, which answered with a bot challenge, so they are not used. Absorption is measured from the weekly change in foreign currency assets instead, which also moves with interest income, forward deliveries and valuation the dollar index does not capture.
- *Reduced form.* Flows, the rupee and RBI's sales are decided together (RBI leans against the rupee), so the weekly coefficients are associations over the sample, not causal estimates; the intervals are wide.
- *One shock at a time, linear.* No second round: a weaker rupee does not raise inflation or move the MPC, and India's markets do not move the US. Shocks run at the same time add up.
- *The VIX is an input.* A Fed surprise that comes with risk-off moves money mostly through the VIX link, whose size the user gives.
- *Swaps and OMOs outlast the horizon.* A buy/sell swap's forward leg and an OMO's maturity are beyond the 30 days followed.

## Retail and business impact (Module E, Phase 10)

`IMPACT` (also `IMPACT RETAIL [+100BP]` and `IMPACT BUSINESS [SHOP|IMPORTER] [+25BP] [INR+5]`) shows what the simulated moves mean for a bond investor and two small businesses. The panel's inputs can be edited; it posts them to `POST /api/impact`. The engine is in `sovereign_engine/impact/`, the calibration and presets in `backend/app/sim/impact.py`.

**The shock.** Each module's shocks reach the impact through the simulated markets, measured against the real data they were anchored to:

- the G-sec curve against FBIL's close, interpolated at each bond's maturity (a fund's at its duration);
- repo against RBI's;
- the 3-month T-bill against FBIL's benchmark;
- the rupee against FBIL's reference rate, once the linkage has moved it.

So a repo move, a CRR change, a Fed shock or a tax-day squeeze all show up. A hypothetical move can be given instead:

- a parallel yield shift (`+100BP` in the retail view), which leaves lending rates alone;
- a repo move (`+25BP` in the business view), which also moves the G-sec curve by the event study's β(τ) (Phase 7) and the 3-month bill by its β;
- a rupee move (`INR+5`, + is weaker).

**Retail investor.**

- *Bonds.* Each bond is repriced exactly from its cash flows: semi-annual coupons, the yield at its maturity on the curve plus a fixed spread for non-government bonds.
- *Funds.* A fund has no cash flows of its own, so only the duration and duration + convexity estimates from its stated modified duration and convexity are available.
- *The table.* For every holding: the exact change next to the two estimates, modified duration, convexity and DV01.
- *Hold or sell.* Held to maturity, a bond pays every coupon and its face. Its realised yield is the yield it was bought at, plus or minus the effect of reinvesting coupons at the new yield. Sold now, the price change is crystallised.
- *The engine's tests.* A 7% 10-year par bond falls 6.80% for a 100 bp rise (modified duration 7.11). The duration estimate's error falls with Δy², the convexity estimate's with Δy³. DV01 matches a 1 bp repricing.

**Business.**

| Item | Rule or fit | Value |
|---|---|---|
| EBLR | A repo-linked external benchmark moves one for one with repo. Banks raised theirs by the full 250 bp of May 2022 – Feb 2023 (RBI Bulletin, "Monetary Policy Transmission in India: Recent Dynamics", 16 Nov 2023). New floating-rate retail and MSME loans have been external-benchmark linked since 1 Oct 2019, with a reset at least every three months (RBI's circular of 4 Sep 2019, as reported). **VERIFY** | 1.0 × Δrepo, no lag |
| MCLR | Fitted on RBI's monthly 1-year median MCLR, Jun 2022 – Sep 2026 (52 months, from the "Lending and Deposit Rates of Scheduled Commercial Banks" releases), against every repo decision since 2014: Bₜ = c + b·Σ Δrepoⱼ·(1 − e^(−(t − tⱼ)/τ)). The RBI Bulletin above found 152 bp of 250 (0.61) by October 2023 | b = 0.57, τ = 6.9 months; RMSE 11.5 bp |
| MCLR and liquidity | The money market's move beyond what repo explains (3-month T-bill − β·Δrepo) also reaches MCLR: banks' marginal cost of funds is mostly deposits, which reprice slowly, and partly CDs, which move at once. **Assumption** | 0.3 |
| Base rates | EBLR = repo before the shock + the loan's spread; MCLR = the latest median 1-year MCLR (8.61% in Sep 2026) + spread | |
| Resets | The loan takes the benchmark's level at each reset, every R months from its first reset after the shock (the pass-through lag) | per profile |
| Imported costs | Rise with the rupee as the stock bought at the old rate runs off, linearly over the inventory days | per profile |
| Prices and demand | A share of the imported-cost rise is passed to prices. Sales volume responds to the repo-linked rate (semi-elasticity) and to prices (elasticity) | per profile |

**ILLUSTRATIVE presets.** Every size, share and elasticity below is an assumption, not any firm's or investor's data, and every field can be edited in the panel.

| Preset | Choice |
|---|---|
| Portfolio | 1-, 5-, 10- and 30-year G-secs (₹2, 3, 5 and 2 lakh face) and a 3-year AAA PSU bond (₹2 lakh, +60 bp over G-secs), each bought at par at today's yield; a gilt fund (₹3 lakh, duration 7.5, convexity 80) and a short-duration fund (₹2 lakh, duration 2.2, convexity 7) |
| Small shop | Sales ₹6 lakh a month; costs 82% of sales, 5% of them imported; inventory 20 days; half of a cost rise passed on. ₹10 lakh working-capital loan on EBLR + 3.5%, reset quarterly (next reset in a month). Sales semi-elasticity −0.3% per point of rates, price elasticity −0.5 |
| Electronics importer | Sales ₹1.5 crore a month; costs 88% of sales, 70% of them imported; inventory 60 days; 60% of a cost rise passed on. ₹2 crore loan on MCLR + 1.5%, reset yearly (next in six months), an older MCLR-linked loan of the kind that runs until renewal. Credit-financed demand: −2% per point of rates; price elasticity −1.2 |

**On the seed.**

- *A 100 bp rise in yields* takes the illustrative portfolio from ₹19,00,000 to ₹18,00,757 (−5.22%; modified duration 5.50, DV01 ₹1,045 per bp). Duration alone would have said −₹1,04,482; with convexity −₹99,022.
- *A 25 bp repo hike with the rupee 5% weaker:*
  - the shop's loan resets +25 bp next month (₹208 a month more interest);
  - the importer's MCLR loan is +8 bp at its month-six reset;
  - the importer's dearer stock cuts its margin by ₹2.30 lakh a month (−14.1%) once the old inventory has run off.

**Known limitations.**

- *Presets, not data.* No firm's or investor's numbers are used, and the elasticities are rough values chosen for illustration, not estimates.
- *MCLR from a short sample.* The highlights state MCLR only from mid-2022 (earlier figures are in attached files on rbidocs.rbi.org.in, which is not used). The fit therefore leans on one hiking and one easing cycle, and the liquidity share is assumed.
- *No credit spreads or defaults.* A bond's spread over G-secs is held fixed, and a business's loan spread and its access to credit do not change with the shock.
- *Partial equilibrium.* The businesses do not feed back into the markets. Interest is on a fully drawn working-capital limit of fixed size, with no repayment in the period followed.

## Historical replays (Module D, Phase 11)

`REPLAY TAPER2013 | DASH2020 | GILT2022 | HIKE2022 | ADVTAX` drives the model with what actually moved from an episode's start and sets each of its paths against what happened. The panel has play, pause, speed and scrub controls, the annotated timeline (each note links to its source) and a summary of what the model got right and wrong. The runners are in `backend/app/sim/replay.py`, the scores and the λ fit in `sovereign_engine/replay/`.

**Datasets.** `data/replays/<ID>/v1/` holds three files:

- `episode.yaml`: the window, drivers, targets, annotations with sources, and any cited inputs;
- `series/*.csv`;
- `manifest.json`: each series' source, URL, fetch time, rows and SHA-256.

`py tasks.py replays` rebuilds them from the committed seed. The gilt crisis also needs the Bank of England's published daily nominal curve archive (`glcnominalddata.zip`, about 40 MB, for the 30-year and 10-year spot yields), which is fetched once into the cache, size-checked and only parsed. The Bank's interactive database did not serve our client, so it is not used. To cover the taper, the seed's NSDL and RBI crawls now start in January 2013. Policy decisions are still read from 2014, so the MPC sample is unchanged.

**Scores** (`score`, `summarize`):

- RMSE and mean absolute error of each model path against what happened.
- Direction: the share of weeks (5 business days) that moved in which the model moved the same way. Days are used for the advance-tax months.
- The largest move from the start, the model's against the actual, and how many days apart they peaked.
- The move from start to end.

The summary turns these into sentences. A direction of 60% or more counts as "mostly right", and a peak within 25% of the actual one as "about right".

**The episodes, on the seed:**

| Episode | Drivers → model | Result |
|---|---|---|
| TAPER2013, May–Sep 2013 | The US 10Y's (+98 bp) and the VIX's daily moves through the Phase 9 chain, which was calibrated on 2014–2026, so this is out of sample | FPI flows −$4.6bn by the end against −$6.7bn actual (peak −5.5 against −8.0); weekly direction 71%. The rupee and the reserves are missed by an order of magnitude. The model moves the rupee ₹0.21 a dollar at most, while the actual rupee fell from ₹53.65 to ₹68.80 (28 August). Reserves end −$2.7bn against −$20.1bn. The chain carries only the US-yield and risk channels, so most of the rupee's fall is outside it |
| DASH2020, Feb–Apr 2020 | Net selling to the private market: foreign holdings' fall ($276.5bn in March, TIC, at market value) spread over 9–20 March, less the Fed's Treasury purchases (weekly SOMA changes, $1.52tn), priced two ways | Neither model has the rally that took the 10Y from 1.38% to 0.54% by 9 March (the emergency cut, the oil collapse). While foreigners sold, both rise only 5–6 bp against the actual 64 bp (to 18 March). The gilt λ moved over by depth ends −0.86 pp against −0.74 (RMSE 0.32 pp) through offsetting errors: it misses the rally to 9 March and keeps falling through April as the Fed kept buying, while the actual 10Y held between 0.6% and 0.8%. The US impact model ends −0.31 (RMSE 0.42 pp) and has the better weekly direction (67% against 56%) |
| GILT2022, Sep–Oct 2022 | LDI funds' forced sales less the Bank of England's purchases, over the long-gilt market's depth, times λ (below) | In sample. The flow model rises 1.25 pp at its peak against an actual 1.69 pp, 11 days late, and cannot see the announcement's reversal |
| HIKE2022, Mar 2022–Jul 2023 | The Fed's actual path (+525 bp) through the US simulator's policy loading, and QT's term premium (+20 bp, from the runoff in 10-year equivalents); RBI's repo and the actual liquidity through the macro map | The 2Y ends +3.38 pp against +3.57 (weekly direction 60%). The 10Y ends +1.24 pp against +2.25: the model has no inflation expectations or wider term-premium moves. India's WACR is within 21 bp RMSE (weekly direction 79%), in sample |
| ADVTAX | WACR through the macro map on the actual liquidity of the three worst advance-tax months since April 2022, picked from the data (the highest WACR − repo between the 10th and the 25th of Mar/Jun/Sep/Dec): Dec 2022 (+25 bp), Sep 2023 (+32), Dec 2023 (+31) | In sample. RMSE 17, 24 and 22 bp; daily direction 81%, 41% and 58%. In September 2023 the reported requirement still included the incremental CRR, so NDTL is held at its last value before it (10 Aug – 20 Oct 2023) |

**The fire-sale price impact λ** (GILT2022, `fit_lambda`):

- *The regression.* Δy₃₀,ₜ = α + λ·xₜ + εₜ, where xₜ is the day's net forced selling (LDI sales less the Bank's purchases) over the long-gilt market's normal daily turnover. λ is the move, in bp, for net selling of one normal day's turnover.
- *The fit.* Over the three weeks of forced selling, 23 Sep – 14 Oct 2022, with the Bank's announcement day (28 Sep) left out. The Cunliffe letter attributes that day's 100+ bp fall to the announcement itself, so no flow explains it.
- *Inputs.*

| Input | Value | Source |
|---|---|---|
| LDI sales | £36bn over the three weeks, daily profile assumed (below) | Pinter (2023), BoE Staff Working Paper 1019 |
| The Bank's purchases | Weekly holdings £0 / £3.66bn / £8.76bn / £19.26bn at 28 Sep / 5 / 12 / 19 Oct, spread evenly over each week's operations | Asset Purchase Facility Quarterly Report, Q4 2022 |
| Depth | £12bn a day of trading in the long-gilt sectors | Cunliffe's letter to the Treasury Committee, 5 Oct 2022 |
| 30-year yield | Daily spot yield | The Bank's nominal curve archive |

- *Result.* **λ = 66 bp per day's turnover**, 90% interval −7 to 331 (pairs bootstrap, 2,000 resamples), R² 0.21, 15 days. That is 5.5 bp per £bn sold in a day.
- *Sensitivity.* LDI funds' daily sales are not published, so λ is shown under three profiles, each with and without the announcement day:

| Profile | 28 Sep out | 28 Sep in |
|---|---|---|
| even over the three weeks (the base) | 66 (−7 to 331) | 17 (−222 to 145) |
| half in the first week | 56 (−2 to 113) | −2 (−143 to 97) |
| a third on 26–28 Sep | 72 (9 to 135) | −6 (−175 to 120) |

  With the announcement day in, no profile identifies λ. With it out, all three agree on 56–72 bp, but the intervals are wide.
- *Coverage.* With so few days, the 90% interval covers the true λ only about 80% of the time in simulation (engine test).
- *Transfer to Treasuries by depth.* Coalition Greenwich put March 2020's average daily volume in Treasuries at $944bn, market-wide. On that depth, λ gives 0.070 bp per $bn, or **7.0 bp per $100bn** sold (interval −0.8 to 35). The US impact model's permanent coefficient (Beltran et al.: 20 bp per $100bn in June 2010's market) gives 5.3 bp at today's debt held by the public ($32.5tn), plus 8.0 bp temporary at a pace of $100bn a month. The two agree on the permanent effect's size, so the simulator keeps its coefficients. The gilt λ is the independent check the brief asked for, not a replacement.

**Known limitations.**

- *Daily flows are estimates.* LDI funds' sales were never published day by day, the 2020 foreign selling is a monthly market-value change, and the Fed's purchases are weekly. Each is spread over days by a stated assumption.
- *In sample.* The gilt λ is replayed on the days it was fitted on, and the macro map was fitted on the WACR it replays. Only the taper is fully out of sample.
- *Right for the wrong reason.* A close end or a low RMSE does not mean the model explains an episode: in 2020 the gilt λ ends close to the actual 10Y through offsetting errors. The panel shows the paths day by day so the timing can be judged, not only the scores.
- *Partial models.* Each replay drives one part of the model. News the drivers do not carry (emergency cuts, budget events, inflation surprises) shows up as the model's error, and the summaries say so.

## Terminal completion (Phase 12)

**Market hours, corrected.** RBI extended call money to 7:00 PM from 1 Jul 2025 (RBI Bulletin, 23 Jul 2025, footnote 15) and opened the SDF and MSF at 7:00 PM instead of 5:30 PM (press release 2025-2026/625). Until Phase 12 the simulator still cleared rounds to 17:00 and ran the standing facilities at 17:30. The hours now live in `sovereign_engine.india.rules` with VERIFY and citations, and the simulator reads them. Market repo and TREPS trade from 9:00 AM to 4:00 PM from 1 Aug 2025 (the same footnote); the CCIL panel shows these hours, but the simulator gives those segments no session of their own, so their rates follow WACR all day.

**Call borrowing limits, re-read.** The Phase 5 citation predated an amendment. Since 8 Jun 2023 (FMRD.DIRD.02/14.01.001/2023-24), scheduled commercial banks borrow within board-approved limits inside the prudential limits for inter-bank liabilities, and RBI's 100% and 125% of capital funds apply only to small finance banks, payment banks and RRBs. The model's numbers are unchanged, but for the other banks they are now labelled an assumption (see the rules table above).

**The government's tax balance (TAXCAL).** The simulator tracks the tax receipts the government holds at RBI beyond the anchor day. Each tax day's drain (advance tax and GST, fitted above) adds to it, and the spending back takes it down again, so it mirrors the banks' loss rupee for rupee. RBI's releases give no daily level of the government's balance at RBI: the Money Market Operations release's "surplus cash balance reckoned for auction" is almost always zero. So the panel shows the change since the anchor, not a level.

The projection runs the expected tax flows alone, with no noise and no auctions. At each day's surplus it reads RBI's fitted reaction, and marks a day "VRR?" when a VRR is likelier than not ("VRRR?" likewise). The calendar heatmap shows WACR − repo for the year to the simulated day: RBI's releases, then simulated days.

**How the overnight markets settle (CCIL).** The panel's claims are each tied to a page checked on 21 Oct 2026:

- NDS-CALL is an electronic request-for-quote platform owned by RBI and managed by Clearcorp, a wholly owned subsidiary of CCIL. CROMS (market repo) and TREPS (tri-party repo) are Clearcorp's anonymous order-matching systems for dealing against G-secs ([CCIL](https://www.ccilindia.com/clearcorp-dealing-systems)).
- Call money is settled bilaterally through RTGS, throughout the day. Market repo and TREPS are settled through CCIL as central counterparty, with multilateral netting of funds and securities ([RBI working group on trading and settlement timings](https://www.rbi.org.in/scripts/PublicationReportDetails.aspx?ID=935)).
- TREPS trades are novated to CCIL as tri-party agent and netted with outright and market repo trades. The borrower's securities move through CCIL's settlement GILT account to the lender's once funds have settled at RBI ([CCIL, triparty repo settlement](https://www.ccilindia.com/web/ccil/tripartyclearingsettlement)).
- Deals done over the counter are reported on NDS-CALL within 15 minutes, and only banks and primary dealers may take part ([Call, Notice and Term Money Directions, 2021](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12120)).

The rates and volumes on the diagram are the simulated day's (TREPS and market repo from the medians in the fit table above).

**Other panels.**

- `DEBT` holds each curve flat on the real maturity profile, deficit and issuance mix, and shows dollars a year or a share of GDP or receipts.
- `TIC` sets the live holdings after any simulated sale against TIC's own figures. Those are at market value and counted by the country where the securities are held in custody, not always the owner's.
- `CORR` draws both corridors live.
- `NDTL` repeats that the 40 banks are SYNTHETIC.

**Layouts and keys.** `LAYOUT SAVE name` keeps the four slots' functions, the commands that filled them and the grid's split in this browser (localStorage). `LAYOUT name` restores one, `LAYOUT DEFAULT` the opening one, and the last layout reopens on start. The backend checks the request; the browser carries it out, and a blocked storage only means nothing is remembered. Keys:

- Alt+1…4 focus a panel, and Alt+arrows move between panels;
- Alt+Enter shows the focused panel alone;
- F1 explains the focused panel, Alt+T toggles teach mode;
- Esc returns to the command bar.

**Charts.** Time series use TradingView Lightweight Charts™: the replays, the call rounds, DEBT and TAXCAL's projection. Curves and heatmaps use ECharts, as the brief has it.

## Scenarios and exports (Phase 13)

**A scenario is a run's seed, its start and its journal.** The journal lists the commands that changed the markets, each with the simulated time it ran:

- `HIKE`, `CUT` and `QT`;
- `SHOCK` (a foreign sale or a Fed shock through the linkage);
- `REPO`, `CRR`, `VRR` and `VRRR`;
- `WACR POLICY` and `WACR REALISTIC`.

Commands that only show something are left out, and so are `SPEED` and `PAUSE`, since the paths depend on simulated time alone: India's market runs a fixed daily schedule, and the US market steps on its one-minute grid. Each run draws a fresh seed unless `SD_SIM_SEED` fixes one, and `RESET` starts a new run.

**SAVE and LOAD.**

- `SAVE name` stores the scenario in the database (`scenarios` table, migration 0002).
- `LOAD name` rebuilds the markets from the current anchors with the saved seed and start, runs to each command's time and runs it again, and stops where the run was saved. The clock stands still while it loads, and other commands are turned away until it is done.
- The replay is exact: a backend test saves a run whose clock ticked unevenly, changes it, loads it, and compares every price, rate, balance and auction. `py tasks.py demo` saves and loads the DEMO.md run on the seed.
- It is exact only from the same anchors. If newer data has arrived since the save, LOAD says so and replays from the newer anchors. A live run that re-anchored part-way (new US data on a new simulated day) is not journaled either: its replay uses the newer anchors from the start.
- The SPRD chart's simulated points pair each G-sec close with the US 10-year at the tick that saw it, so they can differ by a minute's move after a LOAD. The markets themselves do not.
- Module E's edited portfolio and businesses are inputs to a view, not part of the scenario.

**EXPORT CSV** saves the focused panel's main table:

| Panel | Table |
|---|---|
| PY | price change by yield shift: exact, duration, duration + convexity |
| UST | the live curve and the official close, by tenor |
| GSEC | FBIL's close and the live curve, by tenor |
| FED | the QT projection if one is set, else the panel's fields |
| WACR, SPRD | RBI's (Treasury's) history |
| CALL, LAF, NDTL, TIC, CCIL | the rounds, the auctions, the banks, the holders, the segments |
| TAXCAL, LINK, DEBT | the projection ahead, the chain's daily path, the interest bill by month |
| MPC, IMPACT | the backtest's recent decisions, the portfolio's holdings |
| REPLAY | every target's path, actual and modelled, by date |

Other panels give their largest table, or their fields as name/value pairs. Nested fields are dotted (`hold.coupons`).

**EXPORT PNG** stacks the panel's charts under its title and each chart's label, as drawn: ECharts' SVG and Lightweight Charts' canvas. Diagrams and tables are not drawn; their data is in the CSV. Files are named `sovereigndesk-<panel>[-<table>]-<simulated time>`.

## The web demo (GitHub Pages)

The public site is the terminal built in demo mode (`npm run build:demo`). It has no backend, so it computes nothing; it plays back a recording made by `py tasks.py record-demo`. The recorder runs the whole app offline on the committed seed, with seed 7, starting at 09:30 IST on Tuesday 27 October 2026, and saves:

- **The ticks.** The opening three minutes (three simulated hours) at one frame a second, played in a loop.
- **Every view.** Each panel's command (PY, FED, WACR, CALL, TAXCAL, CCIL, MPC, the five replays, IMPACT's presets, HELP for every code…), answered from that opening state.
- **Each command that moves the markets.** Each one is recorded from a fresh RESET: HIKE and CUT, QT, three foreign sales, SHOCK FED with each RBI answer, REPO, CRR, VRR, VRRR and the policy mode. With it come its narrative, twelve seconds of ticks after it, and the panels it changes, as they then read.

So the site answers one shock at a time. A second shock replaces the first rather than adding to it, and RESET returns to the opening. A command or variant that was not recorded (`HIKE 75BP`, say) gets a reply saying so and listing what was. SAVE, LOAD, SPEED and editing IMPACT's portfolio need the live terminal. LAYOUT and EXPORT work, because they run in the browser anyway. The page carries a STATIC DEMO banner, and the status strip reads PLAYBACK instead of LIVE.

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
  - Market quotes (`fit_nss_quotes`, Phase 7): bills at their simple yield and par bonds at their coupon, fitted on the yield errors with an analytic Jacobian, seeded by the zero-rate fit or warm-started from the previous fit. With the long end still rising at 30 years the fit can put β₀ at its bound of zero and carry the level in the τ₂ hump; within 30 years the curve is unaffected, beyond it the extrapolation is not used.

## Short-rate models (engine, Phase 2)

- **Vasicek and CIR.** Both use exact transitions: a Gaussian OU step for Vasicek and a scaled noncentral χ² draw for CIR. CIR bond prices are evaluated in an overflow-safe form.
- **Hull–White 1F.** The short rate is r = x + α(t), with x a zero-mean OU process (Brigo–Mercurio §3.3), so it reprices the initial curve exactly. θ(t) needs the forward-curve slope. It is exact for NSS curves and a finite difference otherwise. On a piecewise-flat curve, θ is not meaningful at the knots; α and bond prices still are.
- **Corridor rates (WACR, EFFR).** A logit-OU process keeps the rate strictly inside (L, U) by construction and reverts its median to the target. The logit volatility is set by the delta method from a target rate volatility.
