# Structured research extraction

Tarkka can extract evidence-backed research objects beyond claims without introducing a parallel persistence or provenance system.

The first generalized model slice supports:

- `Method`
- `Dataset`
- `Result`

## Flow

```text
Document
  -> shared bounded passage requests
  -> StructuredResearchModel
  -> Method / Dataset / Result candidates
  -> request-local evidence validation
  -> exact normalized passage Evidence
  -> one ExtractionRun
  -> ordinary ExtractionBatch
  -> ExtractionRepository
```

The model returns candidates, not trusted domain records. Tarkka resolves every evidence selector against the normalized `Document` and fails closed on unknown passages, evidence outside the current request window, invalid offsets, malformed model output, or unsupported candidate kinds.

## Batching

Generalized research extraction reuses the same `ModelBatchingPolicy` as model-assisted claim extraction. The default policy is:

- 40,000 source characters per request
- 32 passages per request
- 1 passage of overlap

Passages remain atomic so evidence offsets stay passage-local and stable. All bounded calls must succeed before an `ExtractionBatch` can be persisted.

## Deduplication

Overlap can cause the same object to be returned more than once. Tarkka deduplicates only exact semantic signatures consisting of:

- object kind
- normalized primary text/name
- attribution
- exact evidence selector set

If duplicate signatures have different confidence values, the highest-confidence candidate is retained. Fuzzy entity merging is intentionally outside this extractor.

## Provider boundary

`StructuredResearchModel` is provider-neutral. `OpenAICompatibleResearchModel` is the first compatibility adapter and uses the same configured OpenAI-compatible `/chat/completions` JSON transport as claim extraction.

The adapter treats document content as untrusted source data and asks for a JSON object containing an `items` array. Provider output never bypasses Tarkka's domain validation.

## Scope

This slice intentionally extracts from normalized text passages. Figure, table, and equation evidence are already first-class domain concepts, but multimodal interpretation remains an optional later adapter. A future extractor can produce those evidence records without changing the canonical research-object or repository contracts.
