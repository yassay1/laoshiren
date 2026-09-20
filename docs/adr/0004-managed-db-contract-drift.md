# ADR 0004: Make the managed PostgreSQL contract drift gate authoritative

## Status

Accepted, 2026-09-20.

## Context

`alembic check` compared only the Personal State ORM against the entire
database. It consequently proposed deleting the File tables and LangGraph
checkpoint tables. After loading both ORM modules and excluding only the four
framework-owned checkpoint tables, it exposed genuine managed-schema drift:
audit timestamps typed as required in ORM were nullable in historical
migrations, and several migration-created indexes, check constraints, and one
foreign-key action were missing from ORM metadata. Server defaults were also
present in migrations but absent from ORM metadata.

## Decision

- Load every project-owned ORM table in Alembic's metadata. Exclude only
  LangGraph's `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, and
  `checkpoint_migrations` from autogenerate comparison. They remain managed by
  the checkpoint lifecycle.
- Keep the established ORM contract that creation and update audit timestamps
  are required. A reversible migration backfills any null values before adding
  `NOT NULL`; downgrade restores nullable columns without altering values.
- Represent the project's existing indexes, check constraints, and foreign-key
  delete behavior and server defaults in ORM metadata. Enable comparison of
  server defaults so autogenerate compares the full managed schema. Do not
  suppress individual drift categories to make the gate pass.
- Run `alembic check` as the managed DB Contract gate after `upgrade head`.

## Consequences

The migration may briefly lock the affected tables while constraints are
applied. It should be scheduled before production traffic for large databases.
Future ORM changes without matching migrations cause the gate to fail.
