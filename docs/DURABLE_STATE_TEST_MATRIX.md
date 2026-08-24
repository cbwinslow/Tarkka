# Durable-State Test Matrix

This document inventories Tarkka's durable persistence surfaces and the executable tests that protect them.

The goal is not to force every repository through an identical test shape. It is to make the persistence contract for each durable surface explicit: what is persisted, how it is reloaded, how corruption fails, and how interrupted writes recover.

Status meanings:

- **Covered** — the durable surface has reusable contract or focused regression coverage for the behavior it actually promises.
- **Not applicable** — a specific persistence concern does not belong to that surface's public contract; for example, a write-only audit sink has no reload parser to validate against malformed historical rows.

## Inventory

| Durable surface | Implementation | Round trip / reopen | Idempotency / identity | Corruption / schema | Failure / concurrency | Current status |
| --- | --- | --- | --- | --- | --- | --- |
| Research document repository | `src/tarkka/infrastructure/storage/json_repository.py` | `tests/test_json_research_repository_contract.py` | contract suite plus native-ingest/vertical-slice coverage | `tests/test_research_catalog_schema_corruption.py` | `tests/test_ingest_persistence_recovery.py` | **Covered** |
| Work catalog | `src/tarkka/infrastructure/storage/json_work_repository.py` | `tests/test_json_work_repository_contract.py` | reusable work-repository contract | `tests/test_work_catalog_schema_corruption.py` | workflow-level persistence coverage exists | **Covered** |
| Citation catalog | `src/tarkka/infrastructure/storage/json_citation_repository.py` | `tests/test_json_citation_repository_contract.py` | reusable citation-repository contract; relation atomicity regressions | `tests/test_citation_catalog_schema_corruption.py`, `tests/test_citation_catalog_hardening.py` | `tests/test_citation_relation_atomicity.py`, native-ingest persistence regressions | **Covered** |
| Extraction catalog | `src/tarkka/infrastructure/storage/json_extraction_repository.py` | `tests/test_json_extraction_repository_contract.py` | reusable extraction-repository contract | `tests/test_extraction_catalog_schema_corruption.py` | claim-extraction workflow coverage exists; add dedicated interruption tests if persistence becomes multi-step | **Covered** for current single-repository contract |
| Source-observation catalog | `src/tarkka/infrastructure/storage/json_source_observation_repository.py` | `tests/test_json_source_observation_repository_contract.py` | reusable source-observation contract | `tests/test_source_observation_schema_corruption.py` | HTTP/native-ingest recovery tests exercise observation persistence across interrupted finalization | **Covered** |
| Traversal checkpoints | `src/tarkka/infrastructure/storage/json_traversal_checkpoint_repository.py` | `tests/test_traversal_checkpoints.py`, `tests/test_traversal_finalization_serialization.py` | checkpoint/state-machine tests preserve deterministic traversal state | `tests/test_traversal_checkpoint_schema_corruption.py` | `tests/test_traversal_checkpoint_failure_injection.py`, HTTP finalization/restart regressions | **Covered** |
| Local artifact store | `src/tarkka/infrastructure/storage/local_artifacts.py` | `tests/test_local_artifact_store_contract.py`, `tests/test_local_artifact_durability.py` | content identity/durability contract | **Not applicable** to a schema-versioned record catalog | `tests/test_ingest_persistence_recovery.py`, `tests/test_http_finalization_recovery.py`, `tests/test_http_overflow_durable_state.py` | **Covered** |
| Acquisition provenance log | `src/tarkka/infrastructure/storage/acquisition_log.py` | `tests/test_jsonl_audit_log_durability.py`, `tests/test_acquisition_provenance.py` | append/provenance behavior preserves acquisition IDs and source observations | **Not applicable**: intentionally write-only JSONL sink with no historical-row read API | concurrent writers are serialized with `exclusive_lock`; writes flush and `fsync`; concurrency/reopen regressions live in `tests/test_jsonl_audit_log_durability.py` | **Covered** |
| Identity decision log | `src/tarkka/infrastructure/storage/identity_decision_log.py` | `tests/test_jsonl_audit_log_durability.py`, `tests/test_fuzzy_identity.py` | deterministic decision/provenance behavior is covered at the application boundary | **Not applicable**: intentionally write-only JSONL audit sink with no historical-row read API | concurrent writers are serialized with `exclusive_lock`; writes flush and `fsync`; concurrency/reopen regressions live in `tests/test_jsonl_audit_log_durability.py` | **Covered** |
| PostgreSQL evidence relations | `src/tarkka/infrastructure/postgres/verification_repository.py`, migration `0009` | `tests/test_postgres_verification_repository_unit.py` decodes persisted rows | immutable deterministic IDs and incompatible-content rejection | PostgreSQL schema checks enforce Claim/context lineage, exact-evidence shape, and typed values | real PostgreSQL migration validation in the CI database workflow; driver errors are translated at the adapter boundary | **Covered** for the current repository port; interface backend selection remains intentionally deferred until extraction/citation ports are also PostgreSQL-backed |

## Confirmed testing assets

Tarkka has the shared infrastructure expected by the persistence strategy:

- reusable repository/adapter contracts under `tests/contracts/`;
- deterministic time and sleep primitives in `tests/support/deterministic.py`;
- reusable failure injection through `FaultPlan` and helpers under `tests/support/`;
- schema-corruption regressions for research, work, citation, extraction, source-observation, and traversal catalogs;
- restart/finalization regressions around acquisition and traversal;
- local concurrency and reopen regressions for append-only JSONL audit logs;
- strict pytest markers, Python 3.11/3.12/3.13 CI, branch coverage, and changed-line coverage.

New durable repositories should add or reuse a `tests/contracts/` suite instead of relying only on workflow-level tests. New audit sinks should document whether they are write-only or support historical reads and test that public contract directly.

## Future schema evolution

When a durable format introduces an explicit schema version or migration:

- test the immediately previous supported version -> current version path;
- reject unknown/newer versions safely;
- verify deterministic identifiers survive migration;
- retain a golden fixture for each supported historical schema rather than mutating old fixtures in place.

Until such a version exists, corruption and round-trip tests are preferable to speculative migration infrastructure.

## Maintenance rule

This inventory should be updated in the same pull request whenever a new durable repository, audit log, or schema-versioned format is added. A row should describe the surface's real public durability contract rather than inventing APIs solely to make test categories symmetrical.
