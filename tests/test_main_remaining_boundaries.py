from __future__ import annotations

import argparse
import json
import runpy
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tarkka.domain.extraction import Claim, ExtractionProvenance, Hypothesis
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.interfaces import main as interface


def _args(**values: object) -> argparse.Namespace:
    return argparse.Namespace(**values)


def _claim(*, evidence_id: UUID | None = None) -> Claim:
    evidence_id = evidence_id or uuid4()
    return Claim(
        extraction_id=uuid4(),
        document_id=uuid4(),
        evidence_ids=(evidence_id,),
        provenance=ExtractionProvenance(run_id=uuid4(), confidence=0.8),
        text="Boundary claim",
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        extraction_id=uuid4(),
        document_id=uuid4(),
        evidence_ids=(uuid4(),),
        provenance=ExtractionProvenance(run_id=uuid4(), confidence=0.7),
        text="Boundary hypothesis",
    )


@pytest.mark.parametrize(
    ("offset", "limit", "message"),
    [
        (-1, 10, "non-negative"),
        (interface._MAX_CITATION_OFFSET + 1, 10, "offset must not exceed"),
        (0, interface._MAX_CITATION_PAGE_SIZE + 1, "limit must not exceed"),
    ],
)
def test_citations_list_rejects_each_pagination_boundary(
    offset: int,
    limit: int,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        interface._cmd_citations_list(
            _args(document_id=uuid4(), offset=offset, limit=limit)
        )
        == 2
    )
    assert message in capsys.readouterr().err


def test_citations_list_translates_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Repository:
        def count_references(self, document_id: UUID) -> int:
            raise RuntimeError(f"citation catalog unavailable: {document_id}")

    monkeypatch.setattr(interface, "_document_exists_for_inspection", lambda _: True)
    monkeypatch.setattr(interface, "_existing_citation_repository", lambda: _Repository())

    assert interface._cmd_citations_list(_args(document_id=uuid4(), offset=0, limit=10)) == 2
    assert "citation catalog unavailable" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("offset", "limit", "message"),
    [
        (-1, 10, "non-negative"),
        (0, interface._MAX_CITATION_PAGE_SIZE + 1, "pagination exceeds"),
    ],
)
def test_citations_show_rejects_pagination_boundaries(
    offset: int,
    limit: int,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        interface._cmd_citations_show(
            _args(
                document_id=uuid4(),
                reference_id=uuid4(),
                offset=offset,
                limit=limit,
            )
        )
        == 2
    )
    assert message in capsys.readouterr().err


def test_citations_show_handles_missing_document_catalog_reference_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = uuid4()
    reference_id = uuid4()
    args = _args(document_id=document_id, reference_id=reference_id, offset=0, limit=10)

    monkeypatch.setattr(interface, "_document_exists_for_inspection", lambda _: False)
    assert interface._cmd_citations_show(args) == 2
    assert "document not found" in capsys.readouterr().err

    monkeypatch.setattr(interface, "_document_exists_for_inspection", lambda _: True)
    monkeypatch.setattr(interface, "_existing_citation_repository", lambda: None)
    assert interface._cmd_citations_show(args) == 2
    assert "reference not found" in capsys.readouterr().err

    class _EmptyRepository:
        def list_references(self, requested: UUID) -> tuple[()]:
            assert requested == document_id
            return ()

    monkeypatch.setattr(interface, "_existing_citation_repository", lambda: _EmptyRepository())
    assert interface._cmd_citations_show(args) == 2
    assert "reference not found" in capsys.readouterr().err

    class _BrokenRepository:
        def list_references(self, requested: UUID) -> tuple[()]:
            raise RuntimeError(f"citation read failed: {requested}")

    monkeypatch.setattr(interface, "_existing_citation_repository", lambda: _BrokenRepository())
    assert interface._cmd_citations_show(args) == 2
    assert "citation read failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 10), (0, interface._MAX_CITATION_PAGE_SIZE + 1)],
)
def test_citations_resolve_rejects_pagination_boundaries(
    offset: int,
    limit: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        interface._cmd_citations_resolve(
            _args(
                document_id=uuid4(),
                citing_work_id=None,
                offset=offset,
                limit=limit,
            )
        )
        == 2
    )
    assert "citation" in capsys.readouterr().err


