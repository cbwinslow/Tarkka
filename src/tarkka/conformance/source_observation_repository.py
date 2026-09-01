from __future__ import annotations

from tarkka.conformance._assertions import _expect_exception
from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation
from tarkka.ports.source_observations import SourceObservationRepository


class SourceObservationRepositoryContract:
    """Reusable provenance-persistence assertions for source observation repositories."""

    @staticmethod
    def assert_missing_reads_are_empty(
        repository: SourceObservationRepository,
        observation: SourceObservation,
    ) -> None:
        assert repository.get_observation(observation.observation_id) is None
        assert repository.list_resource_links(observation.observation_id) == ()

    @staticmethod
    def assert_first_seen_is_idempotent(
        repository: SourceObservationRepository,
        first: SourceObservation,
        logically_same_later: SourceObservation,
    ) -> None:
        repository.save_observation(first)
        repository.save_observation(logically_same_later)

        assert repository.get_observation(first.observation_id) == first

    @staticmethod
    def assert_link_write_is_idempotent(
        repository: SourceObservationRepository,
        observation: SourceObservation,
        link: ResourceLinkObservation,
    ) -> None:
        repository.save_observation(observation)
        repository.save_resource_link(link)
        repository.save_resource_link(link)

        assert repository.list_resource_links(observation.observation_id) == (link,)

    @staticmethod
    def assert_conflicting_observation_fails(
        repository: SourceObservationRepository,
        first: SourceObservation,
        conflicting: SourceObservation,
        conflict_error: type[Exception],
    ) -> None:
        repository.save_observation(first)
        _expect_exception(
            conflict_error,
            lambda: repository.save_observation(conflicting),
        )

        assert repository.get_observation(first.observation_id) == first

    @staticmethod
    def assert_conflicting_link_fails(
        repository: SourceObservationRepository,
        observation: SourceObservation,
        first: ResourceLinkObservation,
        conflicting: ResourceLinkObservation,
        conflict_error: type[Exception],
    ) -> None:
        repository.save_observation(observation)
        repository.save_resource_link(first)
        _expect_exception(
            conflict_error,
            lambda: repository.save_resource_link(conflicting),
        )

        assert repository.list_resource_links(observation.observation_id) == (first,)
