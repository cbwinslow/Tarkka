from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip("mcp", reason="MCP tests require the optional 'mcp' extra")

from tarkka.interfaces.mcp import create_server


def test_mcp_document_section_rejects_an_invalid_document_before_backend_lookup() -> None:
    server = create_server()

    result = asyncio.run(
        server.call_tool(
            "document_section",
            {"document_id": "not-a-document", "section_id": str(uuid4())},
        )
    )

    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    response: dict[str, Any] = result.structured_content
    assert response["error"]["code"] == "invalid_argument"
