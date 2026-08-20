# Bounded Model Extraction

Model-assisted claim extraction is bounded before provider calls so large normalized documents are not sent as one unbounded request.

## Default policy

`ModelClaimExtractor` uses `ModelBatchingPolicy` with these defaults:

- `max_chars=40_000`
- `max_passages=32`
- `overlap_passages=1`

The character budget is a deterministic transport bound, not a provider token guarantee. Provider-specific prompt overhead and tokenization differ, so callers using the Python API may supply a smaller policy for models with tighter context windows.

```python
extractor = ModelClaimExtractor(
    model,
    batching=ModelBatchingPolicy(
        max_chars=20_000,
        max_passages=16,
        overlap_passages=1,
    ),
)
```

The CLI model extractor uses the default bounded policy.

## Passage integrity

Normalized passages remain atomic. Tarkka does not split a passage into a second coordinate system because evidence selectors are passage-local character offsets.

If one normalized passage is larger than `max_chars`, that passage is sent alone. This deliberately preserves the existing exact-evidence contract. A future sub-passage protocol can add explicit offset remapping if very large individual passages become common.

## Deterministic windows

Tarkka walks normalized passages in document order and creates contiguous windows bounded by both character count and passage count. The configured overlap repeats a small number of passages between adjacent requests to preserve local context near boundaries.

Every provider response is scoped to the passages in the request that produced it. A candidate that cites a passage outside its request window fails closed, even if that passage belongs to the same document.

## Overlap deduplication

Overlap can cause the same claim to be returned twice. Tarkka collapses exact semantic duplicates using:

- normalized claim text
- claim type
- attribution
- exact evidence selector set

When duplicate candidates differ only in confidence or concise reasoning metadata, the candidate with the higher confidence is retained.

Tarkka does not fuzzy-merge differently worded claims merely because their evidence overlaps. Ambiguous semantic merging remains outside this deterministic ingestion step.

## Run semantics

All bounded provider calls for one `ModelClaimExtractor.extract(document)` execution become one `ExtractionRun`. Evidence IDs and claim IDs are created only after all request windows have completed and overlap duplicates have been collapsed.

This preserves one auditable extraction execution while preventing a large paper from becoming one unbounded model request.

## Failure behavior

The extraction fails closed when:

- batching policy values are invalid
- a model candidate references a passage outside its request window
- any exact evidence selector is invalid
- every bounded model response contains zero claims
- existing extraction-domain validation fails

Provider/network failures are not silently skipped. Partial batches are never persisted as a successful extraction run.
