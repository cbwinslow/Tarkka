# Model-Assisted Claim Extraction

Tarkka supports model-assisted claim extraction without making any model provider part of the core architecture.

## Boundary

A model integration implements `StructuredClaimModel` and receives a `ModelClaimRequest` containing normalized passage IDs, section IDs, ordinals, and text. It returns typed `ModelClaimCandidate` objects with one or more exact `EvidenceSelector` passage spans.

```text
Document
  -> ModelClaimRequest
  -> StructuredClaimModel
  -> ModelClaimCandidate + EvidenceSelector
  -> ModelClaimExtractor
  -> Evidence + Claim
  -> ExtractionBatch
  -> ExtractionRepository
```

The model does not create Tarkka domain records directly. `ModelClaimExtractor` resolves every selector against the normalized document, derives exact evidence text with `Evidence.from_passage(...)`, records model provenance on `ExtractionRun`, and builds the same validated `ExtractionBatch` used by deterministic extractors.

## Fail-closed rules

Model output is rejected when:

- no structured claim candidates are returned
- a claim has no evidence selectors
- confidence is outside `[0, 1]`
- a selector references an unknown passage
- a selector is empty, negative, or extends beyond the normalized passage
- model provider/name/version metadata is blank when required
- the final batch violates any existing document/run/evidence invariant

A claim may be a concise paraphrase, but its evidence must remain exact source text. This keeps semantic normalization separate from source provenance.

## Provenance

Every model-assisted execution gets a distinct `ExtractionRun` UUID. The run stores:

- extractor: `model-claims`
- extractor version
- model provider
- model name
- optional model version
- extraction timestamp

Each claim/evidence record stores its own confidence and optional concise reasoning summary. Hidden chain-of-thought must never be requested or persisted.

Evidence and claim IDs are deterministic within one run; separate executions remain separate auditable runs.

## Provider adapters

The core package intentionally has no model SDK dependency. Future adapters can target OpenAI, Anthropic, LiteLLM, OpenRouter, local inference servers, or agent frameworks as long as they implement `StructuredClaimModel`.

Provider adapters are responsible for translating provider-specific structured output into Tarkka's typed candidates. They must not bypass `ModelClaimExtractor` or construct persisted `Evidence` directly.

## Validation

The reference tests use a fake structured model and no network access:

```bash
pytest -q tests/test_model_claim_extraction.py
```

The test suite verifies exact evidence recovery, model provenance, persistence through `ExtractionService`, unknown-passage rejection, out-of-range rejection, empty-response failure, and candidate evidence requirements.

## CLI status

The model path is not exposed as a CLI extractor until at least one concrete configurable provider adapter exists. Tarkka should not advertise a `--extractor model` command that cannot perform a real configured inference call.
