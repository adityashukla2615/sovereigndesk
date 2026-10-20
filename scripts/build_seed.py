"""Build the real-data seed snapshot in data/seed from the live official sources.

    py tasks.py seed                       # every source
    py tasks.py seed --sources fred,tic    # rebuild some sources, keep the rest

Needs network access and, for FRED, FRED_API_KEY in backend/.env. Every file written comes from
a live response: if a request fails the build stops rather than snapshot a cached copy. RBI's
press releases and FBIL's daily G-sec workbooks never change once published, so a copy saved by
an earlier live crawl is reused rather than downloaded again; its fetch time is the original
one. FBIL's G-sec history needs RBI's: the repo changes it brackets come from the RBI seed.
"""

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from app.config import Settings
from app.data.seed import (
    Manifest,
    SeedSeries,
    SeedTable,
    read_manifest,
    read_series,
    write_manifest,
    write_mspd,
    write_series,
)
from app.data.sources import build_adapters, make_client
from app.data.sources.base import Adapter, FetchOutcome
from app.data.sources.fbil_gsec import FbilGsecAdapter
from app.data.sources.fiscaldata import FiscalDataAdapter
from app.logs import configure_logging
from sovereign_engine.india.passthrough import policy_changes

SOURCES = (
    "fred", "treasury", "fiscaldata", "tic", "rbi", "rbi_policy", "fbil", "fbil_gsec", "nsdl",
    "mospi",
)  # fmt: skip
GSEC_XLSX_FROM = date(2023, 2, 13)
"""FBIL's first .xlsx G-sec workbook. The legacy .xls files before it are ~0.75 MB each, so for
that period only the publications around each repo change are fetched."""
STARTS: dict[str, date | None] = {
    "fred": date(2005, 1, 1),
    "treasury": date(2010, 1, 1),
    "fiscaldata": date(2005, 1, 1),
    "tic": None,  # whole files: history from 2000 plus the latest 13 months
    # MMO releases since the SDF replaced the fixed-rate reverse repo as the LAF floor
    # (8 April 2022): about 1,650 releases, fetched one per second.
    "rbi": date(2022, 4, 8),
    # Every policy decision since the bi-monthly cycle began (April 2014), with the money
    # markets and T-bills before each: about 1,100 releases, one per second.
    "rbi_policy": date(2014, 1, 1),
    "fbil": date(2022, 4, 1),
    "fbil_gsec": GSEC_XLSX_FROM,
    "nsdl": None,  # the current month's report
    "mospi": date(2011, 1, 1),  # CPI from January 2011, GDP from 2011-12
}


def repo_changes(seed_dir: Path, series: list[SeedSeries]) -> list[date]:
    """Days the repo rate changed, from the seeded SDF and MSF (repo is their midpoint)."""
    entries = {s.series_id: s for s in series}
    try:
        sdf, msf = (entries[f"rbi/mmo/{k}_rate"] for k in ("sdf", "msf"))
    except KeyError:
        raise SystemExit("fbil_gsec needs the RBI seed first: run --sources rbi") from None
    frame = pd.merge(read_series(seed_dir, sdf), read_series(seed_dir, msf), on="date")
    frame = frame.dropna().sort_values("date")
    repo = (frame["value_x"] + frame["value_y"]) / 2
    return [day for day, _ in policy_changes(list(frame["date"]), repo.to_numpy())]


def fetch_source(
    source: str, adapter: Adapter, seed_dir: Path, series: list[SeedSeries]
) -> FetchOutcome:
    if isinstance(adapter, FbilGsecAdapter):
        older = [d for d in repo_changes(seed_dir, series) if d < GSEC_XLSX_FROM]
        windows = adapter.around(older)
        print(f"  {len(older)} repo changes before {GSEC_XLSX_FROM}: {len(windows)} publications")
        return adapter.fetch(start=GSEC_XLSX_FROM, also=windows)
    return adapter.fetch(start=STARTS[source])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--sources", default=",".join(SOURCES), help="comma-separated subset")
    args = parser.parse_args(argv)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if unknown := set(sources) - set(SOURCES):
        parser.error(f"unknown sources: {sorted(unknown)}")

    configure_logging("INFO")
    settings = Settings()
    seed_dir = settings.seed_dir
    if "fred" in sources and settings.fred_api_key is None:
        print(
            "FRED_API_KEY is missing from backend/.env; skip FRED with --sources", file=sys.stderr
        )
        return 2

    previous = read_manifest(seed_dir)
    previous_series = previous.series if previous else []
    series: list[SeedSeries] = [s for s in previous_series if s.source not in sources]
    tables: list[SeedTable] = [
        t for t in (previous.tables if previous else []) if t.source not in sources
    ]

    with make_client(settings) as client:
        adapters = build_adapters(settings, client)
        for source in sources:
            print(f"fetching {source} ...", flush=True)
            outcome = fetch_source(source, adapters[source], seed_dir, series)
            cached = [f.spec.series_id for f in outcome.frames if f.provenance.from_cache]
            if cached:
                print(f"{source}: live requests failed for {cached[:5]}; not seeding cached data")
                return 1
            for name, error in outcome.errors.items():
                print(f"  warning: {name}: {error}")
            # The source's previous files go first, so series it no longer returns vanish.
            for entry in previous_series:
                if entry.source == source:
                    (seed_dir / entry.file).unlink(missing_ok=True)
            series += [write_series(seed_dir, frame) for frame in outcome.frames]
            adapter = adapters[source]
            if isinstance(adapter, FiscalDataAdapter):
                snapshot = adapter.mspd_latest()
                if snapshot.provenance.from_cache:
                    print("fiscaldata: MSPD came from cache; not seeding it")
                    return 1
                tables.append(write_mspd(seed_dir, snapshot))
            print(f"  {len(outcome.frames)} series", flush=True)

    write_manifest(seed_dir, Manifest(datetime.now(UTC).isoformat(), series, tables))
    rows = sum(s.rows for s in series)
    print(f"seed: {len(series)} series, {rows:,} rows, {len(tables)} table(s) -> {seed_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
