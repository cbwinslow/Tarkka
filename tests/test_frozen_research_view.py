from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from tarkka.application.document_research_state import document_research_state_view
from tarkka.infrastructure.frozen_research_view import (
    FrozenResearchStateProjectionError,
    project_frozen_claims,
)
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.proof_bundle_snapshot import JsonProofBundleV2SnapshotReader
from tests.support.claim_lineage import persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _valid_state(home: Path) -> tuple[dict[str, Any], str, str]:
    fixture = persist_local_claim_lineage(home)
    documents = JsonResearchRepository.open_existing(home / "catalog.json")
    assert documents is not None
    snapshot = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations_path=home / "source_observations.json",
        extractions_path=home / "extractions.json",
        verifications_path=home / "verifications.json",
        citations_path=home / "citations.json",
    ).read(fixture.document.document_id)
    assert snapshot is not None
    return (
        cast(dict[str, Any], copy.deepcopy(document_research_state_view(snapshot.research_state))),
        str(fixture.document.document_id),
        str(fixture.artifact.artifact_id),
    )


def _lineage(state: dict[str, Any]) -> dict[str, Any]:
    claims = cast(list[dict[str, Any]], state["claims"])
    return claims[0]


def _claim(state: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _lineage(state)["claim"])


def _claim_source(state: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _lineage(state)["claim_source"])


def _evidence(state: dict[str, Any], source_kind: str) -> dict[str, Any]:
    values = cast(list[dict[str, Any]], _lineage(state)["claim_evidence"])
    return next(item for item in values if item["source_kind"] == source_kind)


def _verification(state: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _lineage(state)["verification"])


def _assessment(state: dict[str, Any]) -> dict[str, Any]:
    values = cast(list[dict[str, Any]], _verification(state)["assessments"])
    return values[0]


def _project(state: dict[str, Any], document_id: str, artifact_id: str) -> None:
    project_frozen_claims(
        state,
        expected_document_id=document_id,
        expected_artifact_id=artifact_id,
    )


def test_projector_accepts_domain_valid_optional_null_variants(tmp_path: Path) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path / "optional")
    claim_run = cast(dict[str, Any], _claim(state)["extraction_run"])
    claim_run["model"] = None

    passage = _evidence(state, "passage")
    passage_run = cast(dict[str, Any], passage["extraction_run"])
    passage_model = cast(dict[str, Any], passage_run["model"])
    passage_model["version"] = None

    source_artifact = cast(dict[str, Any], _claim_source(state)["artifact"])
    source_artifact["source_uri"] = None

    figure = _evidence(state, "figure")
    for key in ("page_number", "label", "caption", "figure_type"):
        figure[key] = None

    table = _evidence(state, "table")
    for key in ("page_number", "label", "caption", "row_count", "column_count"):
        table[key] = None

    equation = _evidence(state, "equation")
    for key in ("page_number", "label"):
        equation[key] = None

    assessment = _assessment(state)
    assessment["reasoning_summary"] = "Reviewed against exact evidence."
    context = cast(dict[str, Any], assessment["citation_context"])
    context["section_id"] = None
    context["passage_id"] = None

    _project(state, document_id, artifact_id)

    no_evidence_state, document_id, artifact_id = _valid_state(tmp_path / "no-evidence")
    assessment = _assessment(no_evidence_state)
    assessment["kind"] = "no_evidence"
    assessment["evidence"] = None
    assessment["citation_context"] = None

    _project(no_evidence_state, document_id, artifact_id)


def test_projector_rejects_non_object_root(tmp_path: Path) -> None:
    _, document_id, artifact_id = _valid_state(tmp_path)

    with pytest.raises(FrozenResearchStateProjectionError, match="must be an object"):
        project_frozen_claims(
            [],
            expected_document_id=document_id,
            expected_artifact_id=artifact_id,
        )


def test_projector_rejects_research_document_identity_mismatch(tmp_path: Path) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path)
    state["document_id"] = str(UUID(int=999))

    with pytest.raises(FrozenResearchStateProjectionError, match="does not match verified Document"):
        _project(state, document_id, artifact_id)


