Real-data snapshots (CSV + manifest.json with source URL, fetched_at, rows, sha256). Built by `py tasks.py seed` from Phase 3.

FBIL's G-sec par yields (`fbil/gsec/par/`) are daily from 13 Feb 2023, FBIL's first .xlsx workbook. Before that FBIL served .xls workbooks of about 0.75 MB each, so only the publications around each repo change are kept (the one before, the day, the one after). Rebuilding `fbil_gsec` needs the RBI seed, which dates those changes.
