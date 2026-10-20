"""Source adapters and the factory that wires them to one shared HTTP client and raw cache."""

import httpx2

import app
from app.config import Settings
from app.data.http import Fetcher, RawCache
from app.data.sources.base import Adapter
from app.data.sources.fbil import FbilAdapter
from app.data.sources.fbil_gsec import FbilGsecAdapter
from app.data.sources.fiscaldata import FiscalDataAdapter
from app.data.sources.fred import FredAdapter
from app.data.sources.nsdl import NsdlAdapter
from app.data.sources.rbi import RbiAdapter
from app.data.sources.tic import TicAdapter
from app.data.sources.treasury import TreasuryCurveAdapter

USER_AGENT = (
    f"SovereignDesk/{app.__version__} (research terminal; https://github.com/adityashukla2615)"
)


def make_client(settings: Settings) -> httpx2.Client:
    return httpx2.Client(
        timeout=settings.http_timeout_s,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def build_adapters(settings: Settings, client: httpx2.Client) -> dict[str, Adapter]:
    fetcher = Fetcher(client, RawCache(settings.cache_dir))
    adapters: list[Adapter] = [
        FredAdapter(fetcher, settings.fred_api_key),
        TreasuryCurveAdapter(fetcher),
        FiscalDataAdapter(fetcher),
        TicAdapter(fetcher),
        RbiAdapter(fetcher),
        FbilAdapter(fetcher),
        FbilGsecAdapter(fetcher),
        NsdlAdapter(fetcher),
    ]
    return {a.source: a for a in adapters}


__all__ = ["build_adapters", "make_client"]
