# Five-minute offline proof and replay

This walkthrough demonstrates Tarkka's core trust boundary without a model, network provider,
PostgreSQL server, or external research source. Starting from one project-authored local text file,
it uses the normal public CLI to preserve the source, normalize it, extract exact evidence-backed
claims, inspect provenance, export a schema-v3 proof bundle, verify that bundle offline, and replay
the exact deterministic parser.

The research workflow itself has no third-party runtime dependencies. From a repository checkout
with Python 3.11 or newer, `PYTHONPATH=src python -m tarkka` exercises the same top-level CLI
dispatcher as the installed `tarkka` console command, so this demo does not require an install step
or network access.

## Run the walkthrough

The commands below assume a POSIX-compatible shell from the repository root.

```bash
export TARKKA_HOME="$(mktemp -d)"
tarkka_demo() { PYTHONPATH=src python -m tarkka "$@"; }

INGEST_OUTPUT="$(tarkka_demo ingest examples/proof-replay-demo.txt)"
printf '%s\n' "$INGEST_OUTPUT"
DOCUMENT_ID="$(printf '%s\n' "$INGEST_OUTPUT" | awk '/^id: doc:/ {print $2; exit}')"

EXTRACT_OUTPUT="$(tarkka_demo extract claims "$DOCUMENT_ID" --extractor rule)"
printf '%s\n' "$EXTRACT_OUTPUT"
CLAIM_ID="$(printf '%s\n' "$EXTRACT_OUTPUT" | python -c \
  'import json, sys; print(json.load(sys.stdin)["claim_ids"][0])')"

tarkka_demo why "$CLAIM_ID"

tarkka_demo bundle create "$DOCUMENT_ID" --schema-version 3 \
  --output "$TARKKA_HOME/demo-a.tarkka"
tarkka_demo bundle create "$DOCUMENT_ID" --schema-version 3 \
  --output "$TARKKA_HOME/demo-b.tarkka"

cmp "$TARKKA_HOME/demo-a.tarkka" "$TARKKA_HOME/demo-b.tarkka"
tarkka_demo bundle verify "$TARKKA_HOME/demo-a.tarkka"
tarkka_demo replay "$TARKKA_HOME/demo-a.tarkka"
```

A successful final replay includes the important properties below:

```text
"matched": true
"status": "matched"
"determinism": "deterministic"
"parser_name": "plain-text"
"parser_version": "3"
```

`cmp` exits successfully only when both proof-bundle files are byte-for-byte identical. Both bundles
are exported from the same frozen persisted state; this is the reproducibility boundary Tarkka
promises for a deterministic bundle export.

When finished, remove only the temporary directory created for this walkthrough:

```bash
rm -rf -- "$TARKKA_HOME"
```

## What Tarkka proved

The walkthrough uses production paths, not precomputed output:

1. `ingest` stores an immutable content-addressed Artifact and a normalized Document. The plain-text
   parser derives a stable Document identity from the Artifact identity.
2. `extract claims --extractor rule` records an immutable extraction run, exact passage evidence,
   and Claims linked to that evidence. No model is invoked.
3. `why` walks the Claim back through its extraction run, Evidence, normalized Document, and source
   Artifact. No verification relation is invented; the demo correctly shows zero assessments until
   a human or verifier records one.
4. `bundle create --schema-version 3` freezes the Artifact, complete research state, and canonical
   normalized Document into the portable proof bundle.
5. `bundle verify` checks the archive, canonical manifest, member identities, hashes, sizes, and
   document/research-state consistency completely offline.
6. `replay` verifies the bundle again, requires the exact recorded parser identity, reparses the
   preserved Artifact, and compares the canonical normalized Document. It never substitutes a newer
   parser and does not regenerate model output.

## Determinism and provenance are different contracts

The same source bytes produce the same Artifact and plain-text Document identities across clean
local Tarkka homes. A separate claim-extraction execution intentionally receives a new
`ExtractionRun.run_id`; Claim and Evidence identities are scoped to that run. This is desirable:
two executions should remain distinguishable in the audit trail even when they extract the same
sentence.

For that reason, the demo checks byte-identical bundle output by exporting the **same frozen research
state twice**, rather than pretending independent extraction executions are the same event.

## Where to go next

- `docs/PROOF_BUNDLES.md` documents the proof-bundle schemas, verification contract, and replay
  semantics in detail.
- `tarkka verify record ...` can add a reviewable human or tool assessment to a Claim/Evidence pair.
- `tarkka capabilities list` exposes the compact agent-operation index.
- MCP exposes persisted Claim lineage and path-free Document replay to agents.
- The read-only HTTP API exposes the same replay semantics at
  `GET /v1/documents/{document_id}/replay` without accepting server-local filesystem paths.
