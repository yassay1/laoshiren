# ADR 0003: Clear one-shot Automation trigger after materialization

## Status

Accepted, 2026-09-20.

## Context

The authoritative Automation/Scheduler/Notification v2.2 design, section 61,
requires `next_trigger_at = NULL` when an ONCE or one-shot RELATIVE occurrence is
materialized. The existing database column and API response require a timestamp.
The scheduler has consequently relied on a `last_triggered_at` comparison to
avoid repeatedly scanning a materialized one-shot Automation.

## Decision

- `next_trigger_at` is nullable in PostgreSQL, the ORM, Domain, Application DTO,
  and read API response. Creation still requires a timezone-aware timestamp.
- Materializing ONE_SHOT, ONCE, or RELATIVE clears `next_trigger_at` in the same
  transaction as the Occurrence and DurableJob. The scheduled timestamp remains
  on the Occurrence as the durable historical slot.
- The migration clears legacy one-shot triggers only when `last_triggered_at` is
  present. On downgrade, null triggers are restored from `last_triggered_at`,
  then `updated_at` or `created_at`, before restoring NOT NULL. This preserves a
  valid old schema; the old schema cannot represent the cleared-trigger meaning.
- The existing due index remains. SQL comparison with NULL naturally excludes
  materialized one-shot rows, so the extra `last_triggered_at` predicate is
  removed.

## Consequences

Clients must accept `next_trigger_at: null` for an already materialized
Automation. OpenAPI is regenerated from the response schema. The response field
remains required to distinguish a cleared trigger from an omitted field.
