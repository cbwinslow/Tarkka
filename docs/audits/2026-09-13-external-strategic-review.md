> Historical external strategic review, archived 2026-09-13.
>
> This report records an outside assessment of the repository at a specific point in time. It is
> not a current specification, roadmap, or task record. The canonical disposition of its
> recommendations is GitHub issue #390; durable decisions live in the project contracts that issue
> links to. Do not treat a recommendation here as an acceptance criterion without checking current
> issues, code, and docs.

# Tarkka Project Audit and Strategic Review
Repository: cbwinslow/Tarkka
Audit date: 2026-09-13
Reviewed branch: main
Reviewed head: 801dd552ada730f3e62c64decd1eeb23b8e040fe
Audit type: architecture, codebase, workflows, testing, product strategy, research methodology, developer experience, security, scalability, and roadmap review

1. Executive Summary
Tarkka has evolved well beyond a prototype. It is now a serious, highly structured research-infrastructure project whose strongest differentiator is not "AI research" in the generic sense, but auditable research state:

preserve the source, normalize it deterministically, keep claims distinct from evidence, retain provenance, permit challenge and contradiction, export the state, and let another machine independently verify or replay it.

That is a much more defensible position than competing as another "chat with papers" application.

The repository is strongest in five areas:

Architecture discipline — the domain/application/ports/infrastructure/interface separation is real rather than cosmetic.
Trust and provenance — immutable artifacts, evidence lineage, citation separation, deterministic replay, proof bundles, and rights-aware expansion are foundational concepts rather than later additions.
Testing and engineering rigor — strict typing, contract tests, property tests, security regressions, failure injection, PostgreSQL integration tests, mutation testing, branch coverage, and change-coverage gates are unusually mature.
Agent-first design — the project treats context as a constrained resource and exposes progressive research representations instead of dumping entire documents into an LLM.
Spec-driven development — issues define contracts and non-goals, PRs implement bounded slices, and deterministic CI remains authoritative over AI review.
The main problem is no longer "Can this architecture work?" It clearly can.

The main problem is now:

Can Tarkka become easy enough, demonstrably useful enough, and externally validated enough that researchers or agent developers choose it rather than merely admire its architecture?

The project is currently engineering-heavy and product-validation-light. The deterministic test surface is extraordinarily strong, but the public real-world evaluation remains intentionally tiny. The CLI and domain vocabulary are powerful but broad. Several status documents and open issues lag behind merged functionality. Packaging/release policy is not finalized. HTTP/API parity is unfinished. Production-scale operational behavior has been designed more deeply than it has been measured.

Bottom-line assessment



Area	Assessment	Notes
Product thesis / differentiation	Excellent	"Research you can replay" is a strong, defensible wedge.
Core architecture	Excellent	Clear boundaries and stable contracts.
Evidence/provenance model	Excellent	Probably the strongest part of the project.
Testing / correctness discipline	Excellent	Exceptionally mature for a 0.1 project.
CI / repository automation	Excellent	Strong deterministic and security gates.
Security architecture	Very good	Strong local/network boundaries; institutional controls intentionally incomplete.
Persistence / durability	Very good	JSON + PostgreSQL adapters, migrations, conformance; some parallel-surface cost.
Agent interface	Very good	Progressive disclosure is a real innovation; write/API parity is still evolving.
CLI / human UX	Good, but complex	Rich capabilities; command surface and terminology can overwhelm new users.
External evaluation	Early	Real evaluation exists, but the corpus and relevance set are still tiny.
Performance / scale validation	Early-to-middle	Good contracts, insufficient systematic benchmarks.
Release / ecosystem maturity	Early	v0.1.0, no finalized public release/PyPI policy yet.
Documentation	Very strong, with drift	Excellent depth; several stale status statements need reconciliation.
Overall: Tarkka is architecturally closer to a serious research platform than many projects with far larger feature lists. The next phase should emphasize proof of usefulness, adoption, interoperability, evaluation, and simplification rather than continuing to maximize internal surface area.

2. Scope of This Audit
This review examined the current repository structure and current main, including:

README.md
AGENTS.md
CLAUDE.md
pyproject.toml
src/tarkka/{domain,application,ports,infrastructure,interfaces,evaluation,conformance}
PostgreSQL migration history
the current CLI composition approach
project architecture, roadmap, testing, security, agent-interface, and research-library documents
GitHub workflow definitions and automation documentation
recent merged pull requests
current open roadmap/issues
current evaluation results
packaging and optional dependency boundaries
repository-driven AI review/development conventions
This is primarily a repository and architecture audit. It is not a large-scale performance benchmark, security penetration test, or independent scientific validation of the research methods.

3. What Tarkka Is Today
Tarkka is best understood as five systems layered together.

text

1. SOURCE PRESERVATION
   source -> immutable Artifact -> acquisition/source provenance

2. NORMALIZED RESEARCH STATE
   Artifact -> Document -> Section -> Passage
                     -> figures/tables/equations
                     -> bibliography/citations/resources

3. RESEARCH INTERPRETATION
   Document -> Claim / Method / Dataset / Variable / Result / Limitation
            -> Evidence
            -> Verification / contradiction / qualification

4. TRUST / REPRODUCIBILITY
   provenance -> why -> proof bundle -> verify -> replay -> diff

5. PRODUCT / AGENT SURFACE
   Workspace -> Library -> receipts/briefs -> Encyclopedia editions
                           -> manifests/context wallets -> MCP/CLI/HTTP
This layered interpretation is important because it explains why the repository feels larger than a document-RAG tool: it is intentionally modeling the lifecycle of research state rather than only text retrieval.

4. Product Thesis and Differentiation
4.1 The strongest strategic decision
The strongest decision in Tarkka is explicitly refusing to position the product as another conversational RAG frontend.

The current thesis is approximately:

Tarkka is the auditable evidence layer underneath humans and AI research agents.

That positioning is substantially stronger than:

"chat with PDFs,"
"AI literature review,"
"semantic paper search,"
"GraphRAG for research,"
"NotebookLM but open source."
Those categories are already crowded and increasingly commoditized.

Tarkka instead owns a different problem:

How can another person or agent inspect what evidence was used, where it came from, how it was transformed, what was inferred, what contradicted it, and whether the non-model processing can be replayed?

That is a genuine technical and product wedge.

4.2 Why the thesis fits the code
The positioning is not marketing pasted on top of unrelated implementation. The repository already contains the primitives required to support it:

immutable content-addressed artifacts;
acquisition/source provenance;
normalized document structure;
separate citations, claims, and evidence;
deterministic rule extraction;
explicit inferred/model-assisted records;
verification relations;
contradiction/challenge workflows;
claim lineage via tarkka why;
versioned proof bundles;
offline verification;
deterministic replay;
research-state diff;
rights/access policy;
agent context budgets;
portable/interoperable export work such as RO-Crate.
This alignment between product thesis and architecture is a major strength.

