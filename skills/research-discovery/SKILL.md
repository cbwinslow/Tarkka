---
name: research-discovery
description: Discover and triage research efficiently before loading detailed source content.
version: 0.1.0
when:
  - user asks to find research on a topic
  - user asks what literature exists
  - user asks for papers, methods, models, or evidence
principles:
  - progressive-disclosure
  - evidence-first
  - provider-neutral
  - reproducible-search
load:
  first:
    - ../../docs/CONTEXT_EFFICIENCY.md
  on_demand:
    provider_behavior:
      - ../../docs/CONNECTOR_PLUGIN_SPEC.md
    evidence_verification:
      - ../../docs/AGENT_INTERFACE.md
    research_pipeline:
      - ../../docs/RESEARCH_PIPELINE.md
---

# Research Discovery

Use the research platform as a staged discovery system. Do not begin by loading full documents.

## Workflow

1. Normalize the user's research question and preserve meaningful constraints.
2. Inspect available discovery capabilities/providers using a compact capability manifest.
3. Execute a reproducible search strategy across the relevant configured providers.
4. Deduplicate/resolve candidates through platform services rather than manually guessing identity.
5. Return/rank **work manifests** first.
6. Expand summaries, claims, methods, or metadata only for promising candidates.
7. Retrieve source evidence only when it is needed to support an answer or downstream decision.
8. For consequential claims, request claim/evidence verification before presenting them as supported findings.
9. Preserve stable IDs so later operations can expand existing results without replaying text.

## Context rules

Prefer this order:

```text
capabilities -> manifests -> summaries -> structured findings -> evidence -> full source
```

Do not retrieve a full PDF merely because it is available.

## Research quality

Do not rank solely by citation count or model-generated quality scores. Surface observable quality information and apply the workspace/domain policy when one exists.

## Contradictions

When multiple works address the same claim, look for supporting, contradictory, qualifying, and replication evidence. Do not flatten disagreement into a single consensus statement unless the evidence justifies it.

## Output

A useful discovery response should include:

- normalized question
- search/snapshot handle when available
- compact candidate list
- why candidates are relevant
- evidence/quality state
- available expansion paths

Keep the initial payload compact enough for the consuming agent to decide what to inspect next.
