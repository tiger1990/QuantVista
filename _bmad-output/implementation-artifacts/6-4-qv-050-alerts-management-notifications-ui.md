---
baseline_commit: cd87646
---

Status: done

# QV-050 — Frontend: Alerts management + notifications

**Epic:** EPIC-ALERT (Epic 6) · **Points:** 5 · **Depends:** QV-047 (alerts API ✓), QV-035 (frontend foundation ✓)

## Story

As a user, I want to manage alerts and see notifications, so I control my signals — user self-service (each user sees only their own; NOT an admin panel).

## Acceptance Criteria

1. **`/alerts` page** — list the user's alert rules, **create** (stock target + metric + op + threshold + channel), **delete**; empty/loading states. All via the QV-047 CRUD API on the RLS tenant session (only own rules).
2. **Limit-aware** — show usage vs the `alerts` entitlement from `/me` (`3` Free / `50` Pro / unlimited); block create + surface the `entitlement_exceeded` (403) clearly when at the cap.
3. **Email opt-in** — the channel (`in_app` | `email`) is chosen per rule in the create form.
4. **In-app notification center** — a bell in the app nav with an unread badge + a dropdown listing recent notifications (from the fired alerts, QV-049); marks read on open.
5. Backend gap filled: **`GET /api/v1/notifications`** (list, RLS) + **mark-read** — the only new API; alert CRUD already exists (QV-047). openapi/schema regenerated.

## Tasks / Subtasks

- [x] **Task 1 — notifications read API** (AC: #4, #5)
  - [x] `list_notifications`/`mark_all_notifications_read` (RLS + user-scoped), `schemas/notifications.py`, `api/routes_notifications.py` (`GET /notifications` + `POST /notifications/read`), registered. Integration `test_api_notifications.py` (list newest-first, mark-read, per-user isolation).
- [x] **Task 2 — API types + query hooks + stock-id gap** (AC: #1, #2, #4)
  - [x] openapi/schema regenerated. `useAlerts`/`useCreateAlert`/`useDeleteAlert` + `useNotifications`/`useMarkNotificationsRead`; `entitlements` on the auth user. **Backend enrichments** (the symbol↔id gap): `StockListItem.id` (create picker → `target_id`) + `AlertRule.target_symbol` (list display).
- [x] **Task 3 — /alerts page** (AC: #1, #2, #3)
  - [x] `app/(app)/alerts/page.tsx` + `AlertForm` (stock search picker + metric/op/value/channel) + `AlertList` (delete). Limit banner "N of MAX/∞" + `atLimit` disable + typed 403/422 (`CreateAlertError`). **Alerts** added to `app-nav`.
- [x] **Task 4 — notification center** (AC: #4)
  - [x] `NotificationBell` in `app-nav`: unread badge, dropdown of recent notifications (formatted from payload + timestamp), marks read on open. Polls every 60s.
- [x] **Task 5 — tests + gates + reconcile** (AC: all)
  - [x] `AlertList.test.tsx` (empty state + render + delete). Backend **449 passed**; frontend tsc/eslint clean, **51 passed**, `next build` green (`/alerts` route). QV-049 → done reconcile on this branch.

## Dev Notes

### Mirror saved-screens (QV-039)
`features/screener/SaveScreenForm.tsx` + `SavedScreens.tsx` + `useSavedScreens`/`useSaveScreen`/`useDeleteScreen` (useMutation + `invalidateQueries`) are the template for the alert CRUD hooks/components. The notifications API mirrors `routes_screens` (RLS tenant session, `get_tenant_context`/`get_tenant_session`).

### Limit-aware
`/me` returns `entitlements` as `{key: limit|flag}`, so `entitlements.alerts` is `3` / `50` / `null` (unlimited). Expose it on the auth user; the page shows `N of {limit ?? "∞"}` and disables create at the cap. Creating past it still returns 403 `entitlement_exceeded` — surface that too (defence + UX).

### Condition/metric UX
Metric select = the QV-047 allow-list (composite_score, sub-scores, coverage, pe/pb/roe/roce/debt_equity); op select = gte/lte/gt/lt/eq; value = number; channel = In-app / Email. Target = a stock (symbol → the stock's id; reuse the stock search from the Stocks page for the picker, or a symbol lookup).

### Not this story
- **Inline edit** of a rule = delete + recreate in the UI (the QV-047 API has no PATCH; a real `PATCH /alerts/{id}` + enable/disable toggle is a fast-follow).
- Portfolio-scope rules (QV-048 evaluates stock scope only), a full notifications page/pagination (dropdown of recent only), per-notification read (mark-all on open), and the real **Brevo email e2e** smoke (create an email rule here → it fires → Brevo delivers) — verify once merged with the worker on `.env`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Backend: ruff+format/mypy(208)/imports clean, **449 passed / 5 skipped** (+2 notifications API). Frontend: tsc/eslint clean, **51 passed** (+2 AlertList), `next build` green.

### Completion Notes List

- **Mirrors saved-screens** for the alerts CRUD hooks/page; notifications API mirrors `routes_screens` (RLS tenant session) but is **also filtered to the current user** (a tenant can have several members — notifications are per-user).
- **Symbol↔id gap (the one real wrinkle):** the app works in symbols but `alert_rules.target_id` is a stock UUID. Fixed with two tiny read enrichments: `StockListItem.id` (the create form's stock-search picker returns the id → `target_id`) and `AlertRule.target_symbol` (a `LEFT JOIN stocks` so the list shows the symbol, not a UUID; `create` resolves it via a `RETURNING` subquery).
- **Limit-aware from `/me`:** `entitlements.alerts` is `3`/`50`/`null`(∞); page shows "N of MAX", disables create at the cap, and still handles the 403 `entitlement_exceeded` (defence + UX). Email opt-in = the per-rule channel select.
- **Notification bell** polls (60s), badges unread, marks-all-read on open (per-notification read deferred). No new component lib — native `<select>` + the existing `dropdown-menu`.
- **Deferred (documented):** inline edit/PATCH + enable-disable toggle (edit = delete+recreate today), a full notifications page/pagination, portfolio-scope targets. **Real Brevo email e2e** to verify once merged (create an email rule → fire → deliver).

### File List

- Backend: `alerts/repositories.py` (notifications reads + `target_symbol`), `schemas/notifications.py` (new), `api/routes_notifications.py` (new), `api/app.py` (router), `schemas/alerts.py` (`target_symbol`), `analytics/repositories.py` + `schemas/stocks.py` (`StockListItem.id`)
- Backend tests: `tests/integration/test_api_notifications.py` (new)
- Frontend: `app/(app)/alerts/page.tsx` (new), `features/alerts/AlertForm.tsx` / `AlertList.tsx` (new), `features/notifications/NotificationBell.tsx` (new), `components/app-nav.tsx` (Alerts link + bell), `components/auth-provider.tsx` (entitlements), `lib/api/queries.ts` (hooks + types), `lib/api/openapi.json` + `schema.d.ts` (regen)
- Frontend tests: `features/alerts/AlertList.test.tsx` (new)

### Change Log

- QV-050: Alerts management + notification center UI (user self-service) — `/alerts` page (create/list/delete rules, limit-aware, email opt-in) + a notification bell (unread badge, mark-read). New `GET /notifications` + `POST /notifications/read` API; `StockListItem.id` + `AlertRule.target_symbol` enrichments to bridge symbol↔id. Closes Epic 6. No migration.
