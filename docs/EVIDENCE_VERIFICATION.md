# Evidence verification

Verification is a separate, reviewable stage after extraction and citation
preservation. Tarkka records an `EvidenceRelation` between a Claim and exact
Evidence using one of: `supports`, `contradicts`, `partially_supports`,
`qualifies`, `mentions`, `uncertain`, or `no_evidence`.

```bash
tarkka verify record <claim-id> \
  --kind supports \
  --evidence <evidence-id> \
  --citation-context <context-id> \
  --verifier human-review \
  --verifier-version 1 \
  --confidence 0.9

tarkka verify list <claim-id> --limit 20
tarkka verify show <relation-id>

# Before recording, inspect only citation contexts that are exactly co-located
# with the Claim's existing passage evidence; this does not infer support.
tarkka verify candidates <claim-id> --limit 20
tarkka citations context <document-id> <context-id>
```

The record operation validates that the target is a Claim, that non-
`no_evidence` relations name a stored exact Evidence record, and that an
optional citation context belongs to the Claim's document. It stores the
verifier name/version, confidence, human-review state, and optional concise
reasoning summary. Hidden chain-of-thought is neither requested nor stored.

`no_evidence` is explicit: it must not name an Evidence record. All records
are immutable and use a deterministic identity based on the claim, relation
kind, evidence/context handles, and verifier version. Change the verifier
version when a revised assessment is needed.

`list` is bounded to 100 records per request; `show` expands only the selected
assessment and its exact evidence and context anchors when present. Recording
an assessment does not fetch cited sources or make an identity assertion.

`candidates` is a bounded review aid. It returns stable citation-context and
evidence IDs only where a preserved citation context and the Claim's existing
text evidence share the same normalized passage. When the native mention has a
bibliography reference, it also returns that `reference_id`, which can be
expanded through `tarkka citations show <document-id> <reference-id>`. The
candidate response includes its `document_id`; use it with `tarkka citations
context` to expand the exact local context and mention before recording an
assessment. Context expansion fails closed if its required preserved mention is
missing; a mention may still have no bibliography reference. It
excludes figure, table, equation, and unanchored contexts rather than guessing
an association. A candidate is not an assessment and never asserts that a
cited source supports, contradicts, or even discusses the Claim.

For deterministic, human-adjudicated evaluation of these assessments, see
[`EVIDENCE_VERIFICATION_EVALUATION.md`](EVIDENCE_VERIFICATION_EVALUATION.md).
