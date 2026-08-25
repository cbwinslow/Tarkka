# Context Efficiency and Progressive Disclosure

## Purpose

AI agents should not pay the context cost of information they do not need. This project treats token/context efficiency as an architectural property, not a prompt-writing trick.

The core rule is:

> Retrieve conclusions cheaply, retrieve evidence precisely, retrieve full source material only when necessary.

## Progressive disclosure ladder

Every major research object should support progressively richer representations.

### Level 0 — capability index

A tiny catalog describing available tools, collections, object types, and approximate result cost.

Agents should be able to discover capabilities without loading complete tool schemas or domain documentation.

### Level 1 — manifest

Compact metadata suitable for ranking and routing.

Example:

```yaml
id: work:01J...
type: work
title: Pitcher fatigue and performance
published: 2024
source_type: journal_article
peer_reviewed: true
claims: 7
methods: 2
has_full_text: true
summary_tokens: 180
full_text_tokens_estimate: 12400
```

### Level 2 — summary

A concise structured summary containing only normalized high-value fields.

### Level 3 — evidence package

Relevant claims, methods, results, and source passages required to answer a specific question.

### Level 4 — section/document detail

Load complete sections or full normalized documents only when the task actually requires them.

### Level 5 — original artifact

Raw PDF/HTML/data is the final fallback for visual, forensic, or reproduction needs.

## Sequential tool discovery

Do not expose every provider, operation, and JSON schema to the model on every turn.

Preferred pattern:

```text
list_capabilities
    ↓
select capability family
    ↓
list_operations(family)
    ↓
get_operation_schema(operation)
    ↓
execute
```

For MCP, where practical, prefer a small stable top-level tool set whose arguments support staged discovery rather than hundreds of always-visible tools.

Candidate top-level surface:

```text
research.discover
research.search
research.get
research.expand
research.compare
research.sync
research.export
```

Detailed capability descriptors can be resources or compact manifests loaded only when requested.

## YAML/frontmatter

YAML frontmatter is useful for compact, machine-readable routing metadata while preserving human-readable Markdown bodies.

Use it for:

- Agent Skills
- domain packs
- extraction contracts
- research manifests
- report definitions
- source/provider descriptors where static configuration is appropriate

Example skill:

```markdown
---
name: evidence-comparison
description: Compare claims and contradictory evidence across works.
when:
  - user asks what research agrees or disagrees
requires:
  - research.search
  - research.expand
load:
  first: references/decision-tree.md
  on_demand:
    - references/quality-policy.md
    - references/claim-verification.md
---

# Evidence comparison

Start with claim manifests. Do not retrieve source passages until candidate claims are ranked.
```

The frontmatter is not itself a compression algorithm. Its value is that routing metadata can be parsed without loading the long body.

## Skill structure

Skills should use progressive disclosure themselves.

```text
skills/evidence-comparison/
  SKILL.md                 # compact routing/workflow
  references/
    decision-tree.md       # loaded when workflow starts
    quality-policy.md      # loaded only if quality comparison matters
    verification.md        # loaded only if verification is requested
  scripts/
    ...                    # deterministic helpers
```

A `SKILL.md` should not become a 20,000-token textbook.

## Context manifests

When returning a result set to an agent, include an explicit context budget description.

Example:

```yaml
result_count: 42
returned: 10
representation: manifest
estimated_tokens: 620
expansions:
  - summary
  - claims
  - methods
  - evidence
  - full_document
next_cursor: ...
```

This lets an agent make a rational decision about whether to expand.

## Query planning

Retrieval should be staged:

1. clarify/normalize intent when necessary
2. search metadata/lexical/vector indexes cheaply
3. rank candidate works/claims
4. return manifests
5. expand the best candidates
6. retrieve passages only for claims being used
7. verify evidence for high-stakes outputs

Avoid retrieving top-k chunks from the entire corpus before candidate work selection when richer metadata is available.

## Hierarchical summaries

Maintain reusable summaries at multiple levels:

```text
corpus
  topic
    work
      section
        passage
```

Summaries are cached derived objects with versioned provenance. They can be refreshed when underlying objects or synthesis contracts change.

## Delta retrieval

Agents operating repeatedly on a workspace should be able to ask for changes since a snapshot/version.

Example:

```text
research.diff(snapshot_a, snapshot_b)
```

Return only:

- new works
- changed metadata
- new/retracted/corrected findings
- new claim relationships
- changed synthesis

This prevents repeated replay of stable research state.

## Stable handles instead of repeated payloads

Return durable IDs/handles that agents can reference later:

```text
work:...
claim:...
evidence:...
collection:...
context_package:...
```

An agent can then say "expand evidence for claim X" rather than resending prior text.

## Context packages

The server may assemble purpose-specific packages:

- `answer_question`
- `compare_methods`
- `implement_method`
- `verify_claim`
- `write_report`

A package contains only the objects needed for that task and a manifest explaining omissions and expansion paths.

The initial document-package implementation requires caller-selected, distinct section
handles and enforces both a section-count limit and an 8,000-token deterministic
content estimate. Callers must split larger selections into multiple packages rather
than receiving an unexpectedly large response.

When the caller passes `--save`, Tarkka stores only the immutable document handle,
ordered section handles, creation time, and original estimate. The returned
`context_package:<uuid>` can later be resolved without resending the selection or
duplicating source passages.

## Deterministic compression before LLM compression

Prefer cheap structural reduction first:

- remove duplicate metadata
- canonicalize identifiers
- select relevant fields
- collapse repeated citations
- select relevant sections
- filter by time/domain/method
- summarize tables structurally

Only then use LLM summarization.

## Cost telemetry

Track:

- tokens/context bytes returned by endpoint/tool
- number of expansion calls
- embedding/reranking costs
- extraction/model costs
- cache hit rate
- retrieval latency
- evidence utilization rate

This enables optimization based on measurements instead of intuition.

## Safety against over-compression

Compression must not erase provenance or turn uncertainty into certainty.

A summary should retain:

- source IDs
- claim/evidence IDs
- uncertainty/verification state
- contradiction indicators
- important scope qualifiers

Agents must always have a supported path to expand back to the evidence.

## Design target

For common agent questions, the first useful response from the research backend should usually be measured in hundreds to a few thousand tokens, not tens or hundreds of thousands. Full documents are available but are not the default unit of interaction.
