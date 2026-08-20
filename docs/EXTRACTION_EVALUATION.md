# Extraction Evaluation

Tarkka evaluates claim extraction against source-grounded gold labels rather than requiring identical claim wording.

## Why evidence-grounded matching

A deterministic extractor may emit a source sentence verbatim while a model-assisted extractor may produce a concise paraphrase of the same research claim. Comparing claim strings would penalize useful normalization and make cross-extractor evaluation brittle.

The first harness therefore defines a gold claim by its exact supporting normalized passage span(s):

```text
GoldClaim
  -> evidence: tuple[GoldEvidenceSpan, ...]
  -> attribution: AttributionKind

GoldEvidenceSpan
  -> passage_id: UUID
  -> char_start: int
  -> char_end: int
```

A predicted `Claim` is a true positive only when its complete evidence-span set exactly matches one unmatched gold claim. Each gold item may match at most one prediction, so duplicate predictions count as false positives.

## Metrics

`evaluate_claims(...)` reports:

- true positives
- false positives
- false negatives
- precision
- recall
- F1
- attribution accuracy among matched claims

Attribution is measured separately because a claim can be grounded in the correct source span while still being mislabeled as `author_stated`, `extractor_inferred`, or `synthesis`.

## Current scope

This first harness intentionally does not score semantic equivalence between differently worded claims. Exact evidence grounding is the stable common denominator for the rule-based and model-assisted extractors already implemented.

Later evaluation layers can add:

- claim semantic-equivalence judgments
- partial evidence overlap
- calibration / confidence quality
- latency and model cost
- method/model/variable/dataset/result/limitation metrics
- human adjudication and inter-annotator agreement

Those should extend this harness rather than replace source-grounded evaluation.

## Example

```python
from tarkka.evaluation.claims import GoldClaim, GoldEvidenceSpan, evaluate_claims

report = evaluate_claims(
    batch,
    (
        GoldClaim(
            evidence=(
                GoldEvidenceSpan(
                    passage_id=passage_id,
                    char_start=120,
                    char_end=168,
                ),
            ),
        ),
    ),
)

print(report.precision, report.recall, report.f1)
```

## Validation

The reference tests compare both deterministic and model-assisted extraction paths without network access:

```bash
pytest -q tests/test_claim_evaluation.py
```

The full project gate remains:

```bash
ruff check .
mypy
pytest
```
