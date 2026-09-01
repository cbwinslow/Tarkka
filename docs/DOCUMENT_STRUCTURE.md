# Canonical Document Structure

## Purpose

A normalized `Document` is Tarkka's transport-neutral structural representation of one
parsed artifact. Parsers, persistence adapters, proof bundles, and replay must agree on
one structural contract rather than inventing backend-specific rules.

The canonical validator is `tarkka.domain.document_structure.validate_document_structure`.
Code that needs deterministic parent-before-child section ordering should use
`document_sections_parent_first` rather than reimplementing graph traversal.

## Hierarchy semantics

`Section.parent_section_id` is the canonical hierarchy relation.

`Section.level` is **source-native/advisory heading metadata**. It may describe an HTML
`h1`-`h6` rank, a JATS nesting level, a Markdown heading rank, or an equivalent parser
observation. Tarkka intentionally does not require:

- `child.level == parent.level + 1`;
- `child.level > parent.level`;
- `level` to equal reconstructed tree depth.

This distinction preserves source semantics. For example, semantic HTML may legitimately
jump from an `h1` to an `h3`, while LaTeX/Markdown-derived documents may preserve heading
levels without reconstructing parent links at all.

Consumers that need tree depth must derive it from `parent_section_id`; they must not infer
it from `level`.

## Canonical cross-object invariants

The following rules apply to every normalized `Document`:

1. section IDs are unique within the document;
2. section ordinals are unique within the document;
3. every non-null section parent refers to a section preserved in the same document;
4. the section parent graph is acyclic;
5. passage IDs are unique across the entire document;
6. passage ordinals are unique within their containing section.

Local dataclass invariants remain authoritative for properties that do not require a
whole-document view. Examples include:

- section/passages belonging to the same `document_id` and `section_id`;
- non-negative ordinals;
- `Section.level >= 1`;
- passage character ranges matching passage text length;
- source-artifact ownership, IDs, ordinals, and scalar metadata constraints.

The whole-document validator complements those local constructors; it does not duplicate
them.

## Deterministic parent-first ordering

Persistence systems with parent foreign keys often need to write parents before children.
`document_sections_parent_first(document)` validates the document and returns a deterministic
parent-before-child ordering.

Ordering is iterative rather than recursive so deeply nested documents do not depend on
Python recursion limits. Siblings are ordered deterministically by section ordinal and ID.
The stored `Document.sections` tuple itself is not required to be parent-first; valid inputs
may contain a child before its parent.

## Error contract

Structural validation raises `DocumentStructureError`, a `ValueError` subclass with a
stable `code` suitable for adapter/boundary translation:

| Code | Meaning |
| --- | --- |
| `duplicate_sections` | section IDs or document-level section ordinals collide |
| `duplicate_passage_ids` | a passage ID occurs more than once in the document |
| `duplicate_passage_ordinals` | passage ordinals collide within one section |
| `missing_parent` | a section references a parent absent from the document |
| `cyclic_parent` | the parent graph contains a cycle |

Human-readable messages are diagnostic text; integrations should prefer `code` when they
need machine-stable behavior.

## Boundary responsibilities

### Parsers

Parser output must satisfy this contract before it is treated as a normalized native parse.
Rich native information that does not fit the canonical `Document` should remain in
`SourceObservation`, native metadata, resource links, or immutable source artifacts rather
than being discarded or forced into the hierarchy.

### JSON and PostgreSQL repositories

Both reference persistence implementations validate the same contract on writes. Reads are
also validated before reconstructed documents leave the repository boundary so corrupted or
legacy-invalid persisted structures fail explicitly.

### Canonical normalized JSON / proof / replay

Hostile-input JSON validation still owns JSON shape, scalar types, canonical UUID spelling,
canonical encoding, and source-artifact field validation. After those fields are decoded into
safe structural domain objects, the shared document validator owns section/passage hierarchy
semantics. Its stable error codes are translated back to normalized-document boundary errors.

## Compatibility

This contract centralizes invariants already enforced by Tarkka's persistence or proof/replay
paths; it does not redefine heading level as tree depth. Existing valid parser output should
therefore remain valid.

A future proposal that strengthens hierarchy semantics must first audit representative native
formats and persisted data, document the compatibility impact, and provide a migration path if
existing canonical documents would become invalid.