def test_citations_traverse_rejects_lower_bounds_and_translates_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work_id = uuid4()
    bad = _args(
        work_id=work_id,
        max_depth=-1,
        max_works=1,
        max_relations=0,
        direction="outgoing",
        kinds=None,
    )
    assert interface._cmd_citations_traverse(bad) == 2
    assert "non-negative" in capsys.readouterr().err

    class _BrokenWorks:
        def get_work(self, requested: UUID) -> object:
            raise RuntimeError(f"work catalog unavailable: {requested}")

    monkeypatch.setattr(interface, "_work_repository", lambda: _BrokenWorks())
    good = _args(
        work_id=work_id,
        max_depth=1,
        max_works=2,
        max_relations=3,
        direction="outgoing",
        kinds=None,
    )
    assert interface._cmd_citations_traverse(good) == 2
    assert "work catalog unavailable" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 10), (interface.MAX_RESOURCE_LINK_OFFSET + 1, 10)],
)
def test_resources_list_rejects_pagination_boundaries(
    offset: int,
    limit: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert interface._cmd_resources_list(_args(document_id=uuid4(), offset=offset, limit=limit)) == 2
    assert "resource" in capsys.readouterr().err


def test_resources_list_and_show_translate_missing_state_and_service_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = uuid4()

    monkeypatch.setattr(interface, "_document_exists_for_inspection", lambda _: False)
    assert interface._cmd_resources_list(_args(document_id=document_id, offset=0, limit=10)) == 2
    assert "document not found" in capsys.readouterr().err
    assert interface._cmd_resources_show(
        _args(document_id=document_id, resource_link_id=uuid4())
    ) == 2
    assert "document not found" in capsys.readouterr().err

    class _BrokenService:
        def resource_links(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("resource listing unavailable")

        def resource_link(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("resource detail unavailable")

    monkeypatch.setattr(interface, "_document_exists_for_inspection", lambda _: True)
    monkeypatch.setattr(interface, "_research_package_service", lambda: _BrokenService())
    assert interface._cmd_resources_list(_args(document_id=document_id, offset=0, limit=10)) == 2
    assert "resource listing unavailable" in capsys.readouterr().err
    assert interface._cmd_resources_show(
        _args(document_id=document_id, resource_link_id=uuid4())
    ) == 2
    assert "resource detail unavailable" in capsys.readouterr().err


def test_verify_record_translates_service_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _BrokenService:
        def record(self, request: object) -> object:
            raise ValueError(f"invalid verification request: {request!r}")

    monkeypatch.setattr(interface, "_verification_service", lambda: _BrokenService())
    args = _args(
        claim_id=uuid4(),
        evidence_id=uuid4(),
        citation_context_id=None,
        kind="supports",
        verifier="reviewer",
        verifier_version="1",
        confidence=0.5,
        review_state="unreviewed",
        reasoning_summary=None,
    )
    assert interface._cmd_verify_record(args) == 2
    assert "invalid verification request" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 10), (0, interface._MAX_VERIFICATION_PAGE_SIZE + 1)],
)
def test_verify_list_rejects_pagination_boundaries(
    offset: int,
    limit: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert interface._cmd_verify_list(_args(claim_id=uuid4(), offset=offset, limit=limit)) == 2
    assert "verification" in capsys.readouterr().err


def test_verify_candidates_and_list_translate_repository_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _BrokenService:
        def citation_candidates(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("candidate lookup failed")

    monkeypatch.setattr(interface, "_verification_service", lambda: _BrokenService())
    assert interface._cmd_verify_candidates(_args(claim_id=uuid4(), offset=0, limit=10)) == 2
    assert "candidate lookup failed" in capsys.readouterr().err

    class _BrokenRepository:
        def list_relations(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("verification catalog failed")

    monkeypatch.setattr(interface, "_existing_verification_repository", lambda: _BrokenRepository())
    assert interface._cmd_verify_list(_args(claim_id=uuid4(), offset=0, limit=10)) == 2
    assert "verification catalog failed" in capsys.readouterr().err


def test_verify_show_handles_missing_relation_claim_evidence_and_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    relation_id = uuid4()

    monkeypatch.setattr(interface, "_existing_verification_repository", lambda: None)
    assert interface._cmd_verify_show(_args(relation_id=relation_id)) == 2
    assert "verification relation not found" in capsys.readouterr().err

    claim_id = uuid4()
    relation_stub = SimpleNamespace(claim_id=claim_id)

    class _RelationRepository:
        def __init__(self, relation: object) -> None:
            self.relation = relation

        def get_relation(self, requested: UUID) -> object:
            assert requested == relation_id
            return self.relation

    class _Source:
        extraction: object = _hypothesis()
        evidence: object | None = None

        def get_extraction(self, requested: UUID) -> object:
            return self.extraction

        def get_evidence(self, requested: UUID) -> object | None:
            return self.evidence

    source = _Source()
    relation_repository = _RelationRepository(relation_stub)
    monkeypatch.setattr(interface, "_existing_verification_repository", lambda: relation_repository)
    monkeypatch.setattr(interface, "_extraction_repository", lambda: source)
    assert interface._cmd_verify_show(_args(relation_id=relation_id)) == 2
    assert "claim not found" in capsys.readouterr().err

    claim = _claim()
    source.extraction = claim
    evidence_relation = EvidenceRelation(
        relation_id=relation_id,
        claim_id=claim.extraction_id,
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="reviewer",
        verifier_version="1",
        confidence=0.5,
        evidence_id=claim.evidence_ids[0],
    )
    relation_repository.relation = evidence_relation
    assert interface._cmd_verify_show(_args(relation_id=relation_id)) == 2
    assert "evidence not found" in capsys.readouterr().err

    context_id = uuid4()
    context_relation = EvidenceRelation(
        relation_id=relation_id,
        claim_id=claim.extraction_id,
        kind=EvidenceRelationKind.NO_EVIDENCE,
        verifier_name="reviewer",
        verifier_version="1",
        confidence=0.5,
        citation_context_id=context_id,
    )
    relation_repository.relation = context_relation
    monkeypatch.setattr(interface, "_existing_citation_repository", lambda: None)
    assert interface._cmd_verify_show(_args(relation_id=relation_id)) == 2
    assert "citation context not found" in capsys.readouterr().err


def test_main_dispatches_bibliography_legacy_and_real_module_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(interface, "bibliography_main", lambda args, home: 17)
    monkeypatch.setattr(interface, "legacy_main", lambda args: 19)

    assert interface.main(["bibliography", "list"]) == 17
    assert interface.main(["legacy-command"]) == 19

    monkeypatch.setattr(sys, "argv", ["main.py", "capabilities", "list"])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(interface.__file__, run_name="__main__")
    assert raised.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"]