def test_projector_rejects_duplicate_claim_identity(tmp_path: Path) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path)
    claims = cast(list[dict[str, Any]], state["claims"])
    claims.append(copy.deepcopy(claims[0]))

    with pytest.raises(FrozenResearchStateProjectionError, match="duplicate Claim identities"):
        _project(state, document_id, artifact_id)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("claim_document", "Claim belongs to a different Document"),
        ("run_document", "extraction run belongs to a different Document"),
        ("source_document", "Claim source belongs to a different Document"),
        ("source_artifact", "Claim source belongs to a different Artifact"),
        ("source_disagreement", "Document and Artifact identities disagree"),
    ],
)
def test_projector_rejects_cross_record_identity_conflicts(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path / case)
    other = str(UUID(int=999))
    claim = _claim(state)
    source = _claim_source(state)
    source_document = cast(dict[str, Any], source["document"])
    source_artifact = cast(dict[str, Any], source["artifact"])

    if case == "claim_document":
        claim["document_id"] = other
    elif case == "run_document":
        cast(dict[str, Any], claim["extraction_run"])["document_id"] = other
    elif case == "source_document":
        source_document["document_id"] = other
    elif case == "source_artifact":
        source_document["artifact_id"] = other
        source_artifact["artifact_id"] = other
    else:
        source_artifact["artifact_id"] = other

    with pytest.raises(FrozenResearchStateProjectionError, match=message):
        _project(state, document_id, artifact_id)


@pytest.mark.parametrize(
    ("case", "value", "message"),
    [
        ("claim_id", 7, "must be a UUID string"),
        ("claim_id", "not-a-uuid", "must be a UUID string"),
        ("claim_id", "{00000000-0000-0000-0000-000000000008}", "canonical UUID spelling"),
        ("text", 7, "Claim text must be a string"),
        ("text", "   ", "Claim text must not be blank"),
        ("confidence", True, "Claim confidence must be a number"),
        ("confidence", "1", "Claim confidence must be a number"),
        ("confidence", 1.1, "Claim confidence must be between 0 and 1"),
        ("human_review_state", "unknown", "human_review_state is unsupported"),
        ("attribution", "unknown", "Claim attribution is unsupported"),
    ],
)
def test_projector_rejects_invalid_claim_scalars(
    tmp_path: Path,
    case: str,
    value: object,
    message: str,
) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path / f"{case}-{type(value).__name__}")
    _claim(state)[case] = value

    with pytest.raises(FrozenResearchStateProjectionError, match=message):
        _project(state, document_id, artifact_id)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("model_version_blank", "model version must not be blank"),
        ("title_type", "Claim source title must be a string"),
        ("parser_blank", "Claim source parser_name must not be blank"),
        ("sha_short", "lowercase SHA-256"),
        ("sha_character", "lowercase SHA-256"),
        ("size_type", "size_bytes must be a non-negative integer"),
        ("size_bool", "size_bytes must be a non-negative integer"),
        ("size_negative", "size_bytes must be a non-negative integer"),
        ("media_blank", "media_type must not be blank"),
        ("source_uri_type", "source_uri must be a string"),
    ],
)
def test_projector_rejects_invalid_source_and_run_scalars(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path / case)
    claim = _claim(state)
    source = _claim_source(state)
    source_document = cast(dict[str, Any], source["document"])
    source_artifact = cast(dict[str, Any], source["artifact"])

    if case == "model_version_blank":
        run = cast(dict[str, Any], claim["extraction_run"])
        cast(dict[str, Any], run["model"])["version"] = " "
    elif case == "title_type":
        source_document["title"] = 1
    elif case == "parser_blank":
        source_document["parser_name"] = " "
    elif case == "sha_short":
        source_artifact["sha256"] = "a"
    elif case == "sha_character":
        source_artifact["sha256"] = "g" * 64
    elif case == "size_type":
        source_artifact["size_bytes"] = "1"
    elif case == "size_bool":
        source_artifact["size_bytes"] = True
    elif case == "size_negative":
        source_artifact["size_bytes"] = -1
    elif case == "media_blank":
        source_artifact["media_type"] = " "
    else:
        source_artifact["source_uri"] = 1

    with pytest.raises(FrozenResearchStateProjectionError, match=message):
        _project(state, document_id, artifact_id)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("not_object", "Evidence must be an object"),
        ("source_kind", "unsupported frozen Evidence source_kind"),
        ("passage_zero_end", "passage_char_end must be positive"),
        ("passage_range", "Evidence passage range is invalid"),
        ("figure_page", "page_number must be a non-negative integer"),
        ("table_row", "table Evidence range is invalid"),
        ("table_column", "table Evidence range is invalid"),
        ("equation_text", "source_text must be a string"),
    ],
)
def test_projector_rejects_invalid_evidence_semantics(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path / case)
    lineage = _lineage(state)

    if case == "not_object":
        values = cast(list[Any], lineage["claim_evidence"])
        values[0] = "not-an-object"
    elif case == "source_kind":
        _evidence(state, "passage")["source_kind"] = "audio"
    elif case == "passage_zero_end":
        _evidence(state, "passage")["passage_char_end"] = 0
    elif case == "passage_range":
        _evidence(state, "passage")["passage_char_end"] = 6
    elif case == "figure_page":
        _evidence(state, "figure")["page_number"] = -1
    elif case == "table_row":
        table = _evidence(state, "table")
        table["row_start"] = 1
        table["row_end"] = 1
    elif case == "table_column":
        table = _evidence(state, "table")
        table["column_start"] = 1
        table["column_end"] = 1
    else:
        _evidence(state, "equation")["source_text"] = 1

    with pytest.raises(FrozenResearchStateProjectionError, match=message):
        _project(state, document_id, artifact_id)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("page_object", "Claim evidence page must be an object"),
        ("page_keys", "Claim evidence page has unexpected or missing fields"),
        ("items_list", "Claim evidence must be an array"),
        ("offset_type", "Claim evidence offset must be a non-negative integer"),
        ("offset_bool", "Claim evidence offset must be a non-negative integer"),
        ("offset_negative", "Claim evidence offset must be a non-negative integer"),
        ("verification_keys", "Claim verification page has unexpected or missing fields"),
        ("assessment_list", "verification assessment must be an array"),
        ("assessment_object", "verification assessment must be an object"),
    ],
)
def test_projector_rejects_invalid_page_containers_and_scalars(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path / case)
    lineage = _lineage(state)

    if case == "page_object":
        lineage["claim_evidence_page"] = []
    elif case == "page_keys":
        cast(dict[str, Any], lineage["claim_evidence_page"]).pop("total")
    elif case == "items_list":
        lineage["claim_evidence"] = {}
    elif case == "offset_type":
        cast(dict[str, Any], lineage["claim_evidence_page"])["offset"] = "0"
    elif case == "offset_bool":
        cast(dict[str, Any], lineage["claim_evidence_page"])["offset"] = True
    elif case == "offset_negative":
        cast(dict[str, Any], lineage["claim_evidence_page"])["offset"] = -1
    elif case == "verification_keys":
        _verification(state).pop("total")
    elif case == "assessment_list":
        _verification(state)["assessments"] = {}
    else:
        cast(list[Any], _verification(state)["assessments"])[0] = "not-an-object"

    with pytest.raises(FrozenResearchStateProjectionError, match=message):
        _project(state, document_id, artifact_id)


