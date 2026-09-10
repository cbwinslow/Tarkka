"""JSON view for budgeted research get/expand results."""

from __future__ import annotations

from tarkka.application.research_get import ResearchGetResult


def research_get_view(result: ResearchGetResult) -> dict[str, object]:
    """Serialize one walleted representation without extra source text."""
    return {
        "resource_id": result.resource_id,
        "kind": result.kind,
        "representation": result.representation,
        "estimated_tokens": result.estimated_tokens,
        "may_send_to_model": result.may_send_to_model,
        "payload": result.payload,
    }
