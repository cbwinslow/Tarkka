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
