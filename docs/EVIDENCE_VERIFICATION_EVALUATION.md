# Evidence verification evaluation

Tarkka evaluates verification against human-adjudicated, source-handle-grounded
gold labels. A `GoldEvidenceRelation` identifies the exact Claim, Evidence (or
explicit `no_evidence` target), optional citation context, and expected label.

`evaluate_evidence_relations(...)` reports precision, recall, F1, and label
accuracy among predictions that target a gold item. Verifier name/version,
confidence, review state, and reasoning summaries remain auditable provenance;
they are not used as a proxy for correctness.

The evaluator is offline and deterministic. It does not fetch sources or use an
LLM, and it requires exact handles rather than matching prose semantically.
