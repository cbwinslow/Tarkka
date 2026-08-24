from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.ports.works import WorkRepository


class WorkRepositoryContract:
    """Reusable atomicity and identity assertions for canonical Work repositories."""

    @staticmethod
    def assert_missing_reads_are_empty(
        repository: WorkRepository,
        missing_work_id: UUID,
    ) -> None:
        assert repository.get_work(missing_work_id) is None
        assert repository.list_identifiers(missing_work_id) == ()
        assert repository.list_source_records(missing_work_id) == ()

    @staticmethod
    def assert_graph_round_trip(
        repository: WorkRepository,
        work: Work,
        identifier: WorkIdentifier,
        source_record: WorkSourceRecord,
    ) -> None:
        assert identifier.work_id == work.work_id
        assert source_record.work_id == work.work_id

        with repository.transaction():
            repository.save_work(work)
            repository.save_identifier(identifier)
            repository.save_source_record(source_record)

        assert repository.get_work(work.work_id) == work
        assert repository.find_work_by_identifier(identifier.scheme, identifier.value) == work
        assert repository.list_identifiers(work.work_id) == (identifier,)
        assert repository.list_source_records(work.work_id) == (source_record,)

    @staticmethod
    def assert_multi_entry_listing_is_deterministic(
        repository: WorkRepository,
        work: Work,
        identifiers: tuple[WorkIdentifier, ...],
        source_records: tuple[WorkSourceRecord, ...],
    ) -> None:
        assert all(identifier.work_id == work.work_id for identifier in identifiers)
        assert all(source_record.work_id == work.work_id for source_record in source_records)

        with repository.transaction():
            repository.save_work(work)
            for identifier in reversed(identifiers):
                repository.save_identifier(identifier)
            for source_record in reversed(source_records):
                repository.save_source_record(source_record)

        assert repository.list_identifiers(work.work_id) == tuple(
            sorted(identifiers, key=lambda item: (item.scheme, item.value))
        )
        assert repository.list_source_records(work.work_id) == tuple(
            sorted(source_records, key=lambda item: (item.provider, item.provider_id))
        )

    @staticmethod
    def assert_work_can_evolve_without_losing_identity(
        repository: WorkRepository,
        original: Work,
        evolved: Work,
        identifier: WorkIdentifier,
        source_record: WorkSourceRecord,
    ) -> None:
        assert original.work_id == evolved.work_id
        assert original != evolved
        assert identifier.work_id == original.work_id
        assert source_record.work_id == original.work_id

        with repository.transaction():
            repository.save_work(original)
            repository.save_identifier(identifier)
            repository.save_source_record(source_record)

        with repository.transaction():
            repository.save_work(evolved)

        assert repository.get_work(original.work_id) == evolved
        assert repository.find_work_by_identifier(identifier.scheme, identifier.value) == evolved
        assert repository.list_identifiers(original.work_id) == (identifier,)
        assert repository.list_source_records(original.work_id) == (source_record,)

    @staticmethod
    def assert_identifier_conflict_rolls_back_transaction(
        repository: WorkRepository,
        first_work: Work,
        second_work: Work,
        first_identifier: WorkIdentifier,
        conflicting_identifier: WorkIdentifier,
        conflict_error: type[Exception],
    ) -> None:
        assert first_work.work_id != second_work.work_id
        assert first_identifier.work_id == first_work.work_id
        assert conflicting_identifier.work_id == second_work.work_id
        assert first_identifier.scheme == conflicting_identifier.scheme
        assert first_identifier.value == conflicting_identifier.value

        with repository.transaction():
            repository.save_work(first_work)
            repository.save_identifier(first_identifier)

        WorkRepositoryContract._expect_conflict(
            conflict_error,
            lambda: WorkRepositoryContract._save_conflicting_identifier_in_transaction(
                repository,
                second_work,
                conflicting_identifier,
            ),
        )
        assert repository.get_work(second_work.work_id) is None
        assert repository.find_work_by_identifier(
            first_identifier.scheme,
            first_identifier.value,
        ) == first_work
        assert repository.list_identifiers(first_work.work_id) == (first_identifier,)
        assert repository.list_identifiers(second_work.work_id) == ()

    @staticmethod
    def assert_source_record_conflict_rolls_back_transaction(
        repository: WorkRepository,
        first_work: Work,
        second_work: Work,
        first_record: WorkSourceRecord,
        conflicting_record: WorkSourceRecord,
        conflict_error: type[Exception],
    ) -> None:
        assert first_work.work_id != second_work.work_id
        assert first_record.work_id == first_work.work_id
        assert conflicting_record.work_id == second_work.work_id
        assert first_record.provider == conflicting_record.provider
        assert first_record.provider_id == conflicting_record.provider_id

        with repository.transaction():
            repository.save_work(first_work)
            repository.save_source_record(first_record)

        WorkRepositoryContract._expect_conflict(
            conflict_error,
            lambda: WorkRepositoryContract._save_conflicting_source_record_in_transaction(
                repository,
                second_work,
                conflicting_record,
            ),
        )
        assert repository.get_work(second_work.work_id) is None
        assert repository.list_source_records(first_work.work_id) == (first_record,)
        assert repository.list_source_records(second_work.work_id) == ()

    @staticmethod
    def assert_transaction_rolls_back(
        repository: WorkRepository,
        work: Work,
        identifier: WorkIdentifier,
        source_record: WorkSourceRecord,
    ) -> None:
        assert identifier.work_id == work.work_id
        assert source_record.work_id == work.work_id

        try:
            with repository.transaction():
                repository.save_work(work)
                repository.save_identifier(identifier)
                repository.save_source_record(source_record)
                raise RuntimeError("contract rollback sentinel")
        except RuntimeError as exc:
            if str(exc) != "contract rollback sentinel":
                raise
        else:
            raise AssertionError("transaction sentinel must escape the transaction")

        assert repository.get_work(work.work_id) is None
        assert repository.find_work_by_identifier(identifier.scheme, identifier.value) is None
        assert repository.list_identifiers(work.work_id) == ()
        assert repository.list_source_records(work.work_id) == ()

    @staticmethod
    def _save_conflicting_identifier_in_transaction(
        repository: WorkRepository,
        work: Work,
        identifier: WorkIdentifier,
    ) -> None:
        with repository.transaction():
            repository.save_work(work)
            repository.save_identifier(identifier)

    @staticmethod
    def _save_conflicting_source_record_in_transaction(
        repository: WorkRepository,
        work: Work,
        source_record: WorkSourceRecord,
    ) -> None:
        with repository.transaction():
            repository.save_work(work)
            repository.save_source_record(source_record)

    @staticmethod
    def _expect_conflict(
        conflict_error: type[Exception],
        operation: Callable[[], object],
    ) -> None:
        try:
            operation()
        except conflict_error:
            return
        except Exception as exc:
            raise AssertionError(
                f"expected {conflict_error.__name__}, got {type(exc).__name__}"
            ) from exc
        raise AssertionError(f"expected {conflict_error.__name__} to be raised")
