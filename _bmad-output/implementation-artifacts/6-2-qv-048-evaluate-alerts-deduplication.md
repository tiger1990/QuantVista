---
baseline_commit: 29bf95f
---

Status: review

# QV-048 — evaluate_alerts + deduplication

**Epic:** EPIC-ALERT (Epic 6) · **Points:** 5 · **Depends:** QV-047 (alert schema/rules ✓), QV-030 (scores ✓)

## Story

As a user, I want alerts to fire promptly and not spam me, so they're useful.

## Acceptance Criteria

1. `evaluate_alerts` runs **on `ScoresComputed` and `NewsScored`** (event-triggered consumers, thin → `.delay()`), so a rule fires **within one scoring cycle** (US-05).
2. Evaluates each **active** alert rule's condition (the QV-047 allow-list metrics: score sub-scores + coverage + pe/pb/roe/roce/debt_equity) against the target stock's current snapshot; only matching rules fire.
3. **Deduplicated** — at most one `alert_events` row per `(alert_rule_id, cycle)` via the 0010 `UNIQUE(alert_rule_id, dedup_key)` (dedup_key = the cycle date) with `ON CONFLICT DO NOTHING`; re-evaluation in the same cycle is a no-op.
4. Writes `alert_events` (tenant_id, alert_rule_id, dedup_key, payload={metric, value, op, threshold}, status='pending') and **emits `AlertsFired`** after commit.
5. Runs cross-tenant as a background job on the **privileged (RLS-bypassing) session** — reads all tenants' active rules, writes each event under its rule's tenant_id; idempotent per `(date, trigger)` under the QV-015 job framework.

## Tasks / Subtasks

