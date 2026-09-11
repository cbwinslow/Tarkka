# Research library and compiled encyclopedia

## Purpose

Tarkka's kernel already preserves sources, claims, evidence, and proof bundles. The next product
layer is a **durable research library** that agents and people keep filling, and a **compiled
encyclopedia** that turns that library into something both can actually use.

This document is the durable product contract. GitHub issues remain the execution specs for each
slice. It does not replace [`CANONICAL_DATA_MODEL.md`](CANONICAL_DATA_MODEL.md),
[`ARTIFACT_COMPOSITION.md`](ARTIFACT_COMPOSITION.md),
[`SIMILARITY_CONSENSUS_AND_GRAPH.md`](SIMILARITY_CONSENSUS_AND_GRAPH.md),
[`AGENT_INTERFACE.md`](AGENT_INTERFACE.md), or [`CONTEXT_EFFICIENCY.md`](CONTEXT_EFFICIENCY.md).
It says how those contracts compose into a library people understand and agents can query at scale.

## Product thesis

Tarkka is not a chat-with-papers product. It is:

> a content-addressed **library** of captured research state, from which Tarkka compiles versioned
> **encyclopedia editions** that humans read as articles/receipts and agents retrieve as bounded
> handles.

The encyclopedia is smart because every article sentence can be expanded to exact evidence, because
disagreement is preserved, and because an edition can be replayed. It is not smart because a model
wrote a fluent Wikipedia page.

Issue #198 remains the trust-layer north star (proof, replay, challenge). This document is the
knowledge-layer north star (capture, compile, navigate, scale).

## Three nouns

Keep these distinct. Do not collapse them into "the database" or "the wiki."

```text
Workspace  →  one research project / question / policy
Library    →  durable captured objects (works, artifacts, claims, evidence, snapshots)
Encyclopedia edition  →  compiled, versioned, topic-oriented articles over a library
```

### Workspace

A bounded project. It has research questions, source policy, domain pack, token/crawl budgets, and
a Frozen vs Live mode. `examples/mlb-research.yaml` is the intended user-facing shape.

A workspace **contributes to** a library. It is not itself the long-term warehouse.

### Library

The warehouse of captured research objects. Identity, provenance, rights, and immutability live
here. Adding a paper, extracting claims, recording a verification, or storing a search snapshot
are library writes.

A library may start as one local workspace's store (`TARKKA_HOME`). The contract must allow several
workspaces to share one library without rewriting objects.

### Encyclopedia

A **derived compilation**, not a second source of truth. An encyclopedia **edition** is a frozen
composition of topic articles over an explicit library snapshot. Articles select claims, evidence
relations, and source locators; they never overwrite them.

Recompiling after new ingest produces a new edition. Diffing editions is the same frozen-research
diff idea applied to compiled knowledge.

## How captured information is leveraged

Every captured object has to earn a retrieval path. The compile pipeline is:

```text
acquire / ingest
  → preserve Artifact (sha256)
  → normalize Document
  → extract Claims / Methods / … with Evidence
  → verify / challenge (supports, contradicts, qualifies, no-evidence)
  → index (lexical, later embedding) as versioned derivations
  → catalog into Library topics (candidates, not merges)
  → compile Encyclopedia articles (compositions)
  → serve receipts (humans) and manifests (agents)
```

Leverage rules:

1. **Never query raw PDFs by default.** Agents start at article manifests or claim receipts.
2. **Never flatten disagreement.** An article may say "A supports, B contradicts" and must link
   both. Consensus observations stay scoped; see
   [`SIMILARITY_CONSENSUS_AND_GRAPH.md`](SIMILARITY_CONSENSUS_AND_GRAPH.md).
3. **Negative knowledge is library content.** A SearchSnapshot that found nothing is evidence of
   absence of *search*, not absence of truth. Persist it so agents cannot invent "there is no
   literature."
4. **Rights travel with expansion.** `may_send_to_model`, storage, and redistribution are checked
   before article text or source spans enter an agent context.
5. **Compilation is inferred.** Article prose, topic grouping, and "related claims" are inferred
   or reconstructed layers. Native source facts remain underneath.

## Human surface

People should not need the CLI taxonomy.

Default objects they see:

- **Workspace** — "MLB game-outcome research"
- **Article** — "Pitcher fatigue and next-start performance"
- **Claim receipt** — one claim, exact quote, source, verification state, what would change it
- **Contradiction board** — claims that disagree, with independence/recency/review state
- **Brief** — a short compiled reading of one workspace or article, every non-trivial sentence
  citing a claim ID
- **Edition changelog** — frozen vs live: what newly appeared, retracted, or flipped verification

Candidate commands (names may change in the implementing issue; the nouns must not):

```text
tarkka claims receipt <claim-id>
tarkka documents brief <document-id>
tarkka why <claim-id>
tarkka workspace init <manifest.yaml>
tarkka workspace run
tarkka library show
tarkka library show <library-id>
tarkka library documents --library <library-id> --limit 20
tarkka library claims --library <library-id> --limit 20
tarkka library works --library <library-id> --limit 20
tarkka encyclopedia compile
tarkka encyclopedia show <article-id>
tarkka challenge <claim-id>
tarkka workspace brief
tarkka workspace serve
```

