from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from tarkka.domain.models import (
    Acquisition,
    Artifact,
    Document,
    Passage,
    Section,
    Work,
    Workspace,
)
from tarkka.domain.policy_requests import (
    begin_policy_request,
    record_policy_elapsed,
    record_policy_response_bytes,
)
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.rights_access import OperatorOverride, ResourceUse, RightsAccessDecision
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.traversal import TraversalCheckpoint

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _passage(document_id: UUID, section_id: UUID, *, text: str = "text") -> Passage:
    return Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text=text,
        char_start=0,
        char_end=len(text),
    )


def _rights(**overrides: Any) -> RightsAccessDecision:
    values: dict[str, Any] = {
        "target_uri": "https://example.org/article",
        "retrieval_allowed": True,
        "storage_allowed": True,
        "analysis_allowed": True,
        "redistribution_allowed": False,
        "source_name": "policy",
    }
    values.update(overrides)
    return RightsAccessDecision(**values)


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(
        allowed_domains=frozenset({"example.org"}),
        min_request_interval_seconds=0.0,
    )


def test_workspace_rejects_blank_name_and_copies_settings_immutably() -> None:
    with pytest.raises(ValueError, match="workspace name must not be blank"):
        Workspace(workspace_id=uuid4(), name="  ")

    source = {"mode": "strict"}
    workspace = Workspace(workspace_id=uuid4(), name="research", settings=source)
    source["mode"] = "changed"

    assert workspace.settings == {"mode": "strict"}
    with pytest.raises(TypeError):
        cast(Any, workspace.settings)["mode"] = "mutated"


def test_work_validates_title_and_year_and_copies_external_ids() -> None:
    with pytest.raises(ValueError, match="work title must not be blank"):
        Work(work_id=uuid4(), title=" ")
    with pytest.raises(ValueError, match="publication_year must be non-negative"):
        Work(work_id=uuid4(), title="Paper", publication_year=-1)

    external_ids = {"doi": "10.1000/example"}
    work = Work(work_id=uuid4(), title="Paper", publication_year=0, external_ids=external_ids)
    external_ids["doi"] = "changed"

    assert work.external_ids == {"doi": "10.1000/example"}
    with pytest.raises(TypeError):
        cast(Any, work.external_ids)["doi"] = "mutated"


