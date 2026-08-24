# PostgreSQL Persistence Approach

## Decision

Tarkka uses PostgreSQL as its production metadata system of record and `psycopg` 3 as its optional
database driver. PostgreSQL repositories remain infrastructure adapters behind application ports;
domain models must not become ORM entities.

The current SQL migrations remain the authoritative, append-only schema history. Migration discovery
is deterministic and checksummed. The next persistence increment adds the explicit database-backed
upgrade runner and schema-version table; it will not run automatically during application startup.
Deployments must run the explicit upgrade command before starting a service or worker.

## Package choices

| Package | Decision | Rationale |
|---|---|---|
| `psycopg` 3 | Use, optional `postgres` extra | Direct PostgreSQL access, parameter binding, transactions, and PostgreSQL-specific features without making the base profile depend on a database. |
| SQLAlchemy ORM | Do not add | Mapping persistence state onto canonical domain classes would couple the domain to database lifecycle and identity behavior. |
| SQLAlchemy Core | Defer | It may become useful inside infrastructure when several repositories demonstrably share schema/query construction, but handwritten parameterized SQL is currently smaller and clearer. |
| Alembic | Do not add now | The existing SQL files contain their own transactional DDL and are the already-published schema history. A small native runner can record and apply them without adding an ORM/SQL expression dependency. Reconsider Alembic only when branch-aware revision management or SQLAlchemy Core metadata is actually adopted. |
| Pydantic | Do not add for persistence | Database rows are adapted and validated by repositories. Pydantic is a future option at untrusted HTTP/MCP/configuration boundaries or when generated JSON Schema is needed; it is not an ORM or migration tool. |
| `psycopg_pool` / async driver | Defer | Short-lived CLI operations create short-lived connections. A long-lived concurrent service may own a pool at its composition root after load is measured; repositories must not own global pools. |

## Operational contracts

- `TARKKA_DATABASE_URL` is required only for an explicitly selected PostgreSQL backend.
- A database URL alone never changes the local JSON default.
- Each repository translates driver failures into interface-safe errors while retaining the original
  exception as the cause for logs/diagnostics.
- Migrations are append-only after merge. An upgrade records a checksum for each applied file and
  refuses a changed historical migration.
- Schema upgrades are explicit and idempotent. No normal CLI/API/MCP command performs DDL.
- Production repositories use PostgreSQL capabilities directly when useful; a future SQLite profile
  must be a separately tested adapter, not a lowest-common-denominator constraint on the schema.

## Reconsideration triggers

Adopt SQLAlchemy Core only after repeated repository-level query/schema duplication makes it cheaper
than the added abstraction. Adopt Alembic only together with a deliberate conversion plan for the
existing SQL history, including offline SQL output and a real PostgreSQL upgrade test. Adopt Pydantic
only with a named untrusted boundary and a validation/serialization contract.
