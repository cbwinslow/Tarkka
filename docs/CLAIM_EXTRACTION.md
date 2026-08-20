# Deterministic Claim Extraction

Tarkka's first structured-extraction vertical slice is intentionally model-free. It proves that normalized documents can become persisted, evidence-backed claims before an LLM adapter is introduced.

## Workflow

```text
Document -> RuleBasedClaimExtractor -> ExtractionBatch -> JsonExtractionRepository
                                                    -> claims list/show
```

Run the baseline extractor for an already-ingested document:

```bash
tarkka extract claims doc:<document-uuid>
```

Inspect claims without loading the full document:

```bash
tarkka claims list doc:<document-uuid>
tarkka claims show claim:<claim-uuid>
```

`claims show` expands the exact normalized passage-local evidence span, including section, passage, start/end offsets, and text.

## Baseline semantics

`RuleBasedClaimExtractor` is a conservative deterministic baseline, not a general scientific claim detector. It splits normalized passages into sentence spans and emits a claim only when a sentence contains an explicit cue such as `shows`, `finds`, `demonstrates`, `improves`, `reduces`, `predicts`, `outperforms`, or `associated with`.

False negatives are expected. The baseline exists to validate contracts, persistence, evidence locality, and evaluation infrastructure without making an LLM mandatory.

Each execution receives a new `ExtractionRun` UUID because it represents a distinct auditable run. Evidence and claim IDs are deterministic within that run. Retrying persistence of the same batch is idempotent; reusing the same `(document_id, run_id)` with different serialized content fails closed.

## Local persistence

The offline reference runtime stores extraction batches in:

```text
$TARKKA_HOME/extractions.json
```

The repository uses Tarkka's existing local exclusive lock and atomic `os.replace` writes. PostgreSQL remains the production reference persistence model.

Repository reads can be scoped by `run_id`, kind, offset, and limit. The CLI currently exposes run filtering and pagination through `claims list`.

## Validation

Run the focused workflow tests with:

```bash
pytest tests/test_claim_extraction_workflow.py
```

The full project gate remains:

```bash
ruff check .
mypy
pytest
```

The next extraction adapter should implement the same `StructuredExtractor` contract and must not bypass `ExtractionBatch` evidence/run/document validation.