@pytest.mark.parametrize(
    ("sha256", "size_bytes", "media_type", "message"),
    [
        ("a" * 63, 0, "application/pdf", "sha256"),
        ("g" * 64, 0, "application/pdf", "sha256"),
        ("a" * 64, -1, "application/pdf", "size_bytes"),
        ("a" * 64, 0, "", "media_type"),
    ],
)
def test_artifact_rejects_invalid_identity_and_metadata(
    sha256: str,
    size_bytes: int,
    media_type: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Artifact(
            artifact_id=uuid4(),
            sha256=sha256,
            size_bytes=size_bytes,
            media_type=media_type,
            storage_key=PurePosixPath("artifact.bin"),
        )


def test_acquisition_requires_source_uri_and_copies_metadata() -> None:
    with pytest.raises(ValueError, match="source_uri must not be blank"):
        Acquisition(acquisition_id=uuid4(), artifact_id=uuid4(), source_uri=" ")

    metadata = {"etag": "abc"}
    acquisition = Acquisition(
        acquisition_id=uuid4(),
        artifact_id=uuid4(),
        source_uri="https://example.org/file",
        metadata=metadata,
    )
    metadata["etag"] = "changed"

    assert acquisition.metadata == {"etag": "abc"}
    with pytest.raises(TypeError):
        cast(Any, acquisition.metadata)["etag"] = "mutated"


@pytest.mark.parametrize(
    ("ordinal", "char_start", "char_end", "text", "message"),
    [
        (-1, 0, 1, "x", "ordinal"),
        (0, -1, 0, "x", "character range"),
        (0, 2, 1, "", "character range"),
        (0, 0, 2, "x", "match text length"),
    ],
)
def test_passage_rejects_invalid_ranges(
    ordinal: int,
    char_start: int,
    char_end: int,
    text: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Passage(
            passage_id=uuid4(),
            document_id=uuid4(),
            section_id=uuid4(),
            ordinal=ordinal,
            text=text,
            char_start=char_start,
            char_end=char_end,
        )


def test_empty_passage_range_is_valid_when_text_is_empty() -> None:
    passage = Passage(
        passage_id=uuid4(),
        document_id=uuid4(),
        section_id=uuid4(),
        ordinal=0,
        text="",
        char_start=5,
        char_end=5,
    )
    assert passage.char_start == passage.char_end == 5


def test_section_validates_ordinal_level_and_passage_ownership() -> None:
    document_id = uuid4()
    section_id = uuid4()

    with pytest.raises(ValueError, match="section ordinal"):
        Section(section_id=section_id, document_id=document_id, ordinal=-1, title="Intro")
    with pytest.raises(ValueError, match="section level"):
        Section(
            section_id=section_id,
            document_id=document_id,
            ordinal=0,
            title="Intro",
            level=0,
        )
    with pytest.raises(ValueError, match="does not belong"):
        Section(
            section_id=section_id,
            document_id=document_id,
            ordinal=0,
            title="Intro",
            passages=(_passage(uuid4(), section_id),),
        )
    with pytest.raises(ValueError, match="does not belong"):
        Section(
            section_id=section_id,
            document_id=document_id,
            ordinal=0,
            title="Intro",
            passages=(_passage(document_id, uuid4()),),
        )


def test_document_requires_parser_identity_and_child_ownership() -> None:
    document_id = uuid4()
    artifact_id = uuid4()

    for parser_name, parser_version in (("", "1"), ("parser", " ")):
        with pytest.raises(ValueError, match="parser name/version"):
            Document(
                document_id=document_id,
                artifact_id=artifact_id,
                title="Doc",
                parser_name=parser_name,
                parser_version=parser_version,
                sections=(),
            )

    wrong_document_id = uuid4()
    wrong_section = Section(
        section_id=uuid4(),
        document_id=wrong_document_id,
        ordinal=0,
        title="Intro",
    )
    with pytest.raises(ValueError, match="section does not belong"):
        Document(document_id, artifact_id, "Doc", "parser", "1", (wrong_section,))

    with pytest.raises(ValueError, match="figure does not belong"):
        Document(
            document_id,
            artifact_id,
            "Doc",
            "parser",
            "1",
            (),
            figures=(Figure(uuid4(), wrong_document_id, 0),),
        )
    with pytest.raises(ValueError, match="table does not belong"):
        Document(
            document_id,
            artifact_id,
            "Doc",
            "parser",
            "1",
            (),
            tables=(Table(uuid4(), wrong_document_id, 0),),
        )
    with pytest.raises(ValueError, match="equation does not belong"):
        Document(
            document_id,
            artifact_id,
            "Doc",
            "parser",
            "1",
            (),
            equations=(Equation(uuid4(), wrong_document_id, 0),),
        )


@pytest.mark.parametrize("kind", ["figure", "table", "equation"])
@pytest.mark.parametrize("duplicate", ["id", "ordinal"])
def test_document_rejects_duplicate_source_artifact_identity(
    kind: str,
    duplicate: str,
) -> None:
    document_id = uuid4()
    artifact_id = uuid4()
    first_id = uuid4()
    second_id = first_id if duplicate == "id" else uuid4()
    second_ordinal = 1 if duplicate == "id" else 0

    kwargs: dict[str, object] = {}
    if kind == "figure":
        kwargs["figures"] = (
            Figure(first_id, document_id, 0),
            Figure(second_id, document_id, second_ordinal),
        )
    elif kind == "table":
        kwargs["tables"] = (
            Table(first_id, document_id, 0),
            Table(second_id, document_id, second_ordinal),
        )
    else:
        kwargs["equations"] = (
            Equation(first_id, document_id, 0),
            Equation(second_id, document_id, second_ordinal),
        )

    with pytest.raises(ValueError, match=rf"{kind} .* must be unique"):
        Document(
            document_id=document_id,
            artifact_id=artifact_id,
            title="Doc",
            parser_name="parser",
            parser_version="1",
            sections=(),
            **cast(Any, kwargs),
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "retrieval_allowed",
        "storage_allowed",
        "analysis_allowed",
        "redistribution_allowed",
        "requires_authentication",
        "paywalled",
    ],
)
def test_rights_access_requires_actual_booleans(field_name: str) -> None:
    with pytest.raises(ValueError, match=rf"rights {field_name} must be boolean"):
        _rights(**{field_name: 1})


@pytest.mark.parametrize("source_name", [" ", None, 1])
def test_rights_access_requires_non_blank_source_name(source_name: object) -> None:
    with pytest.raises(ValueError, match="source_name must be non-blank"):
        _rights(source_name=source_name)


@pytest.mark.parametrize("policy_reference", [" ", 1])
def test_rights_access_validates_optional_policy_reference(policy_reference: object) -> None:
    with pytest.raises(ValueError, match="policy_reference"):
        _rights(policy_reference=policy_reference)


@pytest.mark.parametrize("rationale", [" ", 1])
def test_rights_access_validates_optional_rationale(rationale: object) -> None:
    with pytest.raises(ValueError, match="rationale"):
        _rights(rationale=rationale)


def test_rights_access_normalizes_auditable_text_fields() -> None:
    rights = _rights(
        source_name="  policy  ",
        policy_reference="  policy-v1  ",
        rationale="  reviewed  ",
        operator_override=OperatorOverride.ALLOW,
    )
    assert rights.source_name == "policy"
    assert rights.policy_reference == "policy-v1"
    assert rights.rationale == "reviewed"


def test_rights_access_requires_enum_values() -> None:
    with pytest.raises(ValueError, match="OperatorOverride"):
        _rights(operator_override="allow")

    rights = _rights()
    with pytest.raises(ValueError, match="ResourceUse"):
        rights.allows(cast(ResourceUse, "retrieve"))


def test_policy_request_helpers_validate_boundary_types() -> None:
    checkpoint = TraversalCheckpoint(uuid4())
    policy = _policy()

    with pytest.raises(ValueError, match="checkpoint must be"):
        begin_policy_request(cast(TraversalCheckpoint, object()), policy, depth=0)
    with pytest.raises(ValueError, match="policy must be"):
        begin_policy_request(
            checkpoint,
            cast(ResourceAcquisitionPolicy, object()),
            depth=0,
        )
    with pytest.raises(ValueError, match="checkpoint must be"):
        record_policy_response_bytes(
            cast(TraversalCheckpoint, object()),
            bytes_acquired=0,
        )
    with pytest.raises(ValueError, match="checkpoint must be"):
        record_policy_elapsed(
            cast(TraversalCheckpoint, object()),
            elapsed_seconds=0.0,
        )


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_policy_response_bytes_requires_non_negative_integer(value: object) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        record_policy_response_bytes(
            TraversalCheckpoint(uuid4()),
            bytes_acquired=cast(int, value),
        )


@pytest.mark.parametrize("value", [True, "1", float("inf"), float("nan"), -1.0])
def test_policy_elapsed_requires_finite_numeric_value(value: object) -> None:
    message = "numeric" if isinstance(value, (bool, str)) else "finite and monotonic"
    with pytest.raises(ValueError, match=message):
        record_policy_elapsed(
            TraversalCheckpoint(uuid4()),
            elapsed_seconds=cast(float, value),
        )


def test_policy_elapsed_accepts_integer_and_preserves_other_budget_counters() -> None:
    checkpoint = begin_policy_request(
        TraversalCheckpoint(uuid4()),
        _policy(),
        depth=0,
        expected_bytes=0,
    )
    checkpoint = record_policy_response_bytes(checkpoint, bytes_acquired=7)

    updated = record_policy_elapsed(checkpoint, elapsed_seconds=2)

    assert updated.budget.requests_used == 1
    assert updated.budget.bytes_used == 7
    assert updated.budget.elapsed_seconds == 2.0