v1 ships `claims receipt`, `documents brief`, Frozen workspace init/run, challenge, encyclopedia
compile, and a named library catalog (`tarkka library show` plus paged document/claim/work
listings). Omitting the library id is valid only when exactly one library exists; otherwise pass
`library-id` / `--library`. Listings are manifests (counts, titles, token estimates), not full text.

`workspace serve` is a local receipt/article viewer plus MCP. It is not a chat UI.

Expert flags (derivation versions, configuration fingerprints, backends) remain available. They
must have workspace defaults so a new user never types them.

## Agent surface

Agents get the same library and encyclopedia through a small verb set. Detailed schemas load only
after capability discovery.

```text
research.capabilities
research.search      # library + encyclopedia, not provider-specific tools
research.get         # representation=manifest|receipt|evidence|full
research.expand      # one handle, one budgeted step
research.compare     # claims, methods, editions, contradictions
research.verify      # record or retrieve assessments; includes challenge
research.export      # proof bundle, brief, encyclopedia edition
```

### Context wallet

A question or agent session carries an explicit token budget. Tarkka returns cheaper
representations first and fails closed with `content_too_large` plus next actions when an expansion
would exceed the remaining wallet. Wallet spend is telemetry (operation, bytes, estimated tokens,
latency) without storing source text or request arguments.

This is how the encyclopedia stays usable by Codex, Claude, and other agents as the library grows.

### Agent run as library object

An agent session that used Tarkka should be exportable as a proof bundle: searches, opened
handles, relied-upon claims, skipped expansions, and wallet spend. Another party can audit the
agent's homework without trusting the model.

## Encyclopedia article contract

An article is a composition over library objects:

- stable `article_id` and human slug/title
- `topic_id` / research-question scope
- `edition_id` (the compile it belongs to)
- ordered sections that are receipts, not raw chapters
- claim IDs with evidence relation labels
- contradiction and qualification lists
- "not found" / search-completeness handles when relevant
- compiler name/version (deterministic selector first; optional model compiler later, labeled
  inferred)
- rights summary for the compiled output
- estimated tokens for the article manifest vs each section

