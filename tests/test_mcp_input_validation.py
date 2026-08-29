from __future__ import annotations

import asyncio
from typing import cast
from uuid import uuid4

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from mcp.server.mcpserver.exceptions import ToolError

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.interfaces.mcp import create_server


class _UnexpectedLineageService:
    def __init__(self) -> None:
        self.called = False

    def inspect(self, *_args: object, **_kwargs: object) -> object:
        self.called = True
        raise AssertionError("MCP input validation should reject the request first")


def test_mcp_rejects_non_integer_lineage_pagination_before_handler() -> None:
    service = _UnexpectedLineageService()
    server = create_server(lineage=cast(ClaimLineageService, service))

    for name, value in (("offset", None), ("limit", "many")):
        with pytest.raises(ToolError, match="Input should be a valid integer"):
            asyncio.run(
                server.call_tool(
                    "claim_lineage",
                    {"claim_id": str(uuid4()), name: value},
                )
            )
        assert service.called is False

    lineage_tool = next(
        tool for tool in asyncio.run(server.list_tools()) if tool.name == "claim_lineage"
    )
    properties = lineage_tool.input_schema["properties"]
    for name in ("offset", "limit", "evidence_offset", "evidence_limit"):
        assert properties[name]["type"] == "integer"
