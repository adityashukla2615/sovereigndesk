# sovereign-engine

The pure quant core of SovereignDesk. Every public function is a pure computation (no I/O, no clocks, no global state), documents its formula in an `Equation:` docstring section, and has a unit test against a textbook, closed-form or official-data anchor. A meta-test enforces the docstrings and the absence of I/O imports.

| Package | Contents |
|---|---|
| `bonds` | Day counts, coupon schedules, price/yield (street and US Treasury App. B conventions), duration, convexity, DV01, key-rate durations, US and Indian bill formulas, and the per-market convention table with sources |
| `curves` | The `Curve` protocol, par yields, log-linear discount curves, par-yield bootstrapping, and Nelson–Siegel–Svensson curves and fitting |
| `rates` | Vasicek, CIR and Hull–White (fitted to the initial curve) with exact transitions, plus a logit-OU process for rates bounded by a policy corridor |

Later phases add `us`, `india`, `linkage`, `predict` and `replay` (see [docs/PLAN.md](../docs/PLAN.md)).

Anchor tests reproduce, from committed snapshots (`tests/fixtures/`, rebuilt by `scripts/fetch_engine_fixtures.py`):

- every TreasuryDirect award price, investment rate and accrued interest in the snapshot, exactly
- the Fed's GSW zero, forward and par yields
- the worked examples in 31 CFR 356 Appendix B, Hull's *Options, Futures, and Other Derivatives* (Table 4.6) and RBI's G-sec primer
- RBI T-bill auction yields