def test_projector_enforces_verification_evidence_presence_by_relation_kind(
    tmp_path: Path,
) -> None:
    no_evidence_state, document_id, artifact_id = _valid_state(tmp_path / "no-evidence")
    assessment = _assessment(no_evidence_state)
    assessment["kind"] = "no_evidence"

    with pytest.raises(FrozenResearchStateProjectionError, match="must not identify Evidence"):
        _project(no_evidence_state, document_id, artifact_id)

    missing_state, document_id, artifact_id = _valid_state(tmp_path / "missing")
    _assessment(missing_state)["evidence"] = None

    with pytest.raises(FrozenResearchStateProjectionError, match="must identify exact Evidence"):
        _project(missing_state, document_id, artifact_id)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("context_object", "citation context must be an object"),
        ("context_keys", "citation context has unexpected or missing fields"),
        ("context_text", "citation context text must not be blank"),
        ("context_reverse", "citation context range is invalid"),
        ("context_length", "citation context range is invalid"),
        ("reasoning_blank", "verification reasoning_summary must not be blank"),
        ("kind", "verification kind is unsupported"),
    ],
)
def test_projector_rejects_invalid_verification_and_citation_semantics(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    state, document_id, artifact_id = _valid_state(tmp_path / case)
    assessment = _assessment(state)
    context = cast(dict[str, Any], assessment["citation_context"])

    if case == "context_object":
        assessment["citation_context"] = []
    elif case == "context_keys":
        context.pop("mention_id")
    elif case == "context_text":
        context["text"] = " "
    elif case == "context_reverse":
        context["char_start"] = 6
        context["char_end"] = 5
    elif case == "context_length":
        context["char_end"] = 4
    elif case == "reasoning_blank":
        assessment["reasoning_summary"] = " "
    else:
        assessment["kind"] = "unsupported"

    with pytest.raises(FrozenResearchStateProjectionError, match=message):
        _project(state, document_id, artifact_id)
