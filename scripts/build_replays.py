"""Build the replay datasets: data/replays/<ID>/v1/{episode.yaml, series/*.csv, manifest.json}.

    py tasks.py replays

Each episode's series are cut from the committed seed (FRED, NSDL, RBI) where it covers the
window. The 2022 gilt crisis also needs the Bank of England's daily nominal spot curve, read
once from the Bank's published archive (glcnominalddata.zip, about 40 MB, cached and only
parsed). Inputs that were never published day by day, such as LDI funds' gilt sales, go into
episode.yaml as the cited estimates they are. The advance-tax episode picks its quarters from
the data: the quarter-months whose WACR − repo rose highest between the 10th and the 25th.
"""

import hashlib
import io
import json
import sys
import zipfile
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import yaml

from app.config import REPO_ROOT, Settings
from app.data.http import Fetcher, RawCache
from app.data.sources import make_client

SEED = REPO_ROOT / "data" / "seed"
OUT = REPO_ROOT / "data" / "replays"
VERSION = "v1"
BOE_ARCHIVE = (
    "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip"
)
BOE_MEMBER = "GLC Nominal daily data_2016 to 2024.xlsx"
MAX_ARCHIVE_BYTES = 80_000_000
MAX_MEMBER_BYTES = 40_000_000
RBI = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid="
FED = "https://www.federalreserve.gov/newsevents/pressreleases/"
CUNLIFFE_5 = (
    "https://www.bankofengland.co.uk/-/media/boe/files/letter/2022/october/"
    "letter-from-jon-cunliffe-ldi-5-october-2022"
)
CUNLIFFE_18 = (
    "https://www.bankofengland.co.uk/-/media/boe/files/letter/2022/october/"
    "letter-from-jon-cunliffe-ldi-18-october-2022.pdf"
)
PINTER = (
    "https://www.bankofengland.co.uk/working-paper/2023/an-anatomy-of-the-2022-gilt-market-crisis"
)
APF_Q4 = "https://www.bankofengland.co.uk/asset-purchase-facility/2022/2022-q4"
GREENWICH = "https://www.greenwich.com/node/144206"

Series = tuple[pd.Series, dict[str, Any]]


def _manifest() -> dict[str, dict[str, Any]]:
    return {
        e["series_id"]: e for e in json.loads((SEED / "manifest.json").read_text("utf-8"))["series"]
    }


def seed_series(series_id: str, start: date, end: date) -> Series:
    """A window of a seed series, with the seed's provenance."""
    entry = _manifest()[series_id]
    frame = pd.read_csv(SEED / entry["file"], parse_dates=["date"]).set_index("date")["value"]
    window = frame[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    return window.astype(float), {
        "source": entry["source"],
        "series_id": series_id,
        "title": entry["title"],
        "units": entry["units"],
        "url": entry["url"],
        "fetched_at": entry["fetched_at"],
    }


def boe_spot(maturities: dict[str, float], start: date, end: date) -> dict[str, Series]:
    """Daily UK nominal spot yields (%) at the given maturities from the Bank of England's
    published curve archive."""
    settings = Settings()
    with make_client(settings) as client:
        body = Fetcher(client, RawCache(settings.cache_dir)).get("boe", BOE_ARCHIVE)
    if len(body.content) > MAX_ARCHIVE_BYTES or body.content[:2] != b"PK":
        raise SystemExit("the Bank of England archive is not the zip expected")
    with zipfile.ZipFile(io.BytesIO(body.content)) as archive:
        info = archive.getinfo(BOE_MEMBER)
        if info.file_size > MAX_MEMBER_BYTES:
            raise SystemExit(f"{BOE_MEMBER} unzips to {info.file_size:,} bytes, more than expected")
        workbook = archive.read(info)
    sheet = pd.read_excel(io.BytesIO(workbook), sheet_name="4. spot curve", header=None)
    years = [float(v) if isinstance(v, int | float) else None for v in sheet.iloc[3, 1:]]
    columns = {name: 1 + years.index(m) for name, m in maturities.items()}
    days = pd.to_datetime(sheet.iloc[5:, 0], errors="coerce")
    inside = days.notna() & (days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))
    out: dict[str, pd.Series] = {}
    for name, col in columns.items():
        values = pd.to_numeric(sheet.iloc[5:, col], errors="coerce")
        picked = pd.Series(values[inside].to_numpy(), index=pd.DatetimeIndex(days[inside]))
        out[name] = picked.dropna().astype(float).sort_index()
    provenance = {
        "source": "boe",
        "series_id": f"BoE nominal spot curve ({BOE_MEMBER}, sheet '4. spot curve')",
        "units": "%",
        "url": BOE_ARCHIVE,
        "fetched_at": body.fetched_at.isoformat(),
    }
    return {
        name: (values, {**provenance, "title": f"UK nominal spot yield, {maturities[name]:g}Y"})
        for name, values in out.items()
    }