4.3 Product risk: the scope is still enormous
The long-term roadmap contains all of the following:

scholarly discovery;
heterogeneous document parsing;
web crawling;
research extraction;
citation graphs;
semantic retrieval;
vector search;
graph projections;
workspace/library management;
encyclopedia generation;
HTTP/MCP/CLI;
plugin SDK;
domain packs;
institutional tenancy;
object storage;
jobs/workers;
observability;
potentially OCR/vision.
Each item is reasonable individually. Collectively, they create a risk that Tarkka becomes an exceptionally good framework that never reaches a simple product moment.

Recommendation
Freeze the public v1 narrative around only four promises:

Capture a research source without losing provenance.
Extract or record claims tied to exact evidence.
Challenge and inspect the evidence.
Export/replay the research state.
Everything else should be explained as an extension of those four actions.

5. Architecture Review
5.1 Overall structure
The project uses a strong ports-and-adapters / clean-architecture style:

text

interfaces
    ↓
application
    ↓
domain

infrastructure/adapters
    ↓ implements
ports/contracts
The actual package layout supports this:

text

src/tarkka/
    application/
    conformance/
    domain/
    evaluation/
    infrastructure/
    interfaces/
    ports/
This is a good architecture for Tarkka because research infrastructure has many volatile external dependencies:

parsers,
publication APIs,
model providers,
databases,
object stores,
retrieval engines,
transport protocols.
The system therefore benefits materially from narrow replaceable contracts.

5.2 Particularly good architectural rules
The most important rule in the repository is:

Preserve native structure first; normalize second; infer last.

This rule protects Tarkka from a common failure mode in AI/research systems: allowing a parser, vectorizer, or LLM representation to become the "truth."

The architecture explicitly separates:

text

native fact
    ↓
parser-reconstructed observation
    ↓
inferred interpretation
That distinction should remain non-negotiable.

Other excellent rules include:

providers do not call one another;
provider identity and canonical research identity remain separate;
ambiguous/fuzzy identity is reviewable rather than silently merged;
retrieval segments are derivatives, not evidence boundaries;
embeddings never replace canonical passages;
encyclopedia articles are compiled views, not source-of-truth objects;
graph views are projections, not justification for immediately adding a graph database;
domain-specific semantics live in domain packs rather than contaminating the generic core.
These are mature decisions.

5.3 Architecture con: conceptual surface area
The cost of this rigor is concept count.

A contributor may encounter:

Artifact
Acquisition
SourceObservation
ResourceLinkObservation
Work
Document
Section
Passage
CitationMention
CitationContext
BibliographicReference
WorkRelation
Claim
Evidence
EvidenceRelation
ExtractionRun
SearchSnapshot
RetrievalSegment
ContextPackage
Workspace
Library
Article
Edition
Job
Capability
Proof bundle
These distinctions are mostly valid, but they create a steep learning curve.

Recommendation
Keep the internal model rich, but give users and extension developers fewer public nouns.

For a new user:

text

Project
Source
Claim
Evidence
Brief
Bundle
can be enough initially.

For adapter authors:

text

Candidate
Artifact
Document
Observation
can be enough.

The rest can emerge progressively.

6. Domain Model Review
6.1 Strengths
The domain package shows good separation of stable concepts rather than one enormous generic schema.

Examples include dedicated modules for:

bibliography,
citations,
document structure,
extraction,
discovery,
source observations,
identifiers,
traversal,
context packages,
verification.
That is preferable to an "everything is JSON" architecture.

The project also correctly recognizes that some upstream facts do not yet deserve promotion into canonical fields. SourceObservation is the right pressure-release valve: source-native information can be retained without permanently encoding one provider's schema into the core.

6.2 Strong evidence model
The distinction between Claim, Evidence, and Citation is particularly important.

Many research systems implicitly treat:

text

paper cites source X
as equivalent to:

text

source X supports claim Y
Tarkka does not.

This enables a real verification workflow:

text

Claim
  ↓
Evidence candidate
  ↓
Evidence relation:
    supports
    contradicts
    qualifies
    partial support
    no evidence
That is a substantive advantage.

6.3 Risk: model granularity can become self-reinforcing
Once a typed concept exists, future code tends to depend on it. This makes early over-modeling expensive.

The open issue around promoting footnotes, links, table cells, equations, media assets, and source locators is therefore correctly cautious.

Recommendation
Before introducing a new canonical type, require:

at least two materially different source formats;
a demonstrated user/research operation that needs it;
loss or ambiguity that cannot be handled safely through SourceObservation;
JSON and PostgreSQL round-trip semantics;
proof/replay implications.
The existing project philosophy already points this way; it should remain an explicit acceptance gate.

7. Discovery and Source Acquisition
7.1 Strong current state
Tarkka has a provider-neutral scholarly discovery architecture with support for multiple providers and explicit intent/capability routing.

The roadmap indicates support for:

OpenAlex,
Crossref,
Semantic Scholar,
arXiv.
The discovery implementation includes valuable reproducibility properties:

provider-specific cursors;
bounded concurrent fan-out;
retry/rate-limit handling;
SearchSnapshots;
deterministic strong-ID identity;
DOI/arXiv normalization;
source/provider observation preservation;
review-only fuzzy identity candidates.
This is a strong design.

7.2 Excellent identity decision
Fuzzy identity is not silently accepted.

That matters because automatic deduplication is one of the fastest ways to corrupt a research corpus.

Tarkka's distinction between:

text

strong identifier match
and:

text

candidate similarity requiring a decision
is correct.

7.3 Remaining acquisition gap
The generic capability-routed acquisition boundary remains an active design area.

The current pieces are strong, but the fully generalized architecture for:

local files,
HTTP,
scholarly resources,
websites,
bulk archives,
APIs,
feeds,
cloud/document stores,
custom MCP connectors
still needs to converge behind one coherent acquisition/candidate contract.

Recommendation
Complete the acquisition router before adding many more provider-specific connectors.

Otherwise the project risks accumulating several semi-overlapping concepts such as:

text

discovery result
full-text representation
resource link
URL acquisition
crawler result
source observation
without a simple shared entry path.

8. Parsing and Document Preservation
8.1 Strength
Tarkka understands that a PDF is not always the best representation of a publication.

The preference for richer native structure—JATS, EPUB, semantic HTML, LaTeX source—before reconstructed PDF structure is exactly right.

The architecture also treats Docling as an adapter rather than making it the canonical data model.

That protects Tarkka from vendor/library lock-in and parser schema churn.

