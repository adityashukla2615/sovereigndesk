"""Build the real-data seed snapshot in data/seed from the live official sources.

    py tasks.py seed                       # every source
    py tasks.py seed --sources fred,tic    # rebuild some sources, keep the rest

Needs network access and, for FRED, FRED_API_KEY in backend/.env. Every file written comes from
a live response: if a request fails the build stops rather than snapshot a cached copy.
"""

import argparse
import shutil
import sys
from datetime import UTC, date, datetime

from app.config import Settings
from app.data.seed import (
    Manifest,
    SeedSeries,
    SeedTable,
    read_manifest,
    write_manifest,
    write_mspd,
    write_series,
)
from app.data.sources import build_adapters, make_client
from app.data.sources.fiscaldata import FiscalDataAdapter
from app.logs import configure_logging

SOURCES = ("fred", "treasury", "fiscaldata", "tic")
STARTS: dict[str, date | None] = {
    "fred": date(2005, 1, 1),
    "treasury": date(2010, 1, 1),
    "fiscaldata": date(2005, 1, 1),
    "tic": None,  # whole files: history from 2000 plus the latest 13 months
}
# Seed sub-directories each source owns (cleared before a rebuild so dropped series vanish).
DIRS = {
    "fred": ["fred"],
    "treasury": ["ust"],
    "fiscaldata": ["fiscal", "fiscaldata"],
    "tic": ["tic"],
}


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
    series: list[SeedSeries] = [
        s for s in (previous.series if previous else []) if s.source not in sources
    ]
    tables: list[SeedTable] = [
        t for t in (previous.tables if previous else []) if t.source not in sources
    ]

    with make_client(settings) as client:
        adapters = build_adapters(settings, client)
        for source in sources:
            print(f"fetching {source} ...", flush=True)
            outcome = adapters[source].fetch(start=STARTS[source])
            cached = [f.spec.series_id for f in outcome.frames if f.provenance.from_cache]
            if cached:
                print(f"{source}: live requests failed for {cached[:5]}; not seeding cached data")
                return 1
            for name, error in outcome.errors.items():
                print(f"  warning: {name}: {error}")
            for folder in DIRS[source]:
                shutil.rmtree(seed_dir / folder, ignore_errors=True)
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
