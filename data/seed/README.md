Real-data snapshots (CSV + manifest.json with source URL, fetched_at, rows, sha256). Built by `py tasks.py seed` from Phase 3.

FBIL's G-sec par yields (`fbil/gsec/par/`) are daily from 13 Feb 2023, FBIL's first .xlsx workbook. Before that FBIL served .xls workbooks of about 0.75 MB each, so only the publications around each repo change are kept (the one before, the day, the one after). Rebuilding `fbil_gsec` needs the RBI seed, which dates those changes.

RBI's policy record (`rbi/mpc/`, `rbi/tbill91/`, `rbi/hist/`, source `rbi_policy`) is crawled from the press-release archive from 1 Jan 2014: every repo decision since April 2014, the MPC's meeting schedules, the 91-day T-bill cut-off before each decision and, until 8 Apr 2022, the money-market readings of the two weeks before each one. MoSPI's CPI (`mospi/cpi/2012/`, `mospi/cpi/2024/`) and quarterly GDP (`mospi/gdp/`) come through MoSPI's MCP server (`mcp.mospi.gov.in`). Both feed the MPC predictor (Phase 8).

NSDL's daily FPI flows (`nsdl/fpi/`) run from January 2014 through NSDL's archive, one month per request, and RBI's weekly foreign exchange reserves (`rbi/wss/`) from the Weekly Statistical Supplement extracts in the same press-release crawl as the policy record. Both calibrate the US → India linkage (Phase 9).
