"""The committed real-data snapshot under ``data/seed`` that lets the terminal boot offline.

Each series is a ``<series_id>.csv`` (``date,value``); ``manifest.json`` records, per file, the
source URL (secrets removed), when it was fetched, row count, date range and sha256.
"""

import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.data.catalog import Frequency, SeriesSpec, SourceName
from app.data.sources.base import SeriesFrame
from app.data.sources.fiscaldata import MspdRow, MspdSnapshot

MANIFEST = "manifest.json"
MSPD_FILE = "fiscaldata/mspd_table_3_market.csv"


@dataclass(frozen=True, slots=True)
class SeedSeries:
    series_id: str
    source: SourceName
    title: str
    units: str
    frequency: Frequency
    file: str
    url: str
    fetched_at: str
    rows: int
    start: str
    end: str
    sha256: str

    @property
    def spec(self) -> SeriesSpec:
        return SeriesSpec(self.series_id, self.source, "", self.title, self.units, self.frequency)


@dataclass(frozen=True, slots=True)
class SeedTable:
    name: str
    source: str
    file: str
    url: str
    fetched_at: str
    rows: int
    record_date: str
    sha256: str


@dataclass(frozen=True, slots=True)
class Manifest:
    generated_at: str
    series: list[SeedSeries]
    tables: list[SeedTable]


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def write_series(seed_dir: Path, frame: SeriesFrame) -> SeedSeries:
    rel = f"{frame.spec.series_id}.csv"
    buffer = io.StringIO()
    buffer.write("date,value\n")
    for day, value in zip(frame.data["date"], frame.data["value"], strict=True):
        buffer.write(f"{day.isoformat()},{float(value)!r}\n")
    sha = _write(seed_dir / rel, buffer.getvalue())
    spec, prov = frame.spec, frame.provenance
    return SeedSeries(
        series_id=spec.series_id,
        source=spec.source,
        title=spec.title,
        units=spec.units,
        frequency=spec.frequency,
        file=rel,
        url=prov.url,
        fetched_at=prov.fetched_at.isoformat(),
        rows=len(frame.data),
        start=frame.data["date"].iloc[0].isoformat(),
        end=frame.data["date"].iloc[-1].isoformat(),
        sha256=sha,
    )


_MSPD_COLUMNS = [
    "record_date", "cusip", "issue_date", "security_class", "maturity_date",
    "interest_rate_pct", "yield_pct", "issued_musd", "outstanding_musd",
]  # fmt: skip


def write_mspd(seed_dir: Path, snapshot: MspdSnapshot) -> SeedTable:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_MSPD_COLUMNS)
    for row in snapshot.rows:
        writer.writerow(
            [
                "" if (v := getattr(row, c)) is None else v.isoformat() if isinstance(v, date) else v
                for c in _MSPD_COLUMNS
            ]
        )
    sha = _write(seed_dir / MSPD_FILE, buffer.getvalue())
    return SeedTable(
        name="mspd_table_3_market",
        source="fiscaldata",
        file=MSPD_FILE,
        url=snapshot.provenance.url,
        fetched_at=snapshot.provenance.fetched_at.isoformat(),
        rows=len(snapshot.rows),
        record_date=snapshot.rows[0].record_date.isoformat(),
        sha256=sha,
    )


def write_manifest(seed_dir: Path, manifest: Manifest) -> None:
    payload = {
        "generated_at": manifest.generated_at,
        "series": [asdict(s) for s in sorted(manifest.series, key=lambda s: s.series_id)],
        "tables": [asdict(t) for t in manifest.tables],
    }
    _write(seed_dir / MANIFEST, json.dumps(payload, indent=1) + "\n")


def read_manifest(seed_dir: Path) -> Manifest | None:
    path = seed_dir / MANIFEST
    if not path.exists():
        return None
    payload = json.loads(path.read_text("utf-8"))
    return Manifest(
        generated_at=payload["generated_at"],
        series=[SeedSeries(**s) for s in payload["series"]],
        tables=[SeedTable(**t) for t in payload["tables"]],
    )


def _verified_bytes(seed_dir: Path, rel: str, sha256: str) -> bytes:
    data = (seed_dir / rel).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"seed file {rel} does not match its manifest checksum")
    return data


def read_series(seed_dir: Path, entry: SeedSeries) -> pd.DataFrame:
    data = _verified_bytes(seed_dir, entry.file, entry.sha256)
    frame = pd.read_csv(io.BytesIO(data), dtype={"value": "float64"})
    frame["date"] = [date.fromisoformat(d) for d in frame["date"]]
    return frame[["date", "value"]]


def _optional(record: dict[str, str], key: str) -> float | None:
    return float(record[key]) if record[key] else None


def read_mspd(seed_dir: Path, table: SeedTable) -> list[MspdRow]:
    data = _verified_bytes(seed_dir, table.file, table.sha256).decode("utf-8")
    return [
        MspdRow(
            record_date=date.fromisoformat(r["record_date"]),
            cusip=r["cusip"],
            issue_date=date.fromisoformat(r["issue_date"]),
            security_class=r["security_class"],
            maturity_date=date.fromisoformat(r["maturity_date"]),
            interest_rate_pct=_optional(r, "interest_rate_pct"),
            yield_pct=_optional(r, "yield_pct"),
            issued_musd=_optional(r, "issued_musd"),
            outstanding_musd=_optional(r, "outstanding_musd"),
        )
        for r in csv.DictReader(io.StringIO(data))
    ]


def fetched_at(entry: SeedSeries | SeedTable) -> datetime:
    return datetime.fromisoformat(entry.fetched_at)