8.2 Correct multimodal boundary
Figures, tables, equations, OCR, and vision are treated as separately provenanced source or reconstructed observations.

This prevents an OCR model's output from silently overwriting what the source actually contained.

8.3 Remaining work
The open source-native-structure issue correctly identifies areas that are not yet fully canonical:

footnotes/endnotes;
inline links and internal cross-references;
structured table cells;
media asset relationships;
multiple equation representations;
source/layout coordinates;
web-content roles.
This is meaningful future work, but it should remain evidence-driven.

9. Extraction and Research Objects
9.1 Strengths
The extraction layer is not hard-coded to one model provider.

The architecture supports:

deterministic/rule extraction;
OpenAI-compatible model extraction;
local models;
future provider adapters.
The core itself does not require an LLM.

That is a significant trust advantage because the pipeline can produce useful artifacts and validate replay without depending on probabilistic external calls.

9.2 Good provenance behavior
Model-assisted outputs retain their execution/extraction provenance rather than pretending they are source-native facts.

This preserves the most important distinction in AI research tooling:

"The source said this" and "the model inferred this" are not the same statement.

9.3 Gap: quality validation is behind implementation rigor
There is extensive structural testing around extraction contracts and evidence bounds, but the public empirical benchmark for extraction quality does not yet appear as mature as the implementation.

The project needs more published measures such as:

claim extraction precision;
claim extraction recall;
evidence-span exactness;
method/result extraction accuracy;
cross-format consistency;
model-vs-rule extraction comparison;
failure rate by source type.
Recommendation
Treat evaluation data as product code.

A high-quality open evaluation corpus may be more strategically valuable now than another extraction adapter.

10. Evidence Verification, Challenge, and Contradiction
This is one of Tarkka's most interesting areas.

10.1 Why it matters
Most RAG systems answer:

"What evidence supports this?"

Tarkka is building toward:

"What evidence supports, contradicts, qualifies, or fails to support this—and can I inspect the exact source?"

That is far more useful for serious research.

10.2 Current strengths
The project already models:

verifier identity/version;
evidence relation type;
confidence;
human review state;
citation context;
exact evidence expansion;
contradiction/challenge workflows;
bounded comparison for agents.
The challenge workflow intentionally does not select a winner automatically.

That is a strong research-integrity choice.

10.3 Risk
The initial challenge rule is intentionally simple. Future similarity/consensus systems will create pressure to assign "truth" or confidence scores.

Recommendation
Continue resisting a universal truth score.

Prefer inspectable dimensions:

direct vs secondary evidence;
support vs contradiction;
independent vs shared source lineage;
recency;
review status;
model dependence;
retraction/correction state.
This is already consistent with the project thesis and should remain a product principle.

11. Retrieval and Embeddings
11.1 Very good architectural restraint
Tarkka explicitly models retrieval as a derived navigation layer rather than source truth.

That is the correct boundary.

A retrieval segment:

points to exact canonical passages/spans;
has its own derivation identity;
does not become Evidence itself.
An embedding:

is versioned;
records model/revision/configuration;
belongs to an exact retrieval projection;
cannot overwrite the canonical document.
That is excellent.

11.2 The recent empirical result is encouraging for project culture
The first measured local embedding baseline did not beat lexical retrieval on the tiny staged corpus.

Recent measurements were approximately:




Retrieval	MRR	Precision@2	Recall@2
Lexical	1.0	0.75	0.75
Vector	0.5	0.5	0.5
Hybrid	1.0	0.75	0.75
The important result is not that lexical "wins forever." The important result is that the project measured first and did not force an embedding/reranker story anyway.

That is excellent engineering behavior.

11.3 Gap: benchmark size
Two queries over a single staged corpus are not enough to choose defaults.

Before choosing a default vector model or introducing reranking, expand evaluation to:

50–100+ reviewed queries;
multiple domains;
paraphrase-heavy semantic queries;
exact identifier queries;
citation/reference lookup;
methods/results queries;
multilingual queries if multilingual support is claimed;
hard negatives;
domain-specific MLB queries.
Recommendation
Keep lexical retrieval the dependable baseline until vectors demonstrate measurable value.

12. Workspace, Library, and Encyclopedia Layer
12.1 Product model
The three nouns are conceptually sound:

text

Workspace = a bounded research project
Library   = durable captured research objects
Edition   = compiled versioned view over a library
This lets the project distinguish:

active research configuration,
long-term research state,
human/agent presentation.
12.2 Strong rule
An Encyclopedia article is not canonical knowledge.

It is a derived composition over claims/evidence.

That protects the system from eventually turning generated prose into its own evidence source.

12.3 Risk: user-facing vocabulary
The project correctly acknowledges that new users should not be forced to learn Workspace + Library + Edition immediately.

The v1 decision to emphasize the project/workspace and keep the library mostly in the background is correct.

Recommendation
Continue this simplification.

A first-time flow should feel like:

bash

Run

$
tarkka init research.yaml
$
tarkka run
$
tarkka brief
$
tarkka challenge <claim>
$
tarkka bundle create
rather than requiring users to understand internal persistence layers.

13. CLI Review
13.1 Strength
The CLI is extremely capable and works as a serious automation interface, not merely a demo.

The top-level dispatcher has begun splitting independently encapsulated command families such as:

bundle,
replay,
diff,
workspace,
library,
encyclopedia,
challenge,
telemetry,
evaluation.
That is a healthy direction.

13.2 Main maintainability hotspot
src/tarkka/interfaces/main.py remains a major composition hotspot.

It contains:

extensive imports from application/domain/infrastructure layers;
environment/backend selection;
concrete repository creation;
application-service wiring;
argument parsing;
serialization;
CLI error handling;
command implementations.
This does not destroy the architecture—the business rules still live elsewhere—but it makes the CLI interface layer increasingly expensive to maintain.

Recommended refactor
Introduce a reusable composition root, for example:

text

src/tarkka/runtime/
    config.py
    container.py
    repositories.py
    services.py
Conceptually:

python

runtime = TarkkaRuntime.from_environment()
service = runtime.documents()
result = service.manifest(document_id)
Then:

CLI parses and renders;
MCP parses and renders;
HTTP parses and renders;
Python consumers can call the same runtime/app services;
backend selection happens once.
This would materially help the open transport-unification work.

14. MCP and Agent Interface
14.1 One of Tarkka's clearest innovations
The agent interface is not "give the model a search endpoint."

It explicitly treats context as a budgeted resource:

text

capabilities
  -> manifest
  -> receipt/summary
  -> evidence
  -> section
  -> full document
  -> raw artifact
This is good for:

token cost;
latency;
privacy;
rights enforcement;
auditability;
agent discipline.
14.2 Strong operational semantics
The MCP design includes:

compact capability discovery;
schema-on-demand;
stable IDs;
server-side limits;
structured errors;
content_too_large rather than silent truncation;
read-only/idempotent operations by default;
no filesystem path exposure;
opt-in telemetry with no source text/request arguments.
This is substantially better than exposing a raw vector search tool.

14.3 Remaining issue
MCP is currently more mature than HTTP parity.

The project needs to avoid ending up with:

text

CLI semantics A
MCP semantics B
HTTP semantics C
The open interface-unification issue is therefore high priority.

15. HTTP / API Surface
The architecture correctly says CLI, HTTP, MCP, and Python should share application services.

The repository already has groundwork for this, but the HTTP /v1 surface is not yet as complete as the CLI/MCP capabilities.

Recommendation
Do not build a second application architecture for HTTP.

Instead define transport-neutral:

text

Operation request DTO
Application service
Operation result DTO
Problem/error envelope
Then adapt it to:

text

CLI
MCP
HTTP/OpenAPI
Python
A good acceptance test is:

The same fixture and operation produce semantically equivalent results through at least two transports.

16. Persistence and PostgreSQL
16.1 Strengths
The project has a meaningful migration sequence covering major concepts such as:

core records,
acquisition,
discovery,
work identity,
structured extraction,
generalized evidence,
citations,
external IDs,
evidence relations,
source observations,
context packages,
work/document links,
retrieval embeddings.
This indicates PostgreSQL is a real reference implementation rather than a README promise.

16.2 JSON default is strategically useful
Keeping a dependency-free local JSON profile is valuable because it supports:

five-minute demo;
offline proof/replay;
local experimentation;
deterministic tests;
simple user adoption.
16.3 Cost: dual persistence surface
Every durable capability may eventually need:

text

JSON implementation
PostgreSQL implementation
shared contract tests
migration/version compatibility
That is a real maintenance multiplier.

Recommendation
Create an explicit persistence policy:

Tier A — core durable contracts: must support JSON + PostgreSQL.

Tier B — experimental derived features: may start JSON/local only until contract stabilizes.

Tier C — caches/ephemeral projections: need not become canonical persistence APIs.

This will prevent database parity from becoming automatic overhead for every experiment.

17. Artifact Storage
Content-addressed storage is exactly the right model.

A stable SHA-256 identity provides:

deduplication;
reproducibility;
integrity;
change detection;
portable proof references.
The architecture correctly keeps blobs outside ordinary relational rows and treats S3-compatible storage as a future port rather than a mandatory dependency.

Recommendation
Do not add S3 merely because the port exists.

Add it when one of these becomes true:

local artifact volume becomes operationally painful;
multi-worker deployment needs shared artifacts;
real users need object lifecycle/storage policies;
measurements show local storage is the bottleneck.
18. Security and Rights
18.1 Security thinking is unusually strong
The security model explicitly considers:

SSRF;
DNS/network boundary risks;
malicious redirects;
oversized downloads;
decompression bombs;
unexpected content types;
local-network access;
credential leakage;
path traversal;
untrusted documents;
parser isolation;
prompt injection;
model data egress;
rights and redistribution.
The distinction between these questions is particularly good:

text

May access?
May fetch?
May store?
May transform?
May display snippets?
May redistribute?
May use commercially?
May send to a model?
One generic license field would be insufficient.

18.2 Repository security automation is strong
The project also uses or documents:

secret scanning;
push protection;
Dependabot security updates;
CodeQL default setup;
dependency review;
immutable Action SHA pins;
zizmor workflow auditing;
read-only default workflow permissions.
18.3 Institutional readiness is intentionally incomplete
The project correctly does not claim mature multi-tenant/institutional security yet.

Missing or future areas include:

authn/authz;
tenant isolation;
SSO/OIDC;
row-level security evaluation;
secret management;
backup/restore validation;
audit integrity;
vulnerability disclosure process;
hardened parser workers;
production deployment guidance.
This is not a flaw at the current stage as long as positioning remains honest.

19. Testing Strategy
19.1 This is one of the repository's standout strengths
Tarkka uses multiple complementary test classes:

unit;
contract;
integration;
regression;
property-based;
security;
failure injection;
PostgreSQL integration;
external/opt-in;
mutation testing.
That is a much stronger model than relying on line coverage alone.

19.2 Coverage
The deterministic tarkka + scripts test surface is maintained at 100% statement and branch coverage according to the project testing policy.

CI additionally protects:

changed lines;
cumulative recent ranges;
high-risk subsystem ratchets.
This is unusually rigorous.

19.3 Excellent testing philosophy
The documentation explicitly says:

coverage is a gate and diagnostic, not a substitute for meaningful assertions.

It also explicitly rejects:

meaningless assertions;
pragma: no cover padding;
artificial branches used only to satisfy coverage.
That is important.

19.4 Risk: 100% can become organizational gravity
Even with good intentions, a repository-wide 100% branch requirement has costs:

every defensive branch becomes expensive;
trivial CLI wiring can require disproportionate tests;
contributors may optimize implementation shape around testability;
refactors can become more expensive;
development velocity can shift toward coverage maintenance.
Tarkka mitigates this with contracts, properties, mutation tests, and failure injection, but this should still be watched.

Recommendation
Do not lower the quality bar now.

Instead track whether the gate is causing unhealthy behavior.

Useful metrics:

time from implementation complete to test-gate complete;
tests added per production line;
mutation score/meaningful survivor count;
flaky failure rate;
review findings that passed coverage;
CI minutes per PR.
If 100% stops correlating with higher confidence, reevaluate the mechanism—not the commitment to quality.

20. Mutation and Property Testing
The project deserves credit for not pretending coverage proves correctness.

Targeted mutation testing is a strong complement.

The current mutation campaign is deliberately scoped to deterministic logic rather than indiscriminately mutating the whole repository.

That is the correct strategy.

Recommendation
Gradually expand mutation testing around especially important pure contracts:

identifier normalization;
proof manifest validation;
evidence span invariants;
rights/policy decisions;
deterministic bundle identity;
backend-independent serialization;
citation resolution rules.
Avoid trying to optimize a global mutation score.

21. CI/CD Review
21.1 Strengths
The main CI pipeline includes:

frozen uv environment;
lockfile verification;
Ruff;
strict mypy;
SQLFluff;
GitHub Actions security audit;
Python 3.11/3.12/3.13 matrix;
branch coverage;
full coverage gate;
changed-line coverage;
subsystem ratchets;
retained JUnit/coverage artifacts.
Additional workflows cover:

package builds;
dependency review;
Docling integration;
PostgreSQL repositories;
parser coverage;
security regressions;
mutation testing;
AI review.
Recent PR-head workflow runs were green across the primary CI/package/integration/review workflows.

