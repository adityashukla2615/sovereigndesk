"""A minimal client for MCP servers over Streamable HTTP (JSON-RPC 2.0).

Some official publishers offer data to software through an MCP server (MoSPI's eSankhyiki
names it as the machine-access route for its statistics). Calls go through the shared Fetcher,
so they are retried, kept raw in the cache for offline fallback, and carry provenance like any
other request. The server may answer with plain JSON or a server-sent-event stream; either way
the last JSON-RPC message is the reply.
"""

import json
from typing import Any

from app.data.http import FetchedBody, Fetcher
from app.data.sources.base import SourceError

PROTOCOL_VERSION = "2025-06-18"


def decode_message(content: bytes) -> dict[str, Any]:
    """The JSON-RPC message in a response body: the body itself, or the last ``data:`` frame of
    an event stream."""
    text = content.decode("utf-8", "replace").strip()
    if not text.startswith("{"):
        frames = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        if not frames:
            raise SourceError("mcp: the response holds no JSON-RPC message")
        text = frames[-1]
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(f"mcp: unreadable JSON-RPC message: {exc}") from None
    if not isinstance(message, dict):
        raise SourceError("mcp: the JSON-RPC message is not an object")
    return message


def tool_result(message: dict[str, Any]) -> dict[str, Any]:
    """The structured result of a ``tools/call``; protocol and tool errors raise SourceError."""
    if "error" in message:
        raise SourceError(f"mcp: {message['error']}")
    result = message.get("result")
    if not isinstance(result, dict):
        raise SourceError("mcp: the reply has no result")
    if result.get("isError"):
        raise SourceError(f"mcp: tool error: {str(result.get('content'))[:300]}")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        try:
            structured = json.loads(texts[0]) if texts else None
        except json.JSONDecodeError:
            structured = None
    if not isinstance(structured, dict):
        raise SourceError("mcp: the tool returned no structured data")
    return structured


class McpClient:
    def __init__(self, fetcher: Fetcher, source: str, url: str) -> None:
        self.fetcher = fetcher
        self.source = source
        self.url = url
        self._ids = 0

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }

    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    def initialize(self) -> dict[str, Any]:
        """The protocol handshake: the server's name, version and capabilities."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "sovereigndesk", "version": "0.1"},
            },
        }
        body = self.fetcher.post_json(
            self.source, self.url, payload, identity="initialize", headers=self._headers()
        )
        message = decode_message(body.content)
        result = message.get("result")
        if not isinstance(result, dict):
            raise SourceError(f"mcp: initialize failed: {message.get('error')}")
        return result

    def call(self, tool: str, arguments: dict[str, Any]) -> tuple[FetchedBody, dict[str, Any]]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        identity = f"tools/call {tool} {json.dumps(arguments, sort_keys=True)}"
        body = self.fetcher.post_json(
            self.source, self.url, payload, identity=identity, headers=self._headers()
        )
        return body, tool_result(decode_message(body.content))
