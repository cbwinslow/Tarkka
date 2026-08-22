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

        for depth in range(selected.max_depth):
            next_frontier: set[UUID] = set()
            for work_id in sorted(frontier, key=str):
                for relation in self._relations_for(work_id, selected):
                    if relation.relation_id in seen_relations:
                        continue
                    neighbor = _neighbor(work_id, relation)
                    if neighbor is None:
                        continue
                    if len(ordered_relations) >= selected.max_relations:
                        return CitationTraversalResult(
                            root_work_id=root_work_id,
                            work_ids=tuple(ordered_works),
                            relations=tuple(ordered_relations),
                            max_depth_reached=reached_depth,
                            stopped_by=TraversalLimit.RELATIONS,
                        )
                    if neighbor not in visited and len(visited) >= selected.max_works:
                        return CitationTraversalResult(
                            root_work_id=root_work_id,
                            work_ids=tuple(ordered_works),
                            relations=tuple(ordered_relations),
                            max_depth_reached=reached_depth,
                            stopped_by=TraversalLimit.WORKS,
                        )

                    seen_relations.add(relation.relation_id)
                    ordered_relations.append(relation)
                    if neighbor not in visited:
                        visited.add(neighbor)
                        ordered_works.append(neighbor)
                        next_frontier.add(neighbor)
            reached_depth = depth + 1
            frontier = tuple(sorted(next_frontier, key=str))
            if not frontier:
                break
        else:
            if frontier and self._has_unvisited_neighbor(frontier, visited, selected):
                return CitationTraversalResult(
                    root_work_id=root_work_id,
                    work_ids=tuple(ordered_works),
                    relations=tuple(ordered_relations),
                    max_depth_reached=reached_depth,
                    stopped_by=TraversalLimit.DEPTH,
                )

        return CitationTraversalResult(
            root_work_id=root_work_id,
            work_ids=tuple(ordered_works),
            relations=tuple(ordered_relations),
            max_depth_reached=reached_depth,
        )

    def _relations_for(
        self,
        work_id: UUID,
        policy: CitationTraversalPolicy,
    ) -> tuple[WorkRelation, ...]:
        relations: dict[UUID, WorkRelation] = {}
        if policy.direction in {TraversalDirection.OUTBOUND, TraversalDirection.BOTH}:
            for relation in self._citations.list_relations_from(work_id):
                relations[relation.relation_id] = relation
        if policy.direction in {TraversalDirection.INBOUND, TraversalDirection.BOTH}:
            for relation in self._citations.list_relations_to(work_id):
                relations[relation.relation_id] = relation
        allowed = (
            relation
            for relation in relations.values()
            if relation.kind in policy.relation_kinds
        )
        return tuple(sorted(allowed, key=_relation_key))

    def _has_unvisited_neighbor(
        self,
        frontier: tuple[UUID, ...],
        visited: set[UUID],
        policy: CitationTraversalPolicy,
    ) -> bool:
        for work_id in frontier:
            for relation in self._relations_for(work_id, policy):
                neighbor = _neighbor(work_id, relation)
                if neighbor is not None and neighbor not in visited:
                    return True
        return False


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
