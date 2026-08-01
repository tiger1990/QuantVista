---
baseline_commit: 9c6f07b2c2a60234f861b944f7c8a482d3851584
---

# Story 1.12: QV-104 — Monthly partition maintenance

Status: done

**Epic:** EPIC-PLAT (Epic 1) · **Points:** 2 · **Depends:** QV-014 (partitioned `daily_prices`), QV-015 (job framework)

> **Found, not planned.** Surfaced while implementing QV-070: a date-rollover test failed on 2026-08-01 because the dev database had no August partition. Investigating it showed the failure was local, but the *cause* was not — nothing anywhere schedules partition creation, and the consequence is silent data misrouting in any long-running environment. Shipped in the QV-070 PR at the user's request, since both open items came out of that story.

## Story

As the platform, I want monthly partitions created ahead of the data, so rows never silently fall into the `_default` partition.

## The defect

`0004_prices_partitioned.py` (and `0006_indicators_factors_scores.py`) create only the **current and next** month at migration time. `src/quantvista/db/README.md` §"Partition maintenance" says to *schedule* `create_month_partition(...)` from then on — **nothing did**. No job, Beat entry, or cron called it outside migrations.

PostgreSQL does not error when no partition matches a row: it routes it into the `_default` partition. So from the second month after a deploy, every `daily_prices` / `technical_indicators` / `scores` / `factor_values` row lands there — partition pruning quietly lost, default table growing unbounded, nothing in the logs.

**Demonstrated on the real database** before fixing: a row dated two months out landed in `daily_prices_default`.

## Acceptance Criteria

1. **A scheduled job keeps partitions ahead.** `quantvista.ensure_partitions` creates the current + next `DEFAULT_MONTHS_AHEAD` (3) monthly partitions for every date-range-partitioned table. Beat-scheduled **daily**, not monthly: the work is idempotent and trivially cheap, so a missed run, a failed worker, or a restart on the wrong day self-heals by the next tick rather than waiting a month.
2. **Parents are discovered, not listed.** The parent set comes from the PostgreSQL catalog (`pg_partitioned_table`, RANGE strategy, single date/timestamp key), so a table partitioned in a future migration is maintained automatically instead of being forgotten. Partitioned *indexes* must not be mistaken for tables (`relkind = 'p'`).
3. **A standing guard fails when coverage lapses.** An integration test asserts no partitioned parent lacks a partition covering **next month** — the exact regression that shipped. It must name the offending tables.
4. **Idempotent and self-cleaning.** Re-running creates nothing and raises nothing. Tests must not leave partitions behind.
5. **Gates green.** Backend ruff/format, mypy, import-linter, full pytest.

## Tasks / Subtasks

- [x] **Task 1 — `core/partitions.py` (AC: 1, 2)** — catalog discovery, month arithmetic, `ensure_month_partitions`, `parents_missing_cover`.
- [x] **Task 2 — `jobs/maintenance.py` + Beat entry (AC: 1)** — `quantvista.ensure_partitions` on the privileged session, daily at 00:30, registered in `include` and `BEAT_SCHEDULE`.
- [x] **Task 3 — tests (AC: 3, 4)** — unit month arithmetic incl. the Dec→Jan rollover; integration discovery, the next-month guard, idempotency, and an end-to-end routing proof.
- [x] **Task 4 — gates (AC: 5)** — 805 passed, 5 skipped; ruff/mypy/lint-imports clean.

## Dev Agent Record

### Agent Model Used

claude-opus-5

### Debug Log

- **The bug reproduced before the fix and after:** a `daily_prices` row dated two months ahead landed in `daily_prices_default`; after the job ran it lands in `daily_prices_2031_03`. The end-to-end test pins exactly that.
- **Guard verified by breaking it.** Dropped `daily_prices_2026_09` and the next-month guard failed with `assert ['daily_prices'] == []`, naming the table. Restored by running the new job itself, which is also its first live exercise.
- **Catalog query needed `relkind = 'p'`.** An initial `pg_inherits` join returned partitioned *index* names (`ix_scores_date_composite`, `daily_prices_pkey`) alongside tables. Filtering on `pg_partitioned_table` + `relkind = 'p'` + a single date/timestamp key column fixes it; a test asserts no `ix_*`/`*_pkey` leaks into the parent set.
- **My own test polluted the database — caught and fixed.** The first version reached a 2031 date by passing `months_ahead≈55`, which created a partition for *every* month in between: **204 stray empty tables** across four parents, with cleanup for only one month. Rewritten to pass `today=_FUTURE, months_ahead=1` (two months, both cleaned up). The strays were dropped with a row-count guard so nothing holding data could be touched, and a re-run confirmed the partition count is now stable at 28 across a full test run.
- **`disallow_untyped_decorators`**: `jobs.maintenance` joins the existing pyproject exemption list — Celery's `@app.task` is untyped, and every other job module is already listed.

### Completion Notes List

- **Daily, not monthly, is the deliberate choice.** A monthly schedule has exactly twelve chances a year to work; a daily one is idempotent, costs four `CREATE TABLE IF NOT EXISTS` statements, and recovers from a missed run without human intervention.
- **Three months of lookahead**, not one — the original defect was having only current+next, so a single missed run stranded the data.
- **Not backfilled into migrations.** Existing databases self-heal on the first scheduled run; no migration was added, since partition DDL at migration time is what created the false sense of coverage in the first place.
- **`_default` partitions are kept.** They remain the correct safety net for genuinely out-of-range dates (e.g. a corporate-action backfill predating the first partition) — the fix is to stop *relying* on them, not to remove them.

### File List

- `backend/src/quantvista/core/partitions.py` (new — catalog discovery + month maintenance)
- `backend/src/quantvista/jobs/maintenance.py` (new — `quantvista.ensure_partitions`)
- `backend/src/quantvista/jobs/celery_app.py` (modified — `include` + daily Beat entry)
- `backend/tests/test_partitions_unit.py` (new)
- `backend/tests/integration/test_partition_maintenance.py` (new — incl. the standing next-month guard)
- `backend/pyproject.toml` (modified — mypy decorator exemption for the new job module)

### Change Log

- 2026-08-01 — QV-104: Beat-scheduled monthly partition maintenance with catalog-discovered parents, plus a standing guard test that fails when any partitioned table lacks next month's partition. Closes a silent data-misrouting gap that was documented but never implemented.