Deterministic compilation is required for encyclopedia editions (#348), after receipts/briefs:

- select claims whose evidence intersects the topic scope
- group by support/contradict/qualify
- order by review state, recency, and source independence — never by unexplained score
- render receipts into Markdown with claim IDs

A later optional model compiler may write a narrative overlay. That overlay is inferred, versioned,
and never the only representation.

## Scale contract

Scale is a property of the library, not a separate product.

What must remain true from one laptop to many agent sessions:

| Layer | Scale unit | Rule |
|---|---|---|
| Artifact | SHA-256 object | Local disk first; S3/R2-compatible store is a port swap |
| Metadata | PostgreSQL (JSON default for offline) | `workspace_id` / `library_id` on every row |
| Derivations | versioned indexes, embeddings, OCR | rebuildable; never mutate source |
| Jobs | ingest / extract / index / compile | resumable, idempotent, backpressured |
| Serving | MCP / HTTP / CLI | stateless workers against shared metadata |
| Encyclopedia | edition snapshots | compile once, serve many; diff editions instead of mutating articles |
| Agents | context wallet + quotas | tokens, expansions, provider calls, crawl depth, stored bytes |

The initial local profile persists compile-job identities and their final checkpoints in the
library home. A repeated compile with the same workspace snapshot and compiler fingerprint returns
the already-completed edition; a failed job retains its checkpoint for an explicit retry. Job
identity is scoped to the workspace and library, so one library cannot reuse another library's
compile result. This local JSON implementation is an offline adapter, not the future shared durable
job table. A concurrent request for the same running job fails with a typed in-progress error rather
than producing a second edition; local crash recovery is deliberately explicit because this adapter
does not implement a distributed lease.

Do **not** introduce a graph database, dedicated vector product, or mandatory queue before a
measured library hurts. pgvector and a durable job table are the first scale-out tools.

Embedding indexing is an explicit, transport-neutral application operation over one exact persisted
retrieval-segment projection. Its caller supplies both the replaceable embedder and immutable store;
the operation does not select, download, or silently substitute a model. Each returned vector is
validated against the exact segment identity, digest, and derivation/configuration key before it can
be persisted.

Federation comes after one library works: workspaces and foreign Tarkka bundles are cited by
digest. Foreign articles are references, not silent merges.

## Mapping from the current kernel

Already implemented and reused:

- content-addressed artifacts and acquisition provenance
- `Document → Section → Passage` and generalized evidence
- claims, verification relations, `tarkka why`
- proof bundles v1–v3, replay, frozen-bundle diff
- composition manifests (section-only Markdown v1)
- capability index, MCP read path, context packages
- lexical retrieval as an explicit derivation; workspace-scoped index requests use durable
  library/workspace `INDEX` jobs while preserving a reusable document/configuration projection
- workspace domain object (not yet the product noun)

Specified nearby, not yet the encyclopedia:

- similarity candidates and consensus observations (#300)
- bounded graph projections (#301)
- hybrid retrieval (#313) and embedding indexing (#340)
- bulk ingest jobs (#280)
- HTTP/MCP/CLI namespace unification (#279)

Those slices feed the library and article compiler. They are not a substitute for workspace,
receipt, and encyclopedia contracts.

## Invariants

- An encyclopedia article never becomes the canonical Work or Claim.
- Topic grouping and relatedness are candidates until an explicit accept/reject decision.
- Native / reconstructed / inferred labels survive compilation.
- Core compile and serve paths must work with no LLM.
- Rights/access/redistribution/commercial-use remain separate from software license.
- Progressive disclosure: article manifest → section/receipt → evidence → source → artifact.
- Agent tools stay few; operation schemas stay on demand.
- No first-party chat UI in this contract. Briefs, receipts, articles, and MCP are the surfaces.

## v1 product (what we ship first)

Users and agents should not have to learn three nouns on day one. They have a **project**
(Workspace). Tarkka files objects in a default named library (`{workspace-name}-library`); the
Library noun stays in the background until someone has two workspaces. The first compiled view is a
**brief of claim receipts**, not a Wikipedia-style encyclopedia.

Workspace init persists that default library name and stores `library_id` on the workspace record.
Two workspaces may share one library without rewriting artifact hashes. `edition_id` stays a
compile-time handle.

v1 is successful when:

1. A person can open a claim receipt and a document brief without knowing derivation fingerprints.
2. An agent can fetch the same receipt/brief under a later token wallet (#346).
3. Support is never implied: no verification means `unreviewed`, not `supports`.
4. Time-to-brief on the offline proof fixture stays in the existing five-minute path.
5. Vectors remain optional retrieval, not the product.

The first encyclopedia **is** that brief. Topic editions (#348) wait until a real rights-clean
corpus exists. Scale ports (#349) mean isolation keys on writes, not S3 in the same slice.

## Spec-driven execution

Do not implement this document in one change. Each row is a GitHub issue using
[`FEATURE_SPEC_TEMPLATE.md`](FEATURE_SPEC_TEMPLATE.md). Promote only decisions that stay true
across issues back into this file or the canonical model.

Do not add further durable architecture documents unless a slice is blocked. Execution is issues
and PRs.

Recommended issue order (parent [#342](https://github.com/cbwinslow/Tarkka/issues/342)):

1. [#345](https://github.com/cbwinslow/Tarkka/issues/345) **Claim receipts and document briefs** — the readable surface over existing claims (`tarkka claims receipt`, `tarkka documents brief`). Workspace brief waits for #343.
2. [#346](https://github.com/cbwinslow/Tarkka/issues/346) **Compact agent verbs and context wallet** — `get(representation=receipt)` and budgeted expand.
3. [#343](https://github.com/cbwinslow/Tarkka/issues/343) **Workspace as the product noun** — init/run from YAML; Frozen/Live; the store behind it is the default library.
4. [#347](https://github.com/cbwinslow/Tarkka/issues/347) **Challenge and contradiction board** — contrary evidence; disagreement in the brief.
5. [#344](https://github.com/cbwinslow/Tarkka/issues/344) **Named library catalog** — only when one workspace is no longer enough to browse.
6. [#348](https://github.com/cbwinslow/Tarkka/issues/348) **Encyclopedia compile** — topic articles over a real corpus; UI word remains `brief`/`article`.
7. [#349](https://github.com/cbwinslow/Tarkka/issues/349) **Scale-ready isolation** — `workspace_id`/`library_id` on writes and the artifact-store port. Object storage and worker pools wait until a measured library is slow.

Embeddings (#340) and hybrid retrieval (#313) stay off this critical path. They are candidate
generators inside the library, not a replacement for receipts.

Domain packs (baseball, finance) specialize topic vocabularies and quality policy. They do not
fork the encyclopedia model.

## Non-goals for the first encyclopedia

- replacing Wikipedia or hosting copyrighted full text for redistribution
- LLM-generated articles as the system of record
- automatic merge of similar claims or works
- institutional SSO, multi-region, or a mandatory worker cluster
- a general document editor
- a graph database

## Success criteria

A v1 of this layer is successful when:

1. A person can produce a claim receipt and a document brief from ingested local research without
   typing derivation fingerprints.
2. An agent can fetch the same receipt/brief (walleted get in #346) without loading full documents.
3. Every brief statement expands to a claim ID and exact evidence, or is labeled `unreviewed` /
   `no_evidence` / inferred — never implied `supports`.
4. Recompiling after a new ingest produces a new edition whose diff is explainable.
5. The same library runs locally on JSON and, with an explicit backend choice, on PostgreSQL
   without changing article identity.
6. Adding an object-store adapter does not change Claim, Article, or Edition contracts.
