"""MoSPI through its MCP server: the JSON-RPC client, the CPI and GDP parsers and the adapter."""

import json
from datetime import date
from pathlib import Path

import httpx2
import pytest

from app.data.mcp import decode_message, tool_result
from app.data.sources.base import SourceError
from app.data.sources.mospi import (
    MospiAdapter,
    parse_cpi_2012,
    parse_cpi_2024,
    parse_nas,
    quarter_start,
)
from tests.support import make_fetcher

FIXTURES = Path(__file__).parent / "fixtures" / "india"
CPI_2012 = (FIXTURES / "mospi_cpi2012_2025.txt").read_bytes()
CPI_2024 = (FIXTURES / "mospi_cpi2024_2026-02.txt").read_bytes()
GDP_2022 = (FIXTURES / "mospi_gdp2022_growth.txt").read_bytes()


def rows(body: bytes) -> list[dict[str, object]]:
    data = tool_result(decode_message(body))["data"]
    assert isinstance(data, list)
    return data


def test_decodes_event_streams_and_plain_json() -> None:
    message = decode_message(CPI_2024)
    assert message["id"] == 1
    assert decode_message(b'{"jsonrpc": "2.0", "id": 7, "result": {}}')["id"] == 7
    with pytest.raises(SourceError, match="no JSON-RPC message"):
        decode_message(b"event: ping\n\n")


def test_tool_errors_are_source_errors() -> None:
    with pytest.raises(SourceError, match="tool error"):
        tool_result({"result": {"isError": True, "content": [{"type": "text", "text": "x"}]}})
    with pytest.raises(SourceError, match="-32601"):
        tool_result({"error": {"code": -32601, "message": "Method not found"}})
    text = json.dumps({"data": [], "msg": "ok"})
    assert tool_result({"result": {"content": [{"type": "text", "text": text}]}}) == {
        "data": [],
        "msg": "ok",
    }


def test_cpi_2012_groups_and_published_inflation() -> None:
    parsed = parse_cpi_2012(rows(CPI_2012))
    assert set(parsed) == {
        *(
            f"cpi2012:{k}"
            for k in (
                "general", "food_beverages", "pan_tobacco", "clothing_footwear", "housing",
                "fuel_light", "miscellaneous",
            )
        ),
        "cpi2012:general_yoy",
    }  # fmt: skip
    general = dict(parsed["cpi2012:general"])
    assert len(general) == 12
    assert general[date(2025, 12, 1)] == 198.0
    assert dict(parsed["cpi2012:general_yoy"])[date(2025, 12, 1)] == 1.33
    assert dict(parsed["cpi2012:fuel_light"])[date(2025, 12, 1)] == 181.3


def test_cpi_2024_divisions_and_division_04_groups() -> None:
    parsed = parse_cpi_2024(rows(CPI_2024))
    feb = date(2026, 2, 1)
    assert dict(parsed["cpi2024:00"])[feb] == 104.57
    assert dict(parsed["cpi2024:general_yoy"])[feb] == 3.21
    assert dict(parsed["cpi2024:01"])[feb] == 103.87
    assert dict(parsed["cpi2024:04.5"])[feb] == 100.46
    divisions = {k for k in parsed if len(k.split(":")[1]) == 2 and k != "cpi2024:00"}
    assert len(divisions) == 12  # COICOP 2018 divisions as MoSPI publishes them (no 12)
    assert not any(k.count(".") > 1 for k in parsed)  # classes and below are left out


def test_gdp_quarters_follow_the_financial_year() -> None:
    assert quarter_start("2025-26", "Q1") == date(2025, 4, 1)
    assert quarter_start("2025-26", "Q4") == date(2026, 1, 1)
    with pytest.raises(ValueError, match="no quarter"):
        quarter_start("2025-26", "Q5")
    growth = dict(parse_nas(rows(GDP_2022)))
    assert growth[date(2026, 4, 1)] == 7.8  # Q1 2026-27
    assert growth[date(2025, 4, 1)] == 6.9


def test_adapter_routes_each_call_and_keeps_the_rest_on_errors(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        call = json.loads(request.content)
        assert call["method"] == "tools/call"
        filters = call["params"]["arguments"]["filters"]
        body: bytes | None
        if filters.get("base_year") == "2012":
            body = CPI_2012
        elif filters.get("base_year") == "2024":
            body = CPI_2024 if filters["month_code"] == "2" and filters["page"] == "1" else None
        elif filters.get("base_year") == "2022-23" and filters["indicator_code"] == "22":
            body = GDP_2022
        else:
            return httpx2.Response(500)
        if body is None:  # later months: not yet published
            reply = {"structuredContent": {"data": [], "statusCode": True}}
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": reply}).encode()
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    adapter = MospiAdapter(make_fetcher(handler, tmp_path), pause_s=0)
    outcome = adapter.fetch(start=date(2026, 2, 1), end=date(2026, 3, 31))
    ids = {f.spec.series_id for f in outcome.frames}
    assert "mospi/cpi/2024/cp04_5" in ids
    assert "mospi/gdp/2022/real_growth" in ids
    assert "mospi/cpi/2012/general" not in ids  # base 2012 ends in 2025
    assert any(key.startswith("gdp2011") for key in outcome.errors)  # the 500s
