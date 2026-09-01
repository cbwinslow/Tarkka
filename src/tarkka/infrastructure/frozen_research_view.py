"""Strict projection of canonical Claim-lineage JSON into frozen diff fingerprints."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from tarkka.application.document_research_state import (
    DOCUMENT_RESEARCH_STATE_FORMAT,
    DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION,
)
from tarkka.application.frozen_research_diff import FrozenClaimState, FrozenEntityState
from tarkka.domain.extraction import AttributionKind, HumanReviewState
from tarkka.domain.verification import EvidenceRelationKind
from tarkka.infrastructure.proof_bundle_v2 import canonical_research_state_bytes


class FrozenResearchStateProjectionError(ValueError):
    """Raised when canonical JSON is not a complete valid frozen lineage view."""


def project_frozen_claims(
    value: object,
    *,
    expected_document_id: str,
    expected_artifact_id: str,
) -> tuple[FrozenClaimState, ...]:
    """Validate and fingerprint one complete document research-state view."""
    research = _mapping(value, "research state")
    _exact_keys(
        research,
        {"format", "schema_version", "document_id", "claims"},
        "research state",
    )
    if research["format"] != DOCUMENT_RESEARCH_STATE_FORMAT:
        raise FrozenResearchStateProjectionError("unsupported frozen research-state format")
    if research["schema_version"] != DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION:
        raise FrozenResearchStateProjectionError(
            "unsupported frozen research-state schema version"
        )
    document_id = _uuid(research["document_id"], "research-state document_id")
    if document_id != expected_document_id:
        raise FrozenResearchStateProjectionError(
            "research-state Document identity does not match verified Document"
        )
    raw_claims = _list(research["claims"], "research-state claims")

    claim_ids: set[str] = set()
    evidence_fingerprints: dict[str, str] = {}
    relation_ids: set[str] = set()
    projected: list[FrozenClaimState] = []
    for raw_claim in raw_claims:
        lineage = _mapping(raw_claim, "Claim lineage")
        _exact_keys(
            lineage,
            {
                "claim",
                "claim_source",
                "claim_evidence_page",
                "claim_evidence",
                "verification",
            },
            "Claim lineage",
        )
        claim = _mapping(lineage["claim"], "Claim")
        claim_id = _validate_claim(claim, expected_document_id=expected_document_id)
        if claim_id in claim_ids:
            raise FrozenResearchStateProjectionError(
                "frozen research state contains duplicate Claim identities"
            )
        claim_ids.add(claim_id)
        _validate_source_lineage(
            lineage["claim_source"],
            expected_document_id=expected_document_id,
            expected_artifact_id=expected_artifact_id,
            label="Claim source",
        )

        evidence_values = _complete_page(
            lineage["claim_evidence_page"],
            lineage["claim_evidence"],
            label="Claim evidence",
        )
        evidence = tuple(
            _validate_and_register_evidence(
                raw,
                evidence_fingerprints=evidence_fingerprints,
                expected_document_id=expected_document_id,
                expected_artifact_id=expected_artifact_id,
            )
            for raw in evidence_values
        )

        verification = _mapping(lineage["verification"], "Claim verification")
        assessments = _complete_verification_page(verification)
        verification_states: list[FrozenEntityState] = []
        for raw_assessment in assessments:
            assessment = _mapping(raw_assessment, "verification assessment")
            relation_id = _validate_assessment(
                assessment,
                evidence_fingerprints=evidence_fingerprints,
            )
            if relation_id in relation_ids:
                raise FrozenResearchStateProjectionError(
                    "frozen research state reuses a verification relation identity"
                )
            relation_ids.add(relation_id)
            verification_states.append(_fingerprint(relation_id, assessment))

        projected.append(
            FrozenClaimState(
                claim=_fingerprint(
                    claim_id,
                    {"claim": lineage["claim"], "claim_source": lineage["claim_source"]},
                ),
                evidence=tuple(sorted(evidence)),
                verifications=tuple(sorted(verification_states)),
            )
        )
    return tuple(sorted(projected, key=lambda item: item.claim.entity_id))


def _validate_claim(value: Mapping[str, Any], *, expected_document_id: str) -> str:
    _exact_keys(
        value,
        {
            "claim_id",
            "document_id",
            "text",
            "claim_type",
            "confidence",
            "human_review_state",
            "attribution",
            "extraction_run",
        },
        "Claim",
    )
    claim_id = _uuid(value["claim_id"], "Claim claim_id")
    document_id = _uuid(value["document_id"], "Claim document_id")
    if document_id != expected_document_id:
        raise FrozenResearchStateProjectionError("frozen Claim belongs to a different Document")
    _non_blank_string(value["text"], "Claim text")
    _non_blank_string(value["claim_type"], "Claim type")
    _unit_number(value["confidence"], "Claim confidence")
    _enum_string(value["human_review_state"], HumanReviewState, "Claim human_review_state")
    _enum_string(value["attribution"], AttributionKind, "Claim attribution")
    _validate_extraction_run(value["extraction_run"], expected_document_id=document_id)
    return claim_id


def _validate_extraction_run(value: object, *, expected_document_id: str) -> None:
    run = _mapping(value, "extraction run")
    _exact_keys(
        run,
        {
            "run_id",
            "document_id",
            "extractor_name",
            "extractor_version",
            "contract_version",
            "model",
            "extracted_at",
        },
        "extraction run",
    )
    _uuid(run["run_id"], "extraction run run_id")
    document_id = _uuid(run["document_id"], "extraction run document_id")
    if document_id != expected_document_id:
        raise FrozenResearchStateProjectionError(
            "frozen extraction run belongs to a different Document"
        )
    _non_blank_string(run["extractor_name"], "extractor_name")
    _non_blank_string(run["extractor_version"], "extractor_version")
    _non_blank_string(run["contract_version"], "contract_version")
    _non_blank_string(run["extracted_at"], "extracted_at")
    model = run["model"]
    if model is not None:
        model_view = _mapping(model, "extraction model")
        _exact_keys(model_view, {"provider", "name", "version"}, "extraction model")
        _non_blank_string(model_view["provider"], "model provider")
        _non_blank_string(model_view["name"], "model name")
        _optional_non_blank_string(model_view["version"], "model version")


def _validate_source_lineage(
    value: object,
    *,
    expected_document_id: str | None,
    expected_artifact_id: str | None,
    label: str,
) -> tuple[str, str]:
    lineage = _mapping(value, label)
    _exact_keys(lineage, {"document", "artifact"}, label)
    document = _mapping(lineage["document"], f"{label} Document")
    _exact_keys(
        document,
        {"document_id", "artifact_id", "title", "parser_name", "parser_version"},
        f"{label} Document",
    )
    document_id = _uuid(document["document_id"], f"{label} document_id")
    artifact_id = _uuid(document["artifact_id"], f"{label} artifact_id")
    if expected_document_id is not None and document_id != expected_document_id:
        raise FrozenResearchStateProjectionError(f"frozen {label} belongs to a different Document")
    if expected_artifact_id is not None and artifact_id != expected_artifact_id:
        raise FrozenResearchStateProjectionError(f"frozen {label} belongs to a different Artifact")
    _string(document["title"], f"{label} title")
    _non_blank_string(document["parser_name"], f"{label} parser_name")
    _non_blank_string(document["parser_version"], f"{label} parser_version")

    artifact = _mapping(lineage["artifact"], f"{label} Artifact")
    _exact_keys(
        artifact,
        {"artifact_id", "sha256", "size_bytes", "media_type", "source_uri"},
        f"{label} Artifact",
    )
    lineage_artifact_id = _uuid(artifact["artifact_id"], f"{label} Artifact artifact_id")
    if lineage_artifact_id != artifact_id:
        raise FrozenResearchStateProjectionError(
            f"frozen {label} Document and Artifact identities disagree"
        )
    _sha256(artifact["sha256"], f"{label} Artifact sha256")
    _non_negative_integer(artifact["size_bytes"], f"{label} Artifact size_bytes")
    _non_blank_string(artifact["media_type"], f"{label} Artifact media_type")
    _optional_string(artifact["source_uri"], f"{label} Artifact source_uri")
    return document_id, artifact_id


def _validate_and_register_evidence(
    value: object,
    *,
    evidence_fingerprints: dict[str, str],
    expected_document_id: str | None,
    expected_artifact_id: str | None,
) -> FrozenEntityState:
    evidence = _mapping(value, "Evidence")
    evidence_id = _uuid(evidence.get("evidence_id"), "Evidence evidence_id")
    source_kind = _non_blank_string(evidence.get("source_kind"), "Evidence source_kind")
    expected_variant_fields = {
        "passage": {
            "section_id",
            "passage_id",
            "passage_char_start",
            "passage_char_end",
            "text",
        },
        "figure": {"figure_id", "ordinal", "page_number", "label", "caption", "figure_type"},
        "table": {
            "table_id",
            "row_start",
            "row_end",
            "column_start",
            "column_end",
            "ordinal",
            "page_number",
            "label",
            "caption",
            "row_count",
            "column_count",
        },
        "equation": {"equation_id", "ordinal", "page_number", "label", "source_text"},
    }
    variant_fields = expected_variant_fields.get(source_kind)
    if variant_fields is None:
        raise FrozenResearchStateProjectionError("unsupported frozen Evidence source_kind")
    _exact_keys(
        evidence,
        {"evidence_id", "extraction_run", "document", "artifact", "source_kind"}
        | variant_fields,
        "Evidence",
    )
    document_id, _ = _validate_source_lineage(
        {"document": evidence["document"], "artifact": evidence["artifact"]},
        expected_document_id=expected_document_id,
        expected_artifact_id=expected_artifact_id,
        label="Evidence source",
    )
    _validate_extraction_run(evidence["extraction_run"], expected_document_id=document_id)
    if source_kind == "passage":
        _uuid(evidence["section_id"], "Evidence section_id")
        _uuid(evidence["passage_id"], "Evidence passage_id")
        start = _non_negative_integer(evidence["passage_char_start"], "Evidence passage_char_start")
        end = _positive_integer(evidence["passage_char_end"], "Evidence passage_char_end")
        text = _non_blank_string(evidence["text"], "Evidence text")
        if end <= start or end - start != len(text):
            raise FrozenResearchStateProjectionError("frozen Evidence passage range is invalid")
    elif source_kind == "figure":
        _uuid(evidence["figure_id"], "Evidence figure_id")
        _non_negative_integer(evidence["ordinal"], "Evidence ordinal")
        _optional_non_negative_integer(evidence["page_number"], "Evidence page_number")
        _optional_string(evidence["label"], "Evidence label")
        _optional_string(evidence["caption"], "Evidence caption")
        _optional_string(evidence["figure_type"], "Evidence figure_type")
    elif source_kind == "table":
        _uuid(evidence["table_id"], "Evidence table_id")
        row_start = _non_negative_integer(evidence["row_start"], "Evidence row_start")
        row_end = _positive_integer(evidence["row_end"], "Evidence row_end")
        column_start = _non_negative_integer(evidence["column_start"], "Evidence column_start")
        column_end = _positive_integer(evidence["column_end"], "Evidence column_end")
        if row_end <= row_start or column_end <= column_start:
            raise FrozenResearchStateProjectionError("frozen table Evidence range is invalid")
        _non_negative_integer(evidence["ordinal"], "Evidence ordinal")
        _optional_non_negative_integer(evidence["page_number"], "Evidence page_number")
        _optional_string(evidence["label"], "Evidence label")
        _optional_string(evidence["caption"], "Evidence caption")
        _optional_non_negative_integer(evidence["row_count"], "Evidence row_count")
        _optional_non_negative_integer(evidence["column_count"], "Evidence column_count")
    else:
        _uuid(evidence["equation_id"], "Evidence equation_id")
        _non_negative_integer(evidence["ordinal"], "Evidence ordinal")
        _optional_non_negative_integer(evidence["page_number"], "Evidence page_number")
        _optional_string(evidence["label"], "Evidence label")
        _string(evidence["source_text"], "Evidence source_text")

    state = _fingerprint(evidence_id, evidence)
    prior = evidence_fingerprints.get(evidence_id)
    if prior is not None and prior != state.sha256:
        raise FrozenResearchStateProjectionError(
            "frozen research state reuses Evidence identity with different content"
        )
    evidence_fingerprints[evidence_id] = state.sha256
    return state


def _validate_assessment(
    value: Mapping[str, Any],
    *,
    evidence_fingerprints: dict[str, str],
) -> str:
    _exact_keys(
        value,
        {
            "relation_id",
            "kind",
            "verifier_name",
            "verifier_version",
            "confidence",
            "human_review_state",
            "reasoning_summary",
            "created_at",
            "evidence",
            "citation_context",
        },
        "verification assessment",
    )
    relation_id = _uuid(value["relation_id"], "verification relation_id")
    kind = _enum_string(value["kind"], EvidenceRelationKind, "verification kind")
    _non_blank_string(value["verifier_name"], "verification verifier_name")
    _non_blank_string(value["verifier_version"], "verification verifier_version")
    _unit_number(value["confidence"], "verification confidence")
    _enum_string(
        value["human_review_state"],
        HumanReviewState,
        "verification human_review_state",
    )
    _optional_non_blank_string(value["reasoning_summary"], "verification reasoning_summary")
    _non_blank_string(value["created_at"], "verification created_at")
    evidence = value["evidence"]
    if kind == EvidenceRelationKind.NO_EVIDENCE.value:
        if evidence is not None:
            raise FrozenResearchStateProjectionError(
                "frozen no_evidence verification relation must not identify Evidence"
            )
    elif evidence is None:
        raise FrozenResearchStateProjectionError(
            "frozen verification relation must identify exact Evidence"
        )
    else:
        _validate_and_register_evidence(
            evidence,
            evidence_fingerprints=evidence_fingerprints,
            expected_document_id=None,
            expected_artifact_id=None,
        )
    _validate_citation_context(value["citation_context"])
    return relation_id


def _validate_citation_context(value: object) -> None:
    if value is None:
        return
    context = _mapping(value, "citation context")
    _exact_keys(
        context,
        {
            "context_id",
            "mention_id",
            "text",
            "section_id",
            "passage_id",
            "char_start",
            "char_end",
        },
        "citation context",
    )
    _uuid(context["context_id"], "citation context context_id")
    _uuid(context["mention_id"], "citation context mention_id")
    text = _non_blank_string(context["text"], "citation context text")
    _optional_uuid(context["section_id"], "citation context section_id")
    _optional_uuid(context["passage_id"], "citation context passage_id")
    start = _non_negative_integer(context["char_start"], "citation context char_start")
    end = _non_negative_integer(context["char_end"], "citation context char_end")
    if end < start or end - start != len(text):
        raise FrozenResearchStateProjectionError("frozen citation context range is invalid")


def _complete_page(page_value: object, values: object, *, label: str) -> list[Any]:
    page = _mapping(page_value, f"{label} page")
    _exact_keys(page, {"offset", "limit", "total"}, f"{label} page")
    items = _list(values, label)
    total = _non_negative_integer(page["total"], f"{label} total")
    offset = _non_negative_integer(page["offset"], f"{label} offset")
    limit = _non_negative_integer(page["limit"], f"{label} limit")
    if offset != 0 or total != len(items) or limit != total:
        raise FrozenResearchStateProjectionError(f"{label} page is not a complete frozen view")
    return items


def _complete_verification_page(value: Mapping[str, Any]) -> list[Any]:
    _exact_keys(value, {"offset", "limit", "total", "assessments"}, "Claim verification page")
    return _complete_page(
        {key: value[key] for key in ("offset", "limit", "total")},
        value["assessments"],
        label="verification assessment",
    )


def _fingerprint(entity_id: str, value: object) -> FrozenEntityState:
    return FrozenEntityState(
        entity_id=entity_id,
        sha256=hashlib.sha256(canonical_research_state_bytes(value)).hexdigest(),
    )


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise FrozenResearchStateProjectionError(
            f"frozen {label} has unexpected or missing fields"
        )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FrozenResearchStateProjectionError(f"frozen {label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise FrozenResearchStateProjectionError(f"frozen {label} must be an array")
    return value


def _uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise FrozenResearchStateProjectionError(f"frozen {label} must be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise FrozenResearchStateProjectionError(f"frozen {label} must be a UUID string") from exc
    if str(parsed) != value:
        raise FrozenResearchStateProjectionError(
            f"frozen {label} must use canonical UUID spelling"
        )
    return value


def _optional_uuid(value: object, label: str) -> str | None:
    return None if value is None else _uuid(value, label)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise FrozenResearchStateProjectionError(f"frozen {label} must be a string")
    return value


def _non_blank_string(value: object, label: str) -> str:
    text = _string(value, label)
    if not text.strip():
        raise FrozenResearchStateProjectionError(f"frozen {label} must not be blank")
    return text


def _optional_string(value: object, label: str) -> str | None:
    return None if value is None else _string(value, label)


def _optional_non_blank_string(value: object, label: str) -> str | None:
    return None if value is None else _non_blank_string(value, label)


def _non_negative_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FrozenResearchStateProjectionError(f"frozen {label} must be a non-negative integer")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _non_negative_integer(value, label)
    if result == 0:
        raise FrozenResearchStateProjectionError(f"frozen {label} must be positive")
    return result


def _optional_non_negative_integer(value: object, label: str) -> int | None:
    return None if value is None else _non_negative_integer(value, label)


def _unit_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrozenResearchStateProjectionError(f"frozen {label} must be a number")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise FrozenResearchStateProjectionError(f"frozen {label} must be between 0 and 1")
    return result


def _enum_string(value: object, enum_type: type[Any], label: str) -> str:
    text = _non_blank_string(value, label)
    try:
        enum_type(text)
    except ValueError as exc:
        raise FrozenResearchStateProjectionError(f"frozen {label} is unsupported") from exc
    return text


def _sha256(value: object, label: str) -> str:
    text = _string(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise FrozenResearchStateProjectionError(f"frozen {label} must be a lowercase SHA-256")
    return text