- [x] **Task 1 — pure evaluation** (AC: #2)
  - [x] `alerts/evaluation.py`: `matches(value, op, threshold)` (operator map for gte/lte/gt/lt/eq; None value or unknown op → False). 11 unit tests.
- [x] **Task 2 — repository** (AC: #2, #3, #5)
  - [x] `alerts/repositories.py`: `active_alert_rules` (privileged, all tenants); `stock_metrics` (LATERAL latest scores + fundamentals → the 12 QV-047 metrics per stock); `insert_alert_event` → `ON CONFLICT (alert_rule_id, dedup_key) DO NOTHING RETURNING id` (True iff new).
- [x] **Task 3 — evaluation service** (AC: #2, #3, #4)
  - [x] `alerts/services.py`: `AlertEvaluationService.evaluate(as_of, trigger)` — privileged session → active rules (scope=stock) → batch metrics → `matches` → `insert_alert_event` (dedup_key = `as_of.isoformat()`) → returns NEW count.
- [x] **Task 4 — job + event + triggers** (AC: #1, #4, #5)
  - [x] `AlertsFired` event. `jobs/alerts.py::evaluate_alerts(date_iso, trigger)` under `run_job` (key `alerts:{date}:{trigger}`), emits `AlertsFired` after evaluate() commits. Consumers: `on_scores_computed` `.delay(day,"scores")` + new `on_news_scored` `.delay(None,"news")`; subscribed `NewsScored`. (Registered via the consumers import; mypy untyped-decorator override added.)
- [x] **Task 5 — tests + gates + reconcile** (AC: all)
  - [x] Integration `test_evaluate_alerts.py` (real PG + 2 tenants, seeded score+fundamentals): matching composite rule fires (2 rules), pe rule doesn't; **dedup** (re-run → 0); events under each tenant_id with `status='pending'` + payload {metric,value}; `AlertsFired` emitted via the task. Gates green (438 passed). QV-047 → done reconcile on this branch.

## Dev Notes

### Cross-tenant on the privileged session
`alert_rules`/`alert_events` are RLS-scoped, but the trigger is a global event, so `evaluate_alerts` is a background job (like scoring) that uses `privileged_session_scope()` — the admin/superuser role **bypasses RLS** (even FORCE), so it reads every tenant's active rules and inserts each event under its rule's own `tenant_id`. This is the first job to touch an RLS table cross-tenant; the `WITH CHECK` policy is bypassed by superuser so the per-tenant insert is fine.

### Metric source + evaluation
Per target stock, the QV-047 metrics come from the **latest `scores`** (composite/sub-scores/coverage) + **latest open `fundamentals`** (pe/pb/roe/roce/debt_equity) — same sources as `stock_detail`, read in one batched query keyed by stock_id. `matches` is pure (gte/lte/gt/lt/eq; a `None` metric never fires). Rules whose metric is absent for their stock simply don't fire.

### Dedup = one fire per rule per cycle
`dedup_key = as_of date`. `INSERT … ON CONFLICT (alert_rule_id, dedup_key) DO NOTHING` (the 0010 unique index) → a rule fires at most once per cycle date no matter how many `ScoresComputed`/`NewsScored` events land that day. `AlertsFired` fires only after the writes commit (no phantom events), mirroring `FactorsComputed`/`ScoresComputed`.

### Not this story
- **Delivery** (in-app/email, the `notifications` table) = **QV-049**; events are written `status='pending'`, undelivered.
- **scope='portfolio'** evaluation (needs portfolio holdings) and **RSI/drift/news** metrics (need the QV-047 allow-list + metric sources extended) — deferred; this story evaluates `scope='stock'` over the score/fundamental metrics QV-047 already admits.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Gates: ruff + format clean · mypy clean (201 files) · import-linter 3/3 (`alerts` top-of-DAG; `jobs.alerts`→`alerts` ok) · pytest **438 passed / 5 skipped** (+11 match unit, +3 evaluate integration).
- Test gotcha: the job's run_key is date-based (`alerts:{date}:{trigger}`) → the ledger record persists across suite runs and would skip the task; fixture teardown now clears `jobs_runs WHERE run_key LIKE 'alerts:%'`.

### Completion Notes List

- **Cross-tenant on the privileged (superuser) session** — first job to read/write an RLS table across tenants; superuser bypasses RLS (even FORCE), so one pass reads every tenant's active rules, batches metrics, and inserts each event under its rule's own `tenant_id`.
- **Two idempotency layers:** `run_job` key `alerts:{date}:{trigger}` (a redelivered event doesn't double-run the job) + the 0010 `UNIQUE(alert_rule_id, dedup_key)` with `ON CONFLICT DO NOTHING` (a rule fires at most once per cycle date). `AlertsFired` fires only after evaluate() commits.
- **Metric source = latest scores + latest fundamentals** (LATERAL, keyed by stock_id) — the 12 QV-047 metrics. A `None` metric never fires (pure `matches`).
- **Scoped to `scope='stock'` + score/fundamental metrics** (what QV-047 admits). `scope='portfolio'` (needs holdings) and RSI/drift/news metrics (need the allow-list + sources extended) are deferred. Delivery is QV-049 — events land `status='pending'`.

### File List

- `backend/src/quantvista/alerts/evaluation.py` (new) — pure `matches`
- `backend/src/quantvista/alerts/repositories.py` — `active_alert_rules`, `stock_metrics`, `insert_alert_event`
- `backend/src/quantvista/alerts/services.py` — `AlertEvaluationService` (was a stub)
- `backend/src/quantvista/jobs/alerts.py` (new) — `evaluate_alerts` task
- `backend/src/quantvista/jobs/consumers.py` — `on_scores_computed` trigger + `on_news_scored` (+ NewsScored subscribe)
- `backend/src/quantvista/core/event_types.py` — `AlertsFired`; `backend/pyproject.toml` — jobs.alerts mypy override
- `backend/tests/test_alert_evaluation.py` (new), `backend/tests/integration/test_evaluate_alerts.py` (new)

### Change Log

- QV-048: evaluate_alerts + deduplication — event-triggered (`ScoresComputed`/`NewsScored`) cross-tenant evaluator on the privileged session; fires QV-047 rules against the latest score/fundamentals, writes deduped `alert_events` (0010 UNIQUE, one per rule/cycle), emits `AlertsFired`. Delivery = QV-049. No migration.
