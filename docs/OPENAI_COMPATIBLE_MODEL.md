# OpenAI-Compatible Claim Extraction

Tarkka can run the model-assisted claim extractor against a configured OpenAI-compatible chat endpoint without installing a provider SDK.

This is a compatibility adapter, not a provider-specific OpenAI integration. The configured server must expose a `POST /chat/completions` endpoint and support JSON-object response mode.

## Configuration

Set the model endpoint through environment variables:

```bash
export TARKKA_MODEL_BASE_URL="http://localhost:4000/v1"
export TARKKA_MODEL_NAME="my-model"

# Optional when the endpoint requires bearer authentication.
export TARKKA_MODEL_API_KEY="..."

# Optional provenance labels.
export TARKKA_MODEL_PROVIDER="litellm"
export TARKKA_MODEL_VERSION="server-or-model-version"
```

`TARKKA_MODEL_BASE_URL` must use HTTPS for remote endpoints. Plaintext HTTP is accepted only for loopback hosts (`localhost`, `127.0.0.1`, and `::1`) so Tarkka does not accidentally send research text or bearer credentials over an unencrypted remote connection. API keys are never persisted into extraction records.

## CLI

The existing deterministic extractor remains the default:

```bash
tarkka extract claims doc:<document-id>
```

Explicit deterministic mode:

```bash
tarkka extract claims doc:<document-id> --extractor rule
```

Configured model mode:

```bash
tarkka extract claims doc:<document-id> --extractor model
```

Model mode fails before making a request when `TARKKA_MODEL_BASE_URL` or `TARKKA_MODEL_NAME` is missing.

## Contract

The adapter sends normalized passages with stable passage IDs and asks for one JSON object containing a `claims` array. Source document fields and passage text are treated as **untrusted data**. The system instruction explicitly tells the model not to follow commands or requests embedded inside source material.

Each candidate must provide:

- claim text
- confidence in `[0, 1]`
- attribution (`author_stated`, `extractor_inferred`, or `synthesis`)
- claim type
- one or more evidence selectors
- optional concise `reasoning_summary`

Each evidence selector contains:

- `passage_id`
- zero-based `char_start`
- end-exclusive `char_end`

The provider response does **not** become a Tarkka domain record directly. `ModelClaimExtractor` resolves every selector against the normalized `Document`, reconstructs exact evidence text, records model provenance, and rejects invalid spans or unknown passages before persistence.

Prompt instructions are defense in depth rather than a trust boundary. Exact evidence resolution and domain validation remain authoritative even if a model ignores the prompt.

## Compatibility

The adapter is intended for gateways and local servers that implement the compatible chat-completions JSON shape. Examples may include LiteLLM proxies, OpenRouter-compatible routing, vLLM-compatible servers, and other local inference gateways, depending on their configuration and support for JSON response mode.

Provider-specific behavior stays outside Tarkka's core. A future native adapter can implement the same `StructuredClaimModel` protocol without changing extraction contracts, persistence, evaluation, or downstream research workflows.

## Validation

Provider tests remain network-free:

```bash
pytest -q tests/test_openai_compatible_claim_model.py tests/test_model_endpoint_security.py
```

The full project gate remains:

```bash
ruff check .
mypy
pytest
```