This is excellent repository engineering.

21.2 Risk: CI configuration complexity
The main workflow contains many repeated coverage report --include=... --fail-under=100 sections.

Some have already been moved to manifest files, but many remain inline.

This creates:

workflow maintenance cost;
merge conflicts;
difficulty understanding which modules are ratcheted;
duplication between policy docs and YAML.
Recommendation
Centralize coverage policy:

text

.github/coverage/ratchets.toml
or
.github/coverage/*.txt
Then one tested script can:

bash

Run

$
python scripts/check_coverage_ratchets.py
and report all failures with subsystem names.

The script itself can remain coverage-protected.

This reduces YAML while keeping the exact same guarantees.

22. Dependency and Packaging Strategy
22.1 Excellent minimal-core policy
The base project currently has effectively no mandatory runtime dependencies.

Optional capabilities are separated:

PostgreSQL;
Docling;
MCP;
embeddings.
This makes the core:

easier to audit;
easier to install;
less vulnerable to transitive dependency churn;
more portable.
22.2 Good dependency governance
The repository:

uses uv;
pins compatible ranges;
separates dev dependencies;
prohibits hand-editing uv.lock;
uses Dependabot;
validates dependency changes;
installs built artifacts in clean environments.
This is strong.

22.3 Gap: public release policy
The package is still version 0.1.0, and the repository automation document says the public release/PyPI policy is not finalized.

That is now a meaningful adoption blocker.

Recommendation
Make a deliberate release decision soon.

A reasonable initial release:

text

0.1.0a1 or 0.1.0
with an explicit compatibility statement:

domain contracts under active evolution;
bundle schemas versioned independently;
no guarantee of CLI stability until 0.2/0.3;
proof-bundle verification compatibility documented;
experimental extras labeled.
A real install path dramatically improves external testing.

23. GitHub Development Workflow
23.1 Spec-driven workflow is excellent
AGENTS.md establishes a disciplined sequence:

text

issue/spec
  -> bounded implementation
  -> tests
  -> PR
  -> automated review
  -> deterministic CI
  -> review disposition
  -> merge
Material changes require the issue to state:

problem/outcome;
in scope;
out of scope;
invariants;
acceptance tests;
dependencies;
successor work.
This is a very strong development contract.

23.2 Recent PR quality
Recent pull requests are generally:

narrow;
explicit;
test-backed;
honest about non-goals;
tied to issues;
explicit about follow-up work.
That is a healthy pattern.

23.3 AI-assisted workflow
The repository has embraced coding/review agents in a disciplined way rather than allowing them to become authority.

The workflow uses:

shared AGENTS.md;
tool-specific extensions;
PR-Agent;
OpenCode Zen;
explicit review triage;
deterministic CI as the source of truth.
The security design for the AI reviewer is particularly good: secret-bearing jobs do not execute untrusted PR-head code.

23.4 Risk: review automation can become noise
With multiple AI reviewers, humans/agents can spend time dispositioning duplicate or shallow findings.

The automation document already recognizes this risk.

Recommendation
Measure reviewer usefulness:

text

valid findings / total findings
unique valid findings / reviewer
security/correctness findings
duplicate rate
time spent triaging
Remove a reviewer if it does not contribute distinct signal.

24. Documentation Review
24.1 Major strength
The documentation is not superficial.

There are durable documents for:

architecture;
canonical model;
source preservation;
artifact composition;
proof bundles;
citation behavior;
testing;
security/rights;
agent interfaces;
evaluation;
library/encyclopedia;
interoperability.
This is extremely helpful for a project driven partly by coding agents.

24.2 Important problem: documentation drift
The repository is moving fast enough that several documents no longer perfectly match reality.

Concrete examples:

PROJECT_CHARTER.md
It still says:

Thoth is the current repository name and final naming is unresolved.

That is obsolete; the repository/package/product is Tarkka.

The same document still contains language suggesting a software license must be selected, while the project is now Apache-2.0.

ROADMAP.md
Some Phase 5 deliverables are listed as future deliverables even though the preceding "delivered foundation" already includes them, such as the MCP server.

GitHub issues
Several parent or implementation issues remain open even though significant portions of their scope have already landed.

This is understandable in a fast project, but it weakens GitHub's role as the canonical status source.

24.3 Recommendation: add documentation consistency checks
Do not attempt to test prose in general.

Instead test a few important machine-verifiable facts:

text

project name = Tarkka
package name = tarkka
license = Apache-2.0
current bundle schema versions
supported Python versions
current CLI command inventory
current MCP operation inventory
current provider inventory
Generate selected reference sections where feasible.

Also add a small:

text

docs/STATUS.md
only if generated from authoritative data, not as another manually maintained journal.

For example:

text

python scripts/generate_status.py
could read:

pyproject.toml;
command registry;
capability registry;
migrations;
release version;
tagged roadmap metadata.
The project correctly avoids duplicate handoff journals. Generated status is different: it eliminates drift rather than adding another source of truth.

25. Evaluation and Scientific Validation
25.1 Positive change
Tarkka now has a real tarkka eval workflow and has published a real result rather than merely claiming reproducibility.

The first published corpus result successfully processed two pinned Project Gutenberg representations of Frankenstein:

EPUB;
semantic HTML.
Both were:

hash verified;
ingested using the expected parser;
bundled;
independently verified;
replayed to an exact content match.
This is a real milestone.

25.2 But the corpus is intentionally tiny
The project documentation correctly states that this is a smoke test, not broad evidence of extraction/retrieval/verification quality.

This is currently the largest strategic gap.

Current empirical ladder
text

Internal deterministic tests       ██████████  very mature
Contract/conformance testing       ██████████  very mature
Security regression testing        █████████   mature
Real-world parser smoke testing    ████         early
Retrieval relevance evaluation     ███          very small
Claim extraction benchmark         ██           limited/publicly immature
Verification benchmark             ██           limited/publicly immature
Performance benchmark              ██           incomplete
Cross-domain validation            █            future
User adoption evidence             █            future
25.3 Recommended public evaluation suite
Build a rights-clean corpus with roughly:

20–50 documents initially;
multiple formats;
multiple domains;
reviewed gold annotations.
Suggested categories:

Ingestion/replay
HTML
EPUB
JATS
Markdown
PDF/Docling
LaTeX
malformed edge cases
Identity/citations
DOI-normalized duplicates
arXiv versions
ambiguous title/author duplicates
resolvable references
intentionally unresolved references
Extraction
100–300 reviewed claims
methods
variables
metrics
results
limitations
Evidence verification
supports
contradicts
qualifies
unrelated
insufficient evidence
Retrieval
exact lookup
paraphrase
concept search
negative/no-answer
hard negatives
cross-format same-work search
Reproducibility
exact replay
deliberate corruption
version mismatch
stale projection
changed source
This corpus would be one of Tarkka's most valuable public assets.

26. Performance Review
The repository is very strong at correctness contracts but less mature at end-to-end performance measurement.

That is appropriate so far, but the next stage should make performance observable.

Measure at least:

text

ingestion:
  documents/sec
  MB/sec
  peak RSS
  time by parser

normalization:
  passages/sec
  sections/sec

retrieval:
  indexing time
  index size
  P50/P95 query latency
  memory
  relevance metrics

proof:
  bundle creation time
  bundle size
  verify time
  replay time

PostgreSQL:
  insert throughput
  indexed read latency
  connection overhead
  migration duration

MCP:
  operation latency
  response bytes
  estimated tokens
Recommendation
Add a non-blocking benchmark suite first.

Do not make benchmarks merge gates until variance and baseline stability are understood.

27. Observability
Tarkka's telemetry design is privacy-conscious, which is a strength.

MCP telemetry records only aggregate operation information rather than research content.

However, broader application observability is still developing.

Recommended future model
Use structured events like:

json

{
  "event": "document.ingest.complete",
  "document_id": "...",
  "parser": "jats",
  "duration_ms": 182,
  "artifact_bytes": 421233,
  "sections": 18,
  "passages": 202,
  "outcome": "success"
}
but continue avoiding:

raw document text;
secret-bearing URLs;
model prompts unless explicitly retained as provenance in a controlled store;
credentials.
OpenTelemetry could eventually be an adapter, not a core requirement.

28. Scalability Review
28.1 Design is sensible
The planned scale path is appropriately conservative:

text

local JSON
    ↓
PostgreSQL metadata
    ↓
pgvector if measured useful
    ↓
S3-compatible artifact port when shared workers need it
    ↓
durable job workers when workloads justify it
This is much better than prematurely introducing:

Kafka;
Kubernetes;
Neo4j;
Qdrant;
Redis queues;
distributed orchestration.
28.2 Risk
The architecture contains many scale-ready contracts before the project has significant user scale.

That is acceptable only while those contracts remain lightweight.

Recommendation
Use a "measurement trigger" for every infrastructure product.

Example:




Infrastructure	Add when
pgvector	vector evaluation demonstrates value and corpus size needs DB search
S3/R2	multiple workers/machines need shared artifacts
queue	in-process/local job execution becomes blocking or unreliable
graph DB	relational traversal becomes a measured bottleneck
Kubernetes	operational workload requires horizontal scheduling
Redis	a concrete latency/coordination use case exists
29. Code Organization and Maintainability
29.1 Strengths
The code generally exhibits:

small domain modules;
explicit protocols;
narrow adapters;
typed interfaces;
defensive validation;
deterministic identities;
testable service boundaries.
29.2 Emerging hotspot: application proliferation
Some vertical features now have multiple neighboring modules, e.g. lineage/service/protocol/view/contract variants.

This is often justified, but the repository should periodically ask:

Does this separation improve replaceability/testability, or are we decomposing names faster than behaviors?

Recommendation
Establish a module consolidation heuristic.

Merge adjacent modules when:

they always change together;
they have one implementation;
no independent port/consumer exists;
the abstraction exists only to preserve naming symmetry.
Keep them separate when:

one is a stable public contract;
multiple implementations exist;
transport-neutrality materially depends on it;
testing benefits from the boundary.
30. Workflow Progress Review
The project has made substantial progress through the original roadmap.

Phase 0 — Foundation
Status: essentially complete

Strong deliverables include:

charter;
architecture;
canonical data model;
rights/security principles;
plugin contracts;
agent interfaces;
shared coding-agent guidance;
testing standards.
Audit note
The content is complete enough; documentation reconciliation is now more important than adding more architecture documents.

Phase 1 — Core local vertical slice
Status: substantially complete

Working:

local content-addressed artifacts;
provenance;
normalized documents;
parsing;
local metadata;
Postgres foundation;
CLI ingestion/inspection;
Docling optional integration.
Remaining work should be driven by later features, not by abstract completeness.

Phase 2 — Discovery and identity
Status: strong

Provider-neutral discovery and canonical work identity are well established.

Main future areas:

additional sources only when justified;
enrichment policies;
better reconciliation workflows;
provider health/cost decisions only if measured.
Phase 3 — Structured extraction
Status: strong foundation

The research-object model and evidence contracts are significantly developed.

The next priority should be empirical evaluation and real-domain validation rather than simply adding more object types.

Phase 4 — Evidence verification
Status: strong initial workflow

The project now has meaningful support/contradiction/qualification mechanics.

This is a differentiating area worth polishing into user-facing workflows.

Phase 5 — Agent-first serving
Status: functional foundation, ongoing productization

MCP, capability discovery, context packages, token budgets, comparison, and lexical retrieval already exist.

Main priorities:

compact stable verbs;
transport parity;
better examples;
context-wallet UX;
benchmark token savings.
Phase 6 — Reproducible outputs
Status: partially emerging ahead of schedule

Proof bundles and RO-Crate export already cover part of the interoperability/output space.

Remaining output areas include richer reporting and bibliography/export workflows.

Phase 7 — Baseball domain pack
Status: not yet the focus

This should become strategically important soon because it can prove that Tarkka solves real research work rather than only generic infrastructure problems.

The MLB project is an ideal proving ground for:

paper discovery;
method extraction;
evidence review;
paper-to-feature mapping;
temporal leakage checks;
implementation handoff.
31. Recent Development Momentum
Recent merged work shows very high development velocity.

Notable recent slices include:

challenge and contradiction board;
deterministic encyclopedia compile;
durable library catalog;
scale-ready compile jobs and quotas;
workspace-scoped lexical index jobs;
embedding indexing;
vector retrieval candidates;
reciprocal-rank hybrid fusion;
retrieval evaluation;
staged real-world corpus execution;
local sentence-transformer baseline;
compact research comparison;
MCP client documentation;
public tarkka eval;
first real published evaluation result;
external adapter conformance example;
dependency/security automation reconciliation;
RO-Crate export.
This is a huge amount of coherent progress.

Risk of this velocity
High PR velocity can produce:

stale parent issues;
documentation mismatch;
overlapping abstractions;
insufficient time for user feedback;
a bias toward "next issue" rather than "use what we just built."
Recommendation
Introduce periodic consolidation milestones.

For every ~10–15 feature PRs, spend one cycle on only:

using the product end to end;
deleting duplication;
updating docs;
closing/reconciling issues;
measuring runtime;
simplifying commands;
improving examples.
32. Biggest Strengths
32.1 Trust is architectural, not cosmetic
This is the single biggest strength.

Tarkka's trust model is woven through:

storage;
extraction;
citations;
retrieval;
agent serving;
bundles;
rights;
evaluation.
32.2 Excellent separation of source vs interpretation
This is essential for research integrity and unusual among AI-first projects.

32.3 Model independence
Core operation does not require an LLM.

That improves:

reproducibility;
privacy;
cost;
longevity;
scientific defensibility.
32.4 Content-addressed artifacts and deterministic replay
These capabilities make Tarkka suitable for durable research workflows instead of ephemeral conversations.

32.5 Agent context efficiency
Progressive disclosure is both technically practical and strategically differentiated.

32.6 Testing culture
The repository does not merely have tests; it has a coherent quality philosophy.

32.7 Security awareness
Network, document, prompt, rights, and supply-chain boundaries are considered early.

32.8 Dependency discipline
The minimal core and optional integrations reduce coupling.

32.9 Honest benchmarking
The project records when a vector baseline performs worse rather than rationalizing it away.

32.10 Strong extension story
Protocols + conformance tests + domain packs create a reasonable ecosystem path.

33. Biggest Weaknesses / Risks
33.1 Too much internal maturity relative to user validation
The project can spend another year becoming architecturally stronger without proving that external users need it.

This is now the highest strategic risk.

33.2 Public evaluation is still too small
The repository has more confidence in internal correctness than in broad real-world research quality.

33.3 CLI/product complexity
There are many commands, IDs, nouns, derivation versions, fingerprints, backends, and object types.

Expert power is strong; newcomer simplicity is not yet equally strong.

33.4 Status/document drift
Fast development has already caused stale naming/license/roadmap/issue state.

33.5 Interface fragmentation risk
CLI/MCP/HTTP must converge on common DTOs/problems/application operations before they grow further.

33.6 Dual persistence cost
JSON + PostgreSQL is valuable but expensive to maintain if every experimental feature immediately requires both.

33.7 CI complexity
Quality is excellent, but the workflow itself is becoming another large software artifact.

33.8 Architecture can outpace necessity
Graph, similarity, web extraction, scale, and institutional layers all make sense—but each can distract from the core wedge.

33.9 No clear release/adoption channel yet
Without a public package/release policy, external testing is unnecessarily difficult.

33.10 Performance evidence is limited
Correctness is measured far more deeply than throughput, latency, memory, and large-corpus behavior.

34. Recommended Priority Roadmap
P0 — Do now
1. Reconcile canonical project status
Update stale durable documents and issue bodies.

At minimum:

fix PROJECT_CHARTER.md Thoth naming text;
remove outdated unresolved-license language;
reconcile Phase 5 delivered/future items;
update parent issue checklists;
close or explicitly rescope completed issues.
This is low-risk, high-value work.

2. Freeze a v1 golden path
Create one canonical end-to-end workflow that is the public face of Tarkka:

text

install
  -> init workspace
  -> ingest/discover
  -> extract claims
  -> inspect receipt
  -> challenge
  -> create proof bundle
  -> verify/replay
  -> connect agent
Every command in this path should have:

predictable defaults;
concise help;
copy/paste docs;
fixture-backed acceptance test.
3. Expand the public evaluation corpus
This is the most important technical/product investment now.

Target:

20–50 documents;
several formats;
50–100+ retrieval queries;
reviewed claims/evidence;
identity/citation edge cases.
Publish results per release.

4. Finalize release policy
Decide:

PyPI or GitHub Releases first;
versioning;
compatibility promises;
prerelease policy;
trusted publishing;
release notes.
Then automate it.

5. Extract the runtime composition root
Reduce interfaces/main.py coupling by creating one reusable environment/runtime container.

This will make CLI/MCP/HTTP convergence easier.

P1 — Next
6. Complete compact agent verb semantics
Converge around:

text

research.search
research.get
research.expand
research.compare
research.verify
research.export
Keep compatibility aliases as necessary.

7. Unify transport contracts
Implement one representative operation through:

CLI;
MCP;
HTTP;
using the same request/result/problem semantics and contract tests.

Then generalize.

8. Add benchmark infrastructure
Add reproducible non-blocking performance reports for:

ingestion;
retrieval;
proof bundles;
PostgreSQL;
MCP.
9. Build the Baseball domain pack as the first serious proving domain
This is strategically valuable.

Use real baseball-research questions to test:

discovery;
extraction;
claim/evidence quality;
method mapping;
leakage detection;
research-to-code handoff.
The domain pack should expose where generic contracts are truly missing.

10. Extend RO-Crate/provenance interoperability carefully
The current RO-Crate slice is intentionally limited.

Next useful interoperability work would likely include:

text

Artifact
Document
Claim
Evidence
Citation
Verification
derivation/provenance
Do not add more standards solely for checkbox coverage.

P2 — After evidence justifies it
11. Web extraction adapters
Benchmark Trafilatura/Crawl4AI/etc. before selecting defaults.

12. pgvector adapter/default decision
Only after a larger retrieval benchmark demonstrates value.

13. Similarity/consensus
Useful, but keep candidate-generation separate from truth/identity decisions.

14. Graph projection service
Use relational projections first; graph database later only when measured.

15. S3 and distributed workers
Only after local/Postgres workflows demonstrate actual scale pain.

16. Institutional auth/tenancy
Only after single-user/team workflows are solid and there is demand.

35. Suggested Next 10 PRs
If I were sequencing the project from the current point, I would prefer something close to:

docs: reconcile charter/roadmap/open issue status
refactor: extract shared runtime/service composition from CLI
eval: expand corpus manifest and evaluation schema
eval: add 25–50 reviewed retrieval queries
eval: add first reviewed claim/evidence benchmark
release: define versioning/publication policy
ci: add tag-driven release build + trusted publication when approved
interface: prove one CLI/MCP/HTTP operation contract end-to-end
domain-baseball: minimal source catalog + research vocabulary + one real workflow
benchmark: publish parser/retrieval/proof runtime measurements
This sequence intentionally spends less time adding abstractions and more time making the existing architecture measurable and usable.

36. What I Would Not Add Yet
I would actively avoid adding the following unless a measured need appears:

Neo4j or another graph database;
Qdrant/Weaviate as a second vector system;
Redis solely because distributed systems often use Redis;
Kafka;
Kubernetes deployment complexity;
a first-party chat UI;
autonomous multi-agent orchestration inside the core;
mandatory LLM extraction;
automatic claim merging;
automatic fuzzy work merging;
universal evidence/truth score;
dozens of new scholarly providers before current workflows are polished.
Tarkka's restraint is part of what makes it good. Preserve that.

37. Specific Technical Improvements
37.1 Runtime/composition
Create a common runtime:

python

@dataclass(frozen=True)
class TarkkaRuntime:
    settings: TarkkaSettings
    documents: ResearchRepository
    works: WorkRepository
    artifacts: ArtifactStore
    extractions: ExtractionRepository
    verifications: VerificationRepository
    ...
Construct once from explicit configuration.

Avoid a service locator that hides dependencies; expose typed factories/services.

37.2 Typed configuration
Consolidate environment parsing into one validated configuration layer.

Goals:

no scattered environment reads;
typed backend enums;
deterministic defaults;
redacted diagnostic rendering;
easy test construction.
37.3 Stable problem model
Create transport-neutral errors:

python

@dataclass(frozen=True)
class Problem:
    code: ProblemCode
    message: str
    recoverable: bool
    next_actions: tuple[str, ...] = ()
Then render through CLI/MCP/HTTP.

37.4 Differential backend tests
For canonical objects, run the same behavioral sequence against:

text

JSON backend
PostgreSQL backend
and compare canonical serialized results.

This gives stronger protection than independent unit coverage.

37.5 Generated interface inventory
Automatically emit:

CLI command tree;
capability IDs;
MCP tools;
HTTP routes;
optional features.
Use it both for docs and interface-drift testing.

37.6 CI ratchet registry
Replace much of the repeated YAML with data:

toml

[[ratchet]]
name = "core-domain"
minimum = 100
paths = [
  "src/tarkka/domain/identifiers.py",
  ...
]
One script validates all ratchets.

37.7 Public benchmark output
Add a structured benchmark artifact:

json

{
  "tarkka_version": "...",
  "commit": "...",
  "suite": "retrieval-v1",
  "corpus_digest": "...",
  "metrics": {...},
  "environment": {...}
}
This can later support version-to-version regressions.

38. Product and Adoption Improvements
Technical quality is no longer enough by itself.

38.1 Homepage/README should answer three questions immediately
What does Tarkka do?
Tarkka stores research in a form humans and AI agents can independently inspect, challenge, verify, and replay.

Why not use ordinary RAG?
RAG retrieves text. Tarkka preserves the chain from source to claim to evidence to verification.

What can I prove in five minutes?
Show one command sequence and its visible outputs.

38.2 Provide opinionated recipes
The project should have several fully runnable recipes:

Verify a claim
Build a reproducible literature brief
Give Claude/Codex a bounded evidence backend
Research an MLB modeling question
Compare two conflicting papers
Audit a research result from a proof bundle
Recipes are more valuable to users than another conceptual architecture page.

38.3 Provide a Python API golden path
Even if the CLI remains primary, researchers will want:

python

from tarkka import Tarkka

t = Tarkka.local()
doc = t.ingest("paper.pdf")
claims = t.claims.extract(doc)
receipt = t.claims.receipt(claims[0])
The actual API can differ, but the ergonomic goal matters.

Do not force Python users to assemble repositories/services manually.

39. Commercial / Ecosystem Potential
Tarkka has plausible value beyond an open-source hobby project.

Potential users include:

AI agent platforms needing auditable source state;
scientific/research teams;
financial research;
policy research;
legal research;
enterprise knowledge systems;
academic reproducibility tooling;
model-evaluation/research pipelines.
Potential commercial layers, without compromising the open core:

managed Tarkka hosting;
institutional connectors;
governed/private model routing;
team review workflows;
hosted artifact storage;
compliance/audit exports;
managed ingestion workers;
premium domain packs or data connectors;
enterprise SSO/RBAC/audit retention.
However, commercialization should follow evidence that people value the core trust layer.

40. Final Verdict
Tarkka is in a very good position.

It is not suffering from the problems that usually kill ambitious AI infrastructure projects:

the core is not tied to one LLM;
it is not built around one vector database;
it is not pretending embeddings are truth;
it is not hiding source provenance;
it is not making a chat UI the architecture;
it is not prematurely introducing a graph database;
it is not treating citations as evidence;
it is not ignoring rights/security;
it is not using AI review as a substitute for tests.
Those are major accomplishments.

The project now needs a deliberate shift in emphasis.

The next stage should be:
text

less:
    "What additional architecture can Tarkka support?"

more:
    "Can another researcher install Tarkka,
     use it on real research,
     trust its results,
     reproduce them,
     and immediately understand why it is better
     than ordinary RAG?"
The architecture already gives Tarkka a credible answer.

The work now is to make that answer obvious, measurable, and easy to adopt.

41. Recommended Immediate Actions
Reconcile docs/issues with current reality.
Freeze and polish one canonical v1 workflow.
Expand the public evaluation corpus substantially.
Finalize and automate the public release policy.
Refactor interface runtime composition before HTTP/MCP/CLI grow further.
Measure performance and context efficiency.
Use the Baseball domain pack as the first serious real-world proof.
Keep vectors, graph systems, queues, and distributed infrastructure evidence-driven.
Continue the current provenance/security/testing discipline.
Schedule recurring consolidation cycles so development velocity does not produce conceptual or documentation debt.
Appendix A — Notable Repository Evidence Reviewed
Key project documents:

README.md
AGENTS.md
docs/PROJECT_CHARTER.md
docs/ARCHITECTURE.md
docs/ROADMAP.md
docs/TESTING.md
docs/SECURITY_PRIVACY_LICENSING.md
docs/AGENT_INTERFACE.md
docs/RESEARCH_LIBRARY_AND_ENCYCLOPEDIA.md
docs/EVALUATION_RESULTS.md
.github/WORKFLOW_AUTOMATION.md
.github/workflows/ci.yml
pyproject.toml
Key implementation areas:

src/tarkka/domain/
src/tarkka/application/
src/tarkka/ports/
src/tarkka/infrastructure/
src/tarkka/interfaces/
src/tarkka/evaluation/
src/tarkka/conformance/
migrations/
tests/
Recent work reviewed includes PRs in the areas of:

proof bundles / RO-Crate;
evaluation;
conformance;
agent comparison;
retrieval;
vector embeddings;
hybrid ranking;
workspace/library jobs;
encyclopedia compilation;
contradiction/challenge;
CI/security automation.
Appendix B — Audit Confidence



Finding type	Confidence
Repository structure	High
Architecture and design intent	High
Current implemented user surface	High
CI/testing policy	High
Recent development progress	High
Performance/scalability	Medium — broad benchmarks are not yet published
Scientific extraction quality	Medium/Low — public evaluation is still narrow
Production institutional readiness	Medium — architecture is documented, deployment evidence is incomplete
External user adoption	Low/unknown — repository evidence does not yet establish meaningful adoption
Appendix C — One-Sentence Strategic Summary
Tarkka should stop proving that its architecture can support trustworthy research and start proving—on larger real corpora and real users—that trustworthy, replayable research is valuable enough to make Tarkka indispensable.
