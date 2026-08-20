from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher
from itertools import combinations
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.identifiers import try_normalize_arxiv_id, try_normalize_doi
from tarkka.domain.identity_candidates import IdentityCandidate, IdentityEvidence


class FuzzyIdentityMatcher:
    """Suggest review-only identity candidates using normalized evidence."""

    def __init__(self, *, minimum_confidence: float = 0.90) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum confidence must be between 0 and 1")
        self.minimum_confidence = minimum_confidence

    def find(self, records: tuple[DiscoveryRecord, ...]) -> tuple[IdentityCandidate, ...]:
        candidates = [
            candidate
            for left, right in combinations(records, 2)
            if (candidate := self.compare(left, right)) is not None
        ]
        return tuple(
            sorted(
                candidates,
                key=lambda item: (-item.confidence, str(item.candidate_id)),
            )
        )

    def compare(
        self,
        left: DiscoveryRecord,
        right: DiscoveryRecord,
    ) -> IdentityCandidate | None:
        if left.provider == right.provider:
            return None
        if _strong_identity_relation(left, right) != "none":
            return None

        left_title = _normalize_title(left.title)
        right_title = _normalize_title(right.title)
        if not left_title or not right_title:
            return None
        title_score = SequenceMatcher(
            None,
            left_title,
            right_title,
            autojunk=False,
        ).ratio()
        evidence = [
            IdentityEvidence(
                signal="title_similarity",
                score=title_score,
                detail=f"normalized title similarity={title_score:.3f}",
            )
        ]

        confidence = title_score
        if left.year is not None and right.year is not None:
            delta = abs(left.year - right.year)
            if delta > 1:
                return None
            year_score = 1.0 if delta == 0 else 0.5
            evidence.append(
                IdentityEvidence(
                    signal="publication_year",
                    score=year_score,
                    detail=(
                        "publication years match"
                        if delta == 0
                        else "publication years differ by one year"
                    ),
                )
            )
            confidence = 0.90 * title_score + 0.10 * year_score

        if confidence < self.minimum_confidence:
            return None

        return IdentityCandidate(
            candidate_id=_candidate_id(left, right),
            left_provider=left.provider,
            left_provider_id=left.provider_id,
            right_provider=right.provider,
            right_provider_id=right.provider_id,
            confidence=confidence,
            evidence=tuple(evidence),
        )


def _normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    tokenized = "".join(character if character.isalnum() else " " for character in normalized)
    return " ".join(tokenized.split())


def _strong_identity_relation(left: DiscoveryRecord, right: DiscoveryRecord) -> str:
    left_doi = try_normalize_doi(left.doi)
    right_doi = try_normalize_doi(right.doi)
    if left_doi and right_doi:
        return "same" if left_doi == right_doi else "conflict"

    left_arxiv = _arxiv_id(left)
    right_arxiv = _arxiv_id(right)
    if left_arxiv and right_arxiv:
        return "same" if left_arxiv == right_arxiv else "conflict"
    return "none"


def _arxiv_id(record: DiscoveryRecord) -> str | None:
    if record.provider == "arxiv":
        value = try_normalize_arxiv_id(record.provider_id)
        if value:
            return value
    for key in ("arxiv", "arXiv", "ARXIV"):
        value = try_normalize_arxiv_id(record.external_ids.get(key))
        if value:
            return value
    return None


def _candidate_id(left: DiscoveryRecord, right: DiscoveryRecord) -> UUID:
    identities = sorted(
        (
            f"{left.provider}:{left.provider_id}",
            f"{right.provider}:{right.provider_id}",
        )
    )
    return uuid5(NAMESPACE_URL, "tarkka:identity-candidate:" + "|".join(identities))
