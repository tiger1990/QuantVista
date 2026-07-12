---
baseline_commit: c2255e6
---

Status: done

# QV-047 — Alerts schema + rule engine

**Epic:** EPIC-ALERT (Epic 6) · **Points:** 5 · **Depends:** QV-007 (tenancy/RLS + entitlements ✓)

## Story

As a user, I want configurable alert rules, so I'm notified on conditions I care about — tenant-isolated, validated, and capped by my plan.

## Acceptance Criteria

1. **`alert_rules` + `alert_events`** tables (migration), **tenant-scoped with RLS** (`app_current_tenant()` isolation, `FORCE ROW LEVEL SECURITY`), per the `03` §4.3 shape.
2. A rule's **condition is validated against an allow-list** (metric ∈ known score/fundamental fields, op ∈ {gte,lte,gt,lt,eq}, numeric value) + allow-listed **scope** ('stock'|'portfolio') and **channel** ('email'|'in_app') — an invalid rule is rejected (422), never stored.
3. **Per-tier limit enforced** on create via the seeded `alerts` entitlement (Free 3 / Pro 50 / Quant unlimited): creating past the limit → `EntitlementExceeded` (403/409 per the app's handler).
4. **CRUD API** (`04` §3.7): `POST /api/v1/alerts` (create, validated + limited), `GET /api/v1/alerts` (list the tenant's rules), `DELETE /api/v1/alerts/{id}` — all on the RLS tenant session, so cross-tenant access is impossible.
5. `alert_events` schema is created here (RLS) but **not populated** — firing is QV-048 (`evaluate_alerts`), delivery is QV-049.

## Tasks / Subtasks

- [x] **Task 1 — schema (already migration 0010)** (AC: #1, #5)
  - [x] **No new migration** — `alert_rules` + `alert_events` (+ `notifications`) were forward-declared in **migration 0010** (tenant-scoped, RLS FORCE + isolation, `ix_alert_rules_active WHERE is_active`, and `alert_events.dedup_key` + `UNIQUE(alert_rule_id, dedup_key)` ready for QV-048). Verified the repo/API use only 0010's columns. (A duplicate 0016 was created then removed — 0010 already had it, like sentiment in 0007.)
- [x] **Task 2 — rule validation (pure)** (AC: #2)
  - [x] `alerts/rules.py`: `METRICS` (screener numeric fields) / `OPS` / `SCOPES` / `CHANNELS`; `validate_condition/scope/channel` → `AlertRuleError` (unknown metric/op, non-numeric/bool value, bad scope/channel). 11 unit tests.
- [x] **Task 3 — repository + schemas** (AC: #4)
  - [x] `alerts/repositories.py`: `create_alert_rule` / `count_active_alert_rules` / `list_alert_rules` / `delete_alert_rule` (RLS session, mirrors `saved_screens`). `schemas/alerts.py`: `AlertConditionSchema` / `CreateAlertRequest` / `AlertRule`.
- [x] **Task 4 — API + wiring** (AC: #3, #4)
  - [x] `api/routes_alerts.py`: POST/GET/DELETE (validate condition → 422; `alerts` limit → `EntitlementExceeded` 403; RLS session). `AlertRuleError`/`AlertNotFound` handlers + router registered in `app.py`. openapi.json + schema.d.ts regenerated.
- [x] **Task 5 — tests + gates + reconcile** (AC: all)
  - [x] Integration `test_api_alerts.py` (real app + PG + 2 tenants): create/list/delete, Free-tier limit (4th → 403 entitlement_exceeded), invalid condition → 422, **cross-tenant RLS isolation** (B sees none / delete→404 / A intact). Gates. QV-046 → done reconcile on this branch.

## Dev Notes

### Mirror saved-screens exactly (QV-039)
`routes_screens.py` + `analytics/saved_screens.py` are the template: `get_tenant_context` / `get_tenant_session` / `get_entitlement_service` deps; validate with an allow-list; `limit = entitlements.limit(tenant_id, "alerts")` then `count_* >= limit → EntitlementExceeded`; all persistence on the RLS session (no manual `tenant_id` filter — the `app_current_tenant()` policy scopes it). RLS migration mirrors `0009` (`_enable_rls` with FORCE + isolation policy). The `alerts` entitlement is already seeded (QV-005): Free 3, Pro 50, Quant NULL(∞).

### Condition allow-list
Reuse the screener's numeric metric set (composite_score, fundamental/momentum/quality/sentiment/risk_score, coverage, pe, pb, roe, roce, debt_equity) + ops {gte,lte,gt,lt,eq}; value must be a number. `scope ∈ {stock, portfolio}`, `channel ∈ {email, in_app}`. Validating here means QV-048's evaluator only ever sees runnable rules. RSI/drift/news metrics are a QV-048 extension of the allow-list (this story ships the score/fundamental set).

### Bounded context
`alerts` is the top of the domain DAG (may import `analytics`/`identity`); the context files are stubs today. `alert_events` firing/dedup = **QV-048** (`evaluate_alerts` on `ScoresComputed`/`NewsScored`, emits `AlertsFired`); delivery (in-app/email) = **QV-049**. `IAlertService.evaluate` (already declared) is implemented in QV-048, not here.

### Not this story
Evaluation, deduplication, `AlertsFired`, notification delivery, and the alerts management UI. Only the schema, validated CRUD, and tier-limit enforcement.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Gates: ruff + format clean · mypy clean (196 files) · import-linter 3/3 (`alerts` is top-of-DAG) · pytest **424 passed / 5 skipped** (+11 rule-validation unit, +4 alerts API integration).
- **No migration** — `alert_rules`/`alert_events` were already created by migration **0010** (found after a duplicate 0016 failed CI with `DuplicateTable`; 0010's schema is a superset — has `dedup_key`/`updated_at` this story doesn't use). Chain head stays 0015; both tables `rowsecurity=t`.

### Completion Notes List

- **Straight mirror of saved-screens (QV-039):** same tenant-session + entitlement-limit + allow-list shape, so the alerts CRUD is uniform with the rest of the tenant-scoped API. RLS migration mirrors 0009 (`_enable_rls` = ENABLE + FORCE + isolation policy).
- **Defence in depth on validation:** pydantic pins `scope`/`channel`/`op` as `Literal`s and `value` as `float` at the edge; the domain `alerts.rules` allow-list is the authoritative re-check (metric ∈ known fields, numeric non-bool value) before persisting — an unknown metric passes pydantic but is rejected 422 by the domain check (tested).
- **`alerts` entitlement already seeded** (QV-005: Free 3 / Pro 50 / Quant NULL=∞) → no seed/entitlement change; create enforces `count_active_alert_rules >= limit → EntitlementExceeded`.
- **`alert_events` created empty** — firing/dedup + `AlertsFired` is QV-048 (the partial `ix_alert_rules_active` index is pre-provisioned for its per-tenant active-rule scan); delivery is QV-049. `IAlertService.evaluate` stays unimplemented here.
- No alerts UI in this story; openapi.json/schema.d.ts regenerated so the `/alerts` contract is available when the management UI is built.

### File List

- `backend/src/quantvista/alerts/rules.py` (new) — allow-list validation
- `backend/src/quantvista/alerts/repositories.py` — RLS-scoped CRUD (was a stub)
- `backend/src/quantvista/schemas/alerts.py` (new) — wire DTOs
- `backend/src/quantvista/api/routes_alerts.py` (new) — POST/GET/DELETE /alerts
- `backend/src/quantvista/api/app.py` — router + `AlertRuleError`/`AlertNotFound` handlers
- `backend/tests/test_alert_rules.py` (new), `backend/tests/integration/test_api_alerts.py` (new)
- `frontend/src/lib/api/openapi.json`, `frontend/src/lib/api/schema.d.ts` — regenerated (contract in sync)

### Change Log

- QV-047: Alerts schema + rule engine — builds on the pre-existing `alert_rules`/`alert_events` tables (migration 0010, tenant-scoped RLS) with pure allow-list condition validation and validated + tier-limited CRUD (`POST/GET/DELETE /api/v1/alerts`) mirroring saved-screens. Firing (QV-048) and delivery (QV-049) build on this. No migration, no entitlement/seed change.
