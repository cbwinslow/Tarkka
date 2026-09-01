from __future__ import annotations

from uuid import UUID

from tarkka.conformance._assertions import _expect_exception
from tarkka.domain.extraction import ExtractionBatch, ResearchObjectKind
from tarkka.ports.extraction import ExtractionRepository


class ExtractionRepositoryContract:
    """Reusable atomicity and provenance assertions for extraction repositories."""

    @staticmethod
    def assert_missing_reads_are_empty(
        repository: ExtractionRepository,
        batch: ExtractionBatch,
        missing_run_id: UUID,
    ) -> None:
        assert missing_run_id != batch.run.run_id
        assert repository.list_evidence(batch.document_id) == ()
        assert repository.list_extractions(batch.document_id) == ()

        repository.save_batch(batch)
        assert repository.list_evidence(
            batch.document_id,
            run_id=missing_run_id,
        ) == ()
        assert repository.list_extractions(
            batch.document_id,
            run_id=missing_run_id,
        ) == ()

    @staticmethod
    def assert_batch_round_trip(
        repository: ExtractionRepository,
        batch: ExtractionBatch,
    ) -> None:
        repository.save_batch(batch)

        assert repository.list_evidence(
            batch.document_id,
            run_id=batch.run.run_id,
        ) == batch.evidence
        assert repository.list_extractions(
            batch.document_id,
            run_id=batch.run.run_id,
        ) == batch.extractions

    @staticmethod
    def assert_repeated_save_is_idempotent(
        repository: ExtractionRepository,
        batch: ExtractionBatch,
    ) -> None:
        repository.save_batch(batch)
        repository.save_batch(batch)

        assert repository.list_evidence(
            batch.document_id,
            run_id=batch.run.run_id,
        ) == batch.evidence
        assert repository.list_extractions(
            batch.document_id,
            run_id=batch.run.run_id,
        ) == batch.extractions

    @staticmethod
    def assert_kind_filter_preserves_evidence_links(
        repository: ExtractionRepository,
        batch: ExtractionBatch,
    ) -> None:
        """Require a fixture with at least two extraction kinds and verify exclusive filtering."""
        repository.save_batch(batch)
        evidence_ids = {item.evidence_id for item in batch.evidence}
        present_kinds = {item.kind for item in batch.extractions}
        if len(present_kinds) < 2:
            raise AssertionError("contract fixture must contain at least two extraction kinds")

        for kind in present_kinds:
            expected = tuple(item for item in batch.extractions if item.kind is kind)
            filtered = repository.list_extractions(
                batch.document_id,
                run_id=batch.run.run_id,
                kind=kind,
            )
            assert set(filtered) == set(expected)
            assert len(filtered) == len(expected)
            for extraction in filtered:
                assert extraction.evidence_ids
                assert set(extraction.evidence_ids).issubset(evidence_ids)

        for kind in set(ResearchObjectKind) - present_kinds:
            assert repository.list_extractions(
                batch.document_id,
                run_id=batch.run.run_id,
                kind=kind,
            ) == ()

    @staticmethod
    def assert_conflicting_batch_fails_closed(
        repository: ExtractionRepository,
        original: ExtractionBatch,
        conflicting: ExtractionBatch,
        conflict_error: type[Exception],
    ) -> None:
        assert original.document_id == conflicting.document_id
        assert original.run.run_id == conflicting.run.run_id
        assert original != conflicting

        repository.save_batch(original)
        _expect_exception(
            conflict_error,
            lambda: repository.save_batch(conflicting),
        )

        assert repository.list_evidence(
            original.document_id,
            run_id=original.run.run_id,
        ) == original.evidence
        assert repository.list_extractions(
            original.document_id,
            run_id=original.run.run_id,
        ) == original.extractions
