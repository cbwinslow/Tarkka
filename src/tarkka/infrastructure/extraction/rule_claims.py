from __future__ import annotations

import re
from uuid import UUID, uuid5

from tarkka.domain.extraction import (
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
)
from tarkka.domain.models import Document

_TARKKA_CLAIM_NAMESPACE = UUID("a86ad31c-8f5b-5fe7-9c8a-59b0bfad7ac7")
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_CLAIM_CUE_RE = re.compile(
    r"\b(?:shows?|finds?|found|demonstrates?|indicates?|suggests?|reports?|"
    r"improves?|improved|increases?|increased|decreases?|decreased|reduces?|reduced|"
    r"predicts?|predicted|outperforms?|outperformed|associated\s+with|correlates?\s+with)\b",
    re.IGNORECASE,
)


class NoClaimsFoundError(ValueError):
    """Raised when the deterministic extractor finds no supported claim sentence."""


class RuleBasedClaimExtractor:
    """Conservative deterministic baseline for sentence-level claim extraction."""

    name = "rule-claims"
    version = "1.0.0"

    def extract(self, document: Document) -> ExtractionBatch:
        run_id = uuid5(
            _TARKKA_CLAIM_NAMESPACE,
            f"run:{document.document_id}:{self.name}:{self.version}:contract-1",
        )
        run = ExtractionRun(
            run_id=run_id,
            document_id=document.document_id,
            extractor_name=self.name,
            extractor_version=self.version,
        )
        provenance = ExtractionProvenance(run_id=run_id, confidence=1.0)
        evidence: list[Evidence] = []
        claims: list[Claim] = []

        for section in document.sections:
            for passage in section.passages:
                for start, end, text in _claim_spans(passage.text):
                    evidence_id = uuid5(
                        _TARKKA_CLAIM_NAMESPACE,
                        f"evidence:{run_id}:{passage.passage_id}:{start}:{end}",
                    )
                    claim_id = uuid5(
                        _TARKKA_CLAIM_NAMESPACE,
                        f"claim:{run_id}:{passage.passage_id}:{start}:{end}",
                    )
                    item = Evidence.from_passage(
                        evidence_id=evidence_id,
                        passage=passage,
                        passage_char_start=start,
                        passage_char_end=end,
                        provenance=provenance,
                    )
                    evidence.append(item)
                    claims.append(
                        Claim(
                            extraction_id=claim_id,
                            document_id=document.document_id,
                            evidence_ids=(evidence_id,),
                            provenance=provenance,
                            text=text,
                        )
                    )

        if not claims:
            raise NoClaimsFoundError("no deterministic claim sentences found")
        return ExtractionBatch(
            document=document,
            run=run,
            evidence=tuple(evidence),
            extractions=tuple(claims),
        )


def _claim_spans(text: str) -> tuple[tuple[int, int, str], ...]:
    spans: list[tuple[int, int, str]] = []
    for match in _SENTENCE_RE.finditer(text):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        start = match.start() + left
        end = match.start() + right
        if end <= start:
            continue
        sentence = text[start:end]
        if _CLAIM_CUE_RE.search(sentence):
            spans.append((start, end, sentence))
    return tuple(spans)
