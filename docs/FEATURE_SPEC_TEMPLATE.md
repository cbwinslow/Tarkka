# Feature Specification Template

Use this template in the canonical GitHub issue for any material capability, public contract,
persistence format, or architectural decision. The issue is the live execution record; promote only
stable decisions into durable architecture/contract documentation.

## Outcome

State the user-visible or system outcome in one paragraph. Name the affected capability rather than
an implementation class where possible.

## Scope

- In scope:
- Explicit non-goals:
- Existing contracts/docs to extend:
- Related or successor issues/PRs:

## Invariants and data handling

- What remains immutable or append-only?
- What is native, reconstructed, or inferred?
- What provenance, version, rights, identity, and idempotency information is required?
- What data must be bounded, paginated, or kept out of logs?

## Contract sketch

Describe the input, output, failure classes, ownership/lifecycle boundaries, and capability routing.
Use stable handles and typed result/error shapes. Do not commit to a provider-specific SDK unless
the issue explains its replacement boundary.

## Acceptance tests

- Normal behavior:
- Failure/policy/permission behavior:
- Preservation and provenance assertions:
- Idempotency/retry/concurrency behavior where relevant:
- User/agent discovery and documentation path:

## Dependencies and rollout

- Dependency/license/network review:
- Migration or backward-compatibility plan:
- Fixture/evaluation corpus required:
- Exact next issue if this slice intentionally leaves an extension point:

## Completion record

The linked pull request must state what changed, validation run, review dispositions, remaining
risks, and any durable document promoted from this specification.