def _write(episode: dict[str, Any], series: dict[str, Series]) -> None:
    folder = OUT / episode["id"] / VERSION
    target = folder / "series"
    target.mkdir(parents=True, exist_ok=True)
    for old in target.glob("*.csv"):
        old.unlink()
    manifest: dict[str, Any] = {}
    for name, (values, provenance) in series.items():
        dates = pd.DatetimeIndex(values.index).strftime("%Y-%m-%d")
        frame = pd.DataFrame({"date": dates, "value": values.round(6).to_numpy()})
        text = frame.to_csv(index=False, lineterminator="\n")
        (target / f"{name}.csv").write_text(text, encoding="utf-8", newline="\n")
        manifest[name] = {
            **provenance,
            "file": f"series/{name}.csv",
            "rows": len(frame),
            "start": frame["date"].iloc[0] if len(frame) else None,
            "end": frame["date"].iloc[-1] if len(frame) else None,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    (folder / "manifest.json").write_text(
        json.dumps({"id": episode["id"], "version": VERSION, "series": manifest}, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (folder / "episode.yaml").write_text(
        yaml.safe_dump(episode, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
        newline="\n",
    )
    print(f"  {episode['id']}: {len(series)} series -> {folder.relative_to(REPO_ROOT)}")


def _note(day: str, text: str, source: str) -> dict[str, str]:
    return {"date": day, "text": text, "source": source}


def taper2013() -> None:
    start, end = date(2013, 4, 15), date(2013, 9, 30)
    episode: dict[str, Any] = {
        "id": "TAPER2013",
        "title": "The 2013 taper tantrum",
        "summary": (
            "The Fed signalled it would slow its bond buying; US yields jumped, foreign money "
            "left India, the rupee fell to a record low and RBI tightened rupee liquidity in "
            "an emergency."
        ),
        "model": "taper",
        "window": {"start": "2013-05-01", "end": "2013-09-30"},
        "drivers": ["us10y", "vix"],
        "targets": ["fpi", "inr", "reserves"],
        "annotations": [
            _note(
                "2013-05-22",
                "Bernanke: the Fed could slow its purchases in the next few meetings",
                "https://www.federalreserve.gov/newsevents/testimony/bernanke20130522a.htm",
            ),
            _note(
                "2013-06-19",
                "FOMC: Bernanke sets out tapering later in the year",
                f"{FED}monetary20130619a.htm",
            ),
            _note(
                "2013-07-15", "RBI raises the MSF to 10.25% and caps LAF borrowing", f"{RBI}29086"
            ),
            _note(
                "2013-07-23",
                "RBI tightens further: a per-bank LAF cap, a higher daily CRR",
                f"{RBI}29140",
            ),
            _note(
                "2013-08-28",
                "Rupee at a record low; RBI opens a dollar window for oil companies",
                f"{RBI}29423",
            ),
            _note(
                "2013-09-04",
                "Rajan takes office; a swap window for FCNR(B) deposits",
                f"{RBI}29480",
            ),
            _note(
                "2013-09-18",
                "FOMC holds its purchases: no taper yet",
                f"{FED}monetary20130918a.htm",
            ),
            _note("2013-09-20", "RBI raises repo to 7.5% and cuts the MSF to 9.5%", f"{RBI}29590"),
        ],
    }
    series = {
        "us10y": seed_series("fred/DGS10", start, end),
        "vix": seed_series("fred/VIXCLS", start, end),
        "inr": seed_series("fred/DEXINUS", start, end),
        "fpi_total": seed_series("nsdl/fpi/total_usd", start, end),
        "fpi_debt": seed_series("nsdl/fpi/debt_usd", start, end),
        "fpi_equity": seed_series("nsdl/fpi/equity_usd", start, end),
        "reserves": seed_series("rbi/wss/reserves", start, end),
    }
    _write(episode, series)


def dash2020() -> None:
    start, end = date(2020, 2, 3), date(2020, 4, 30)
    holdings = seed_series("tic/grand_total", date(2020, 1, 1), date(2020, 4, 30))
    tic = holdings[0]
    feb = float(tic[tic.index <= pd.Timestamp("2020-02-29")].iloc[-1])
    mar = float(tic[tic.index <= pd.Timestamp("2020-03-31")].iloc[-1])
    episode: dict[str, Any] = {
        "id": "DASH2020",
        "title": "The March 2020 dash for cash",
        "summary": (
            "As the pandemic hit, investors sold even Treasuries for cash: yields rose while "
            "stocks fell, until the Fed bought Treasuries at an unprecedented pace."
        ),
        "model": "dash",
        "window": {"start": "2020-02-24", "end": "2020-04-30"},
        "drivers": ["foreign_sales", "fed_purchases"],
        "targets": ["us10y", "us30y"],
        "params": {
            "foreign_sales_bn": round(feb - mar, 1),
            "foreign_sales_note": (
                f"TIC: foreign holdings of Treasuries fell from ${feb:,.1f}bn (end-February) to "
                f"${mar:,.1f}bn (end-March 2020), at market value; spread evenly over 9-20 March, "
                "the days of the selling (an assumption)"
            ),
            "selling_days": ["2020-03-09", "2020-03-20"],
            "depth_bn": 944.0,
            "depth_note": (
                "Coalition Greenwich: March 2020 average daily notional volume in Treasuries, "
                "$944bn, market-wide"
            ),
            "depth_source": GREENWICH,
        },
        "annotations": [
            _note("2020-03-03", "Emergency Fed cut of 50 bp", f"{FED}monetary20200303a.htm"),
            _note("2020-03-09", "10Y at a record low as oil collapses", "FRED DGS10"),
            _note(
                "2020-03-15",
                "Fed to zero; $500bn of Treasury purchases",
                f"{FED}monetary20200315a.htm",
            ),
            _note("2020-03-18", "Dash for cash: yields up as everything is sold", "FRED DGS10"),
            _note(
                "2020-03-23", "FOMC: purchases in the amounts needed", f"{FED}monetary20200323a.htm"
            ),
        ],
    }
    debt_2010, _ = seed_series("fiscal/debt/public", date(2010, 6, 1), date(2010, 6, 30))
    episode["params"]["debt_public_2010_bn"] = round(float(debt_2010.iloc[-1]) / 1e9, 1)
    episode["params"]["debt_public_2010_note"] = (
        "debt held by the public at the end of June 2010 (Treasury, debt to the penny): the "
        "market the US impact model's coefficients come from"
    )
    series = {
        "us10y": seed_series("fred/DGS10", start, end),
        "us30y": seed_series("fred/DGS30", start, end),
        "fed_treasuries": seed_series("fred/TREAST", start, end),
        "foreign_holdings": holdings,
        "debt_public": seed_series("fiscal/debt/public", start, end),
    }
    _write(episode, series)


def gilt2022() -> None:
    start, end = date(2022, 9, 1), date(2022, 10, 31)
    episode: dict[str, Any] = {
        "id": "GILT2022",
        "title": "The September 2022 gilt crisis",
        "summary": (
            "After the mini-budget, long gilt yields rose faster than ever recorded; leveraged "
            "LDI funds had to sell gilts into a market that could not take them, until the Bank "
            "of England bought long gilts as a backstop. The closest real analogue to a forced "
            "foreign sale, and the episode that calibrates the fire-sale price impact λ."
        ),
        "model": "gilt",
        "window": {"start": "2022-09-01", "end": "2022-10-31"},
        "drivers": ["ldi_sales", "boe_purchases"],
        "targets": ["gilt30y", "gilt10y"],
        "params": {
            "ldi_sales_bn": 36.0,
            "ldi_note": (
                "Pinter (2023, BoE Staff Working Paper 1019): the LDI sector sold about £36bn "
                "of gilts in three weeks"
            ),
            "ldi_source": PINTER,
            "ldi_window": ["2022-09-23", "2022-10-14"],
            "announcement_days": ["2022-09-28"],
            "announcement_note": (
                "Left out of the fit: the Bank's announcement itself moved the 30-year yield by "
                "more than 100 bp that day (Cunliffe, 5 Oct 2022), a move no flow explains"
            ),
            "ldi_profiles": {
                "even": "spread evenly over the three weeks",
                "front": "half in the first week (23-29 Sep), the rest evenly after",
                "spike": "a third on 26-28 Sep, the rest evenly after",
            },
            "depth_bn": 12.0,
            "depth_note": (
                "Cunliffe (5 Oct 2022): average trading of £12bn a day in the long-gilt sectors"
            ),
            "depth_source": CUNLIFFE_5,
            "boe_holdings": {
                "2022-09-28": 0.0,
                "2022-10-05": 3.657,
                "2022-10-12": 8.761,
                "2022-10-19": 19.259,
            },
            "boe_note": (
                "APF Q4 2022 report: temporary gilt holdings at each week's end, £bn; purchases "
                "spread evenly over each week's operations"
            ),
            "boe_source": APF_Q4,
            "boe_operation_days": ["2022-09-28", "2022-10-14"],
        },
        "annotations": [
            _note("2022-09-22", "MPC raises Bank Rate; long gilts +20 bp", CUNLIFFE_5),
            _note("2022-09-23", "The growth plan: long gilts +30 bp, sterling −4%", CUNLIFFE_5),
            _note(
                "2022-09-26",
                "30Y gilt +50 bp; LDI funds warn of at least £50bn of sales",
                CUNLIFFE_5,
            ),
            _note(
                "2022-09-28",
                "The Bank of England buys long gilts as a backstop: 30Y −100 bp",
                "https://www.bankofengland.co.uk/markets/market-notices/2022/september/market-notice-28-september-2022-gilt-market-operations",
            ),
            _note("2022-10-10", "Auction limit raised to £10bn a day", CUNLIFFE_18),
            _note("2022-10-11", "Index-linked gilts added to the purchases", CUNLIFFE_18),
            _note("2022-10-14", "The purchases end", CUNLIFFE_18),
        ],
    }
    series = boe_spot({"gilt10y": 10.0, "gilt30y": 30.0}, start, end)
    _write(episode, series)


def hike2022() -> None:
    start, end = date(2022, 2, 15), date(2023, 7, 31)
    episode: dict[str, Any] = {
        "id": "HIKE2022",
        "title": "The 2022-23 hiking cycle",
        "summary": (
            "Inflation drove the fastest Fed hikes in four decades and the start of QT; the "
            "curve inverted. RBI hiked in parallel, by 250 bp, as surplus liquidity drained."
        ),
        "model": "hike",
        "window": {"start": "2022-03-01", "end": "2023-07-31"},
        "drivers": ["fed_target", "fed_treasuries", "fed_mbs", "repo", "net_liquidity"],
        "targets": ["us2y", "us10y", "wacr"],
        "annotations": [],
    }
    series = {
        "fed_target": seed_series("fred/DFEDTARU", start, end),
        "fed_assets": seed_series("fred/WALCL", start, end),
        "fed_treasuries": seed_series("fred/TREAST", start, end),
        "fed_mbs": seed_series("fred/WSHOMCB", start, end),
        "gdp": seed_series("fred/GDP", date(2021, 10, 1), end),
        "us2y": seed_series("fred/DGS2", start, end),
        "us10y": seed_series("fred/DGS10", start, end),
        "repo": seed_series("rbi/mpc/repo", date(2014, 1, 1), end),
        "wacr": seed_series("rbi/mmo/wacr", start, end),
        "net_liquidity": seed_series("rbi/mmo/net_liquidity", start, end),
        "crr_requirement": seed_series("rbi/mmo/crr_requirement", start, end),
    }
    notes: list[dict[str, str]] = []
    for key, who, source in (
        ("fed_target", "FOMC", "FRED DFEDTARU"),
        ("repo", "RBI", "RBI MPC resolution (rbi/mpc/repo)"),
    ):
        levels, _ = series[key]
        for day, level, change in zip(
            pd.DatetimeIndex(levels.index), levels.to_numpy(), levels.diff().to_numpy(), strict=True
        ):
            if np.isfinite(change) and change and day >= pd.Timestamp(start):
                text = f"{who} {change * 100:+.0f} bp to {level:.2f}%"
                notes.append(_note(f"{day:%Y-%m-%d}", text, source))
    episode["annotations"] = sorted(notes, key=lambda n: n["date"])
    _write(episode, series)


def advtax() -> None:
    start, end = date(2022, 4, 8), date(2026, 10, 18)
    wacr, wacr_p = seed_series("rbi/mmo/wacr", start, end)
    repo, repo_p = seed_series("rbi/mpc/repo", date(2014, 1, 1), end)
    in_force = repo.reindex(wacr.index.union(repo.index)).ffill().reindex(wacr.index)
    spread = (wacr - in_force) * 100  # bp
    days = pd.DatetimeIndex(spread.index)
    window = days.month.isin([3, 6, 9, 12]) & (days.day >= 10) & (days.day <= 25)
    peaks = spread[window].groupby([days[window].year, days[window].month]).max()
    chosen = peaks.sort_values(ascending=False).head(3)
    segments: list[dict[str, Any]] = []
    picked = sorted((int(k[0]), int(k[1]), float(v)) for k, v in chosen.items())  # type: ignore[index]
    for year, month, peak in picked:
        first = date(year, month, 1)
        last = (pd.Timestamp(first) + pd.offsets.MonthEnd(1)).date()
        segments.append(
            {
                "start": f"{first:%Y-%m-%d}",
                "end": f"{last:%Y-%m-%d}",
                "peak_bp": round(float(peak), 1),
            }
        )
    episode: dict[str, Any] = {
        "id": "ADVTAX",
        "title": "Advance-tax liquidity squeezes",
        "summary": (
            "Around the 15th of March, June, September and December companies pay advance tax: "
            "money leaves the banks for the government's account and the call rate jumps. The "
            "three quarter-months shown are the ones whose WACR − repo rose highest between "
            "the 10th and the 25th since April 2022, picked from RBI's data."
        ),
        "model": "advtax",
        "window": {"start": segments[0]["start"], "end": segments[-1]["end"]},
        "segments": segments,
        "selection": (
            "the three highest peaks of WACR − repo between the 10th and the 25th of "
            "Mar/Jun/Sep/Dec, Apr 2022 on"
        ),
        "drivers": ["net_liquidity", "crr_requirement", "repo"],
        "targets": ["wacr"],
        "annotations": [
            _note(
                s["start"][:8] + "15",
                f"Advance tax due; WACR − repo peaked at {s['peak_bp']:+.0f} bp this month",
                "Income-tax Act, s. 211 (due dates); RBI Money Market Operations",
            )
            for s in segments
        ],
    }
    keep = np.zeros(len(days), dtype=bool)
    for s in segments:
        keep |= np.asarray((days >= pd.Timestamp(s["start"])) & (days <= pd.Timestamp(s["end"])))
    span = (pd.Timestamp(segments[0]["start"]) - pd.Timedelta(days=30)).date()
    series = {
        "wacr": (wacr[keep], wacr_p),
        "repo": (repo, repo_p),
        "net_liquidity": seed_series("rbi/mmo/net_liquidity", span, end),
        "crr_requirement": seed_series("rbi/mmo/crr_requirement", span, end),
    }
    _write(episode, series)


EPISODES = {
    "TAPER2013": taper2013,
    "DASH2020": dash2020,
    "GILT2022": gilt2022,
    "HIKE2022": hike2022,
    "ADVTAX": advtax,
}


def main(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    chosen = argv or list(EPISODES)
    unknown = set(chosen) - set(EPISODES)
    if unknown:
        print(f"unknown episodes: {sorted(unknown)}; choose from {list(EPISODES)}")
        return 2
    print("replays:")
    for name in chosen:
        EPISODES[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
