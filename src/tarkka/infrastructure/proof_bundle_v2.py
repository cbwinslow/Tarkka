"""Canonical JSON helpers for proof-bundle v2 research-state members."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from tarkka.domain.proof_bundle_v2 import ProofBundleResearchState


class ProofBundleResearchStateJsonError(ValueError):
    """Raised when v2 research-state bytes are not canonical safe JSON."""


def canonical_research_state_bytes(value: object) -> bytes:
    """Encode one research-state value with Tarkka's canonical JSON representation."""
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return (text + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProofBundleResearchStateJsonError(
            "proof bundle research-state value is not JSON-compatible"
        ) from exc


def validate_canonical_research_state_bytes(data: bytes) -> None:
    """Fail closed unless bytes are canonical UTF-8 JSON with safe object semantics."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProofBundleResearchStateJsonError(
            "proof bundle research-state member is not valid UTF-8"
        ) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ProofBundleResearchStateJsonError(
            "proof bundle research-state member is not valid JSON"
        ) from exc
    if data != canonical_research_state_bytes(value):
        raise ProofBundleResearchStateJsonError(
            "proof bundle research-state member is not canonically encoded"
        )


def research_state_descriptor(data: bytes) -> ProofBundleResearchState:
    """Return the integrity descriptor for already-canonical research-state bytes."""
    validate_canonical_research_state_bytes(data)
    return ProofBundleResearchState(
        path="research/claim-lineage.json",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProofBundleResearchStateJsonError(
                f"proof bundle research-state member contains duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ProofBundleResearchStateJsonError(
        f"proof bundle research-state member contains non-finite number: {value}"
    )
