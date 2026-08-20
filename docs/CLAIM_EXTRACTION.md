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
tarkka claims list doc:<document-uuid> --run run:<run-uuid>
tarkka claims show claim:<claim-uuid>
```

`claims show` expands the exact normalized passage-local evidence span, including section, passage, start/end offsets, and text.

## Baseline semantics

`RuleBasedClaimExtractor` is a conservative deterministic baseline, not a general scientific claim detector. It splits normalized passages into simple sentence spans and emits a claim only when a sentence contains an explicit cue such as `shows`, `finds`, `demonstrates`, `revealed`, `confirmed`, `improves`, `reduces`, `predicts`, `outperforms`, or `associated with`.

False negatives are expected. The baseline exists to validate contracts, persistence, evidence locality, and evaluation infrastructure without making an LLM mandatory.

Each execution receives a new random `ExtractionRun` UUID because it represents a distinct auditable run. Evidence and claim IDs are deterministic within that run, but the full ID chain intentionally changes across separate executions. Retrying persistence of the same batch is idempotent; reusing the same `(document_id, run_id)` with different serialized content fails closed.

The current sentence splitter is intentionally lightweight and dependency-free. It does not attempt full scientific sentence segmentation and can split abbreviations such as `e.g.`, `Fig.`, or `et al.` imperfectly. A later extractor/evaluation slice should measure whether a dedicated sentence-segmentation library is justified before adding that dependency.

## Local persistence

The offline reference runtime stores extraction batches in:

```text
$TARKKA_HOME/extractions.json
```

The repository uses Tarkka's existing local exclusive lock and atomic `os.replace` writes. First-time catalog creation is protected by the same lock so concurrent processes cannot overwrite newly persisted runs. PostgreSQL remains the production reference persistence model.

Repository reads can be scoped by `run_id`, kind, offset, and limit. The CLI currently exposes run filtering and pagination through `claims list`.

The local JSON adapter intentionally favors simplicity over large-catalog lookup performance. Direct ID lookups scan the local catalog; production-scale indexed access remains the responsibility of the PostgreSQL adapter.

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

The next extraction adapter should implement the same `StructuredExtractor` contract and must not bypass `ExtractionBatch` evidence/run/document validation. `ExtractionBatch` validates evidence counts, unique IDs, passage spans, run identity, and document lineage at construction time; `validate_extractor_output()` then verifies that the returned batch matches the invoking extractor and input document.
