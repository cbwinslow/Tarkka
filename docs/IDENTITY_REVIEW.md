# Identity Review

Tarkka separates deterministic identity from fuzzy identity review.

## Deterministic identity

Strong identifiers such as normalized DOI and arXiv IDs remain authoritative. Matching strong IDs
belong to deterministic identity resolution. Conflicting strong IDs fail closed and are never offered
as fuzzy matches.

## Fuzzy candidates

Fuzzy matching produces **review-only candidates**. It never merges Works.

The initial `title-year-v1` matcher is intentionally conservative and dependency-free:

- compare records from different providers
- normalize titles with Unicode NFKC normalization and case folding
- use `difflib.SequenceMatcher` for title similarity
- require a default confidence of at least `0.90`
- reward matching publication years
- allow a one-year preprint/publication difference with a lower year score
- reject records more than one publication year apart when both years are known
- exclude pairs with matching or conflicting strong identifiers from the fuzzy path
- reject titles that cannot produce meaningful normalized text

Each candidate stores the matcher version, signals, scores, and human-readable details used to
produce its confidence. The candidate ID is deterministic for the same provider-record pair.

Author, venue, and other evidence should only be added after those fields become normalized,
provider-neutral data rather than being inferred from provider-specific metadata.

## Review workflow

```bash
tarkka identity suggest --snapshot <snapshot-id>

tarkka identity decide \
  --snapshot <snapshot-id> \
  --left 0 \
  --right 3 \
  --decision accept \
  --rationale "same study after review"
```

Decisions are appended to `~/.tarkka/identity_decisions.jsonl`. Each audit event preserves the
candidate ID, source snapshot, record indexes, matcher version, confidence, evidence, actor,
rationale, and timestamp so the decision remains explainable even after later matcher revisions.

An `accept` decision means only that the reviewer considers the two observations to represent the
same research work. **It does not merge or mutate canonical Works.** A future reconciliation workflow
may consume accepted decisions explicitly and must preserve provenance and conflict checks.

## Invariant

Fuzzy evidence may recommend review. It must never silently become canonical identity.
