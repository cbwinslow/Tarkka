"""Deterministic Markdown, HTML, and JSON views for claim receipts."""

from __future__ import annotations

from html import escape

from tarkka.application.claim_receipts import ClaimReceipt, DocumentBrief


def claim_receipt_view(receipt: ClaimReceipt) -> dict[str, object]:
    """Serialize one receipt without lineage pagination or raw assessments."""
    return {
        "schema_version": receipt.schema_version,
        "claim_id": str(receipt.claim_id),
        "document_id": str(receipt.document_id),
        "claim_text": receipt.claim_text,
        "attribution": receipt.attribution.value,
        "quote": receipt.quote,
        "source_kind": receipt.source_kind,
        "locator": receipt.locator,
        "document_title": receipt.document_title,
        "artifact_sha256": receipt.artifact_sha256,
        "source_uri": receipt.source_uri,
        "relation_kinds": list(receipt.relation_kinds),
        "support_state": receipt.support_state,
        "human_review_state": receipt.human_review_state,
        "what_would_change_this": receipt.what_would_change_this,
    }


def document_brief_view(brief: DocumentBrief) -> dict[str, object]:
    """Serialize one document brief as ordered receipt views."""
    return {
        "schema_version": brief.schema_version,
        "document_id": str(brief.document_id),
        "document_title": brief.document_title,
        "offset": brief.offset,
        "limit": brief.limit,
        "receipts": [claim_receipt_view(item) for item in brief.receipts],
    }


def claim_receipt_markdown(receipt: ClaimReceipt) -> str:
    """Render one deterministic Markdown receipt."""
    quote = receipt.quote if receipt.quote is not None else "(no evidence quote)"
    locator = receipt.locator if receipt.locator is not None else "(none)"
    source_kind = receipt.source_kind if receipt.source_kind is not None else "(none)"
    source_uri = receipt.source_uri if receipt.source_uri is not None else "(none)"
    kinds = ", ".join(receipt.relation_kinds) if receipt.relation_kinds else "(none)"
    return "\n".join(
        (
            f"# Claim receipt ({receipt.schema_version})",
            f"claim_id: {receipt.claim_id}",
            f"document_id: {receipt.document_id}",
            f"title: {receipt.document_title}",
            f"claim: {receipt.claim_text}",
            f"attribution: {receipt.attribution.value}",
            f"support_state: {receipt.support_state}",
            f"relation_kinds: {kinds}",
            f"human_review_state: {receipt.human_review_state}",
            f"source_kind: {source_kind}",
            f"locator: {locator}",
            f"artifact_sha256: {receipt.artifact_sha256}",
            f"source_uri: {source_uri}",
            "## Quote",
            f"> {quote}",
            "## What would change this",
            receipt.what_would_change_this,
            "",
        )
    )


def claim_receipt_html(receipt: ClaimReceipt) -> str:
    """Render one deterministic HTML receipt from the same fields as Markdown."""
    payload = claim_receipt_view(receipt)
    rows = "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(_html_value(value))}</td></tr>"
        for key, value in payload.items()
        if key != "quote"
    )
    quote = receipt.quote if receipt.quote is not None else "(no evidence quote)"
    return (
        "<article class=\"tarkka-claim-receipt\">"
        f"<h1>Claim receipt ({escape(receipt.schema_version)})</h1>"
        f"<table>{rows}</table>"
        f"<h2>Quote</h2><blockquote>{escape(quote)}</blockquote>"
        "<h2>What would change this</h2>"
        f"<p>{escape(receipt.what_would_change_this)}</p>"
        "</article>\n"
    )


def document_brief_markdown(brief: DocumentBrief) -> str:
    """Render one deterministic Markdown brief of receipts."""
    header = "\n".join(
        (
            f"# Document brief ({brief.schema_version})",
            f"document_id: {brief.document_id}",
            f"title: {brief.document_title}",
            f"offset: {brief.offset}",
            f"limit: {brief.limit}",
            f"receipt_count: {len(brief.receipts)}",
            "",
        )
    )
    if not brief.receipts:
        return header + "(no claims)\n"
    body = "\n---\n".join(claim_receipt_markdown(item).rstrip() for item in brief.receipts)
    return header + body + "\n"


def document_brief_html(brief: DocumentBrief) -> str:
    """Render one deterministic HTML brief from the same fields as Markdown."""
    receipts = (
        "".join(claim_receipt_html(item) for item in brief.receipts)
        if brief.receipts
        else "<p>(no claims)</p>"
    )
    return (
        "<main class=\"tarkka-document-brief\">"
        f"<h1>Document brief ({escape(brief.schema_version)})</h1>"
        f"<p>document_id: {escape(str(brief.document_id))}</p>"
        f"<p>title: {escape(brief.document_title)}</p>"
        f"<p>offset: {brief.offset}</p>"
        f"<p>limit: {brief.limit}</p>"
        f"<p>receipt_count: {len(brief.receipts)}</p>"
        f"{receipts}"
        "</main>\n"
    )


def _html_value(value: object) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "(none)"
    return str(value)
