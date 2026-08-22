from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from tarkka.domain.citations import WorkRelation, WorkRelationKind
from tarkka.ports.citations import CitationRepository


class TraversalDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    BOTH = "both"


class TraversalLimit(StrEnum):
    DEPTH = "depth"
    WORKS = "works"
    RELATIONS = "relations"


@dataclass(frozen=True, slots=True)
class CitationTraversalPolicy:
    """Hard local bounds for traversing persisted Work relations."""

    max_depth: int = 1
    max_works: int = 100
    max_relations: int = 500
    direction: TraversalDirection = TraversalDirection.OUTBOUND
    relation_kinds: frozenset[WorkRelationKind] = frozenset({WorkRelationKind.CITES})

    def __post_init__(self) -> None:
        if self.max_depth < 0:
            raise ValueError("citation traversal max_depth must be non-negative")
        if self.max_works < 1:
            raise ValueError("citation traversal max_works must be at least one")
        if self.max_relations < 0:
            raise ValueError("citation traversal max_relations must be non-negative")
        if not isinstance(self.direction, TraversalDirection):
            raise ValueError("citation traversal direction must be a TraversalDirection")
        kinds = frozenset(self.relation_kinds)
        if not kinds:
            raise ValueError("citation traversal must allow at least one relation kind")
        if any(not isinstance(kind, WorkRelationKind) for kind in kinds):
            raise ValueError("citation traversal relation kinds must be WorkRelationKind values")
        object.__setattr__(self, "relation_kinds", kinds)


@dataclass(frozen=True, slots=True)
class CitationTraversalResult:
    root_work_id: UUID
    work_ids: tuple[UUID, ...]
    relations: tuple[WorkRelation, ...]
    max_depth_reached: int
    stopped_by: TraversalLimit | None = None


class CitationTraversalService:
    """Traverse persisted Work relations deterministically without a graph database."""

    def __init__(self, citations: CitationRepository) -> None:
        self._citations = citations

    def traverse(
        self,
        root_work_id: UUID,
        policy: CitationTraversalPolicy | None = None,
    ) -> CitationTraversalResult:
        selected = policy or CitationTraversalPolicy()
        visited: set[UUID] = {root_work_id}
        ordered_works: list[UUID] = [root_work_id]
        seen_relations: set[UUID] = set()
        ordered_relations: list[WorkRelation] = []
        frontier: tuple[UUID, ...] = (root_work_id,)
        reached_depth = 0

        if selected.max_depth == 0:
            stopped = (
                TraversalLimit.DEPTH
                if self._has_unseen_relation(frontier, seen_relations, selected)
                else None
            )
            return CitationTraversalResult(
                root_work_id=root_work_id,
                work_ids=(root_work_id,),
                relations=(),
                max_depth_reached=0,
                stopped_by=stopped,
            )

        for depth in range(selected.max_depth):
            next_frontier: set[UUID] = set()
            for work_id in sorted(frontier, key=str):
                remaining_relations = selected.max_relations - len(ordered_relations)
                if remaining_relations == 0:
                    if self._has_unseen_relation((work_id,), seen_relations, selected):
                        return _result(
                            root_work_id,
                            ordered_works,
                            ordered_relations,
                            reached_depth,
                            TraversalLimit.RELATIONS,
                        )
                    continue

                relations = self._relations_for(
                    work_id,
                    selected,
                    limit=remaining_relations,
                    exclude_ids=seen_relations,
                )
                for relation in relations:
                    neighbor = _neighbor(work_id, relation)
                    if neighbor is None:
                        continue
                    if neighbor not in visited and len(visited) >= selected.max_works:
                        return _result(
                            root_work_id,
                            ordered_works,
                            ordered_relations,
                            reached_depth,
                            TraversalLimit.WORKS,
                        )

                    seen_relations.add(relation.relation_id)
                    ordered_relations.append(relation)
                    if neighbor not in visited:
                        visited.add(neighbor)
                        ordered_works.append(neighbor)
                        next_frontier.add(neighbor)

                if len(ordered_relations) == selected.max_relations and self._has_unseen_relation(
                    (work_id,), seen_relations, selected
                ):
                    return _result(
                        root_work_id,
                        ordered_works,
                        ordered_relations,
                        reached_depth,
                        TraversalLimit.RELATIONS,
                    )

            reached_depth = depth + 1
            frontier = tuple(sorted(next_frontier, key=str))
            if not frontier:
                break
        else:
            if frontier and self._has_unseen_relation(frontier, seen_relations, selected):
                return _result(
                    root_work_id,
                    ordered_works,
                    ordered_relations,
                    reached_depth,
                    TraversalLimit.DEPTH,
                )

        return _result(
            root_work_id,
            ordered_works,
            ordered_relations,
            reached_depth,
            None,
        )

    def _relations_for(
        self,
        work_id: UUID,
        policy: CitationTraversalPolicy,
        *,
        limit: int,
        exclude_ids: set[UUID],
    ) -> tuple[WorkRelation, ...]:
        if limit <= 0:
            return ()
        excluded = frozenset(exclude_ids)
        relations: dict[UUID, WorkRelation] = {}
        if policy.direction in {TraversalDirection.OUTBOUND, TraversalDirection.BOTH}:
            for relation in self._citations.list_relations_from(
                work_id,
                kinds=policy.relation_kinds,
                exclude_ids=excluded,
                limit=limit,
            ):
                relations[relation.relation_id] = relation
        if policy.direction in {TraversalDirection.INBOUND, TraversalDirection.BOTH}:
            for relation in self._citations.list_relations_to(
                work_id,
                kinds=policy.relation_kinds,
                exclude_ids=excluded,
                limit=limit,
            ):
                relations[relation.relation_id] = relation
        return tuple(sorted(relations.values(), key=_relation_key)[:limit])

    def _has_unseen_relation(
        self,
        frontier: tuple[UUID, ...],
        seen_relations: set[UUID],
        policy: CitationTraversalPolicy,
    ) -> bool:
        for work_id in frontier:
            if self._relations_for(
                work_id,
                policy,
                limit=1,
                exclude_ids=seen_relations,
            ):
                return True
        return False


def _result(
    root_work_id: UUID,
    ordered_works: list[UUID],
    ordered_relations: list[WorkRelation],
    max_depth_reached: int,
    stopped_by: TraversalLimit | None,
) -> CitationTraversalResult:
    return CitationTraversalResult(
        root_work_id=root_work_id,
        work_ids=tuple(ordered_works),
        relations=tuple(ordered_relations),
        max_depth_reached=max_depth_reached,
        stopped_by=stopped_by,
    )


def _neighbor(work_id: UUID, relation: WorkRelation) -> UUID | None:
    if relation.subject_work_id == work_id:
        return relation.object_work_id
    if relation.object_work_id == work_id:
        return relation.subject_work_id
    return None


def _relation_key(relation: WorkRelation) -> tuple[str, str, str, str]:
    return (
        relation.kind.value,
        str(relation.subject_work_id),
        str(relation.object_work_id),
        str(relation.relation_id),
    )
