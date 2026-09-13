"""Offline evaluation helpers for Tarkka extraction workflows."""

from tarkka.evaluation.claims import (
    ClaimEvaluationReport,
    GoldClaim,
    GoldEvidenceSpan,
    evaluate_claims,
)
from tarkka.evaluation.retrieval import (
    GoldRetrievalQuery,
    RankedRetrievalQuery,
    RetrievalEvaluationReport,
    RetrievalQueryEvaluation,
    evaluate_retrieval,
)
from tarkka.evaluation.staged_retrieval import (
    ModalityEvaluation,
    RelevanceQuery,
    RelevantSegment,
    RetrievalModality,
    StagedRelevanceSet,
    evaluate_lexical_projection,
    evaluate_modalities,
    load_staged_relevance,
    validate_relevance_projection,
)
from tarkka.evaluation.staged_runner import (
    CorpusIngestion,
    CorpusRunStage,
    StagedCorpusReport,
    StagedCorpusRun,
    run_staged_corpus,
)
from tarkka.evaluation.verification import (
    EvidenceRelationEvaluationReport,
    GoldEvidenceRelation,
    evaluate_evidence_relations,
)

__all__ = [
    "ClaimEvaluationReport",
    "GoldClaim",
    "GoldEvidenceSpan",
    "evaluate_claims",
    "EvidenceRelationEvaluationReport",
    "GoldEvidenceRelation",
    "evaluate_evidence_relations",
    "GoldRetrievalQuery",
    "RankedRetrievalQuery",
    "RetrievalEvaluationReport",
    "RetrievalQueryEvaluation",
    "evaluate_retrieval",
    "CorpusIngestion",
    "CorpusRunStage",
    "StagedCorpusReport",
    "StagedCorpusRun",
    "run_staged_corpus",
    "ModalityEvaluation",
    "RelevantSegment",
    "RelevanceQuery",
    "RetrievalModality",
    "StagedRelevanceSet",
    "evaluate_modalities",
    "evaluate_lexical_projection",
    "load_staged_relevance",
    "validate_relevance_projection",
]
