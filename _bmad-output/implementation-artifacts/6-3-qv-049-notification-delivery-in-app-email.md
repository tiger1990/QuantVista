---
baseline_commit: 27361b0
---

Status: review

# QV-049 — Notification delivery (in-app + email)

**Epic:** EPIC-ALERT (Epic 6) · **Points:** 5 · **Depends:** QV-048 (alert_events fired ✓)

## Story

As a user, I want alerts delivered, so I act on them.

## Acceptance Criteria

1. `INotificationChannel` with two impls: **in-app** (writes the 0010 `notifications` table) and **email** (via a plug-and-play `IEmailSender`: `log` dev/CI, **`brevo`** real provider, `ses` later — chosen by `EMAIL_PROVIDER`).
2. **Channel honored from the rule** — each pending `alert_event` is delivered via *its rule's* `channel`.
3. **Delivery status + retries** — on success mark `alert_events.status='delivered'` + `delivered_at`; on failure `status='failed'` (per-event isolation, one bad delivery never blocks the rest); a later run re-attempts `failed` events (idempotent).
4. Triggered by **`AlertsFired`** (thin consumer → `.delay()`), so notifications follow within the cycle; recorded under the QV-015 job framework.
5. Runs cross-tenant on the **privileged (RLS-bypassing) session** (like QV-048); in-app rows written under each event's own `tenant_id`/`user_id`.

## Tasks / Subtasks

- [x] **Task 1 — channels** (AC: #1, #2)
  - [x] `DeliveryTarget` + `INotificationChannel.deliver(target)` in `interfaces.py`; `alerts/channels.py`: `InAppChannel(session)` (insert `notifications`), `EmailChannel(sender)`, `IEmailSender` + `LogEmailSender` (dev). (Config knob deferred with the real SES/Resend sender — `LogEmailSender` is the hardcoded default.)
- [x] **Task 2 — repository** (AC: #2, #3, #5)
  - [x] `alerts/repositories.py`: `pending_alert_events` (join events→rules→users, status IN ('pending','failed')); `mark_alert_event` (+ `delivered_at` when delivered); `insert_notification`.
- [x] **Task 3 — delivery service** (AC: #2, #3, #5)
  - [x] `alerts/services.py`: `NotificationDeliveryService(email_sender).deliver_pending()` — privileged session → dispatch by `channel` → per-event SAVEPOINT (a failure isolates + marks `failed`) → return delivered count.
- [x] **Task 4 — job + trigger** (AC: #4)
  - [x] `jobs/alerts.py::deliver_notifications()` under `run_job` (per-second key). `on_alerts_fired` `.delay()`s it; subscribed `AlertsFired`.
- [x] **Task 5 — tests + gates + reconcile** (AC: all)
  - [x] Integration `test_deliver_notifications.py`: in-app → `notifications` row + `delivered`; email → spy sender + `delivered`; **channel honored** (email hits sender, in-app hits table); failing sender → `failed`, re-run **retries** → `delivered` (+`delivered_at`); cross-tenant. Gates green (441 passed). QV-048 → done reconcile on this branch.

## Dev Notes

### Channels behind one seam
`INotificationChannel.deliver(target)` — `InAppChannel` inserts a `notifications` row (0010, RLS but written on the privileged session with explicit tenant_id); `EmailChannel` calls an injected `IEmailSender`. The **real SES/Resend sender is deferred** (no creds in dev — same posture as AWS/FinBERT); dev/CI use `LogEmailSender` (logs the send, counts as delivered). The delivery service maps `rule.channel` → the channel impl, so the rule's choice is honored.

### Pending + retry
`pending_alert_events` selects `status IN ('pending','failed')`, so each `AlertsFired` run delivers new events **and** re-attempts previously-failed ones — retries without a scheduler. Per-event try/except → one failing recipient marks only that event `failed` and the rest still deliver. Delivery is idempotent-ish: a `delivered` event is never re-selected.

### Cross-tenant, like QV-048
Runs on `privileged_session_scope()` (superuser bypasses RLS) to read every tenant's pending events and write `notifications` under each event's own tenant. `AlertsFired` → `on_alerts_fired` → `deliver_notifications.delay()`.

### Not this story
- Alerts management + notification-center **UI** = QV-050. Read/unread + a `GET /notifications` API = QV-050/later.
- Webhooks/Slack channels (Quant tier), real SES/Resend live wiring (a PV like AWS), scheduled retry/backoff beyond the per-event re-attempt.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Gates: ruff + format clean · mypy clean (203 files) · import-linter 3/3 · pytest **441 passed / 5 skipped** (+3 delivery integration).
- Bug caught: structlog reserves the first positional as `event`, so a `event=` kwarg collides → renamed to `event_id=`.

### Completion Notes List

- **One seam, two channels:** `INotificationChannel.deliver(target)` (evolved from the placeholder `send`); `InAppChannel` holds the session and writes `notifications`, `EmailChannel` holds an `IEmailSender`. The service maps `rule.channel` → the impl, so the rule's choice is honored.
- **Plug-and-play email provider** (`alerts/email.py`): `IEmailSender` + `get_email_sender(settings)` picks by `EMAIL_PROVIDER` — `log` (dev/CI default, no creds), **`brevo`** (transactional REST API via stdlib `urllib`, like the news providers; 300/day free), and `ses` is a future one-class + one-branch add. Real send needs `BREVO_API_KEY` (gitignored `.env`) + a Brevo-verified `EMAIL_FROM`. A non-2xx raises → the event is marked `failed` and retried. `.env.example` documents the keys. Unit-tested with a mocked `urlopen` (request shape + api-key header + HTTP-error path).
- **Per-event SAVEPOINT** (`begin_nested`) isolates a failed delivery — it rolls back that event's partial write and marks it `failed` without aborting the run; `pending_alert_events` re-selects `failed` so the next `AlertsFired` **retries** it (no scheduler). A `delivered` event is never re-selected (idempotent).
- **Cross-tenant on the privileged session** (like QV-048); in-app rows written under each event's own tenant. `AlertsFired` → `on_alerts_fired` → `deliver_notifications.delay()`. **No migration** (`notifications` + `alert_events.status/delivered_at` are in 0010).

### File List

- `backend/src/quantvista/alerts/interfaces.py` — `DeliveryTarget` + `INotificationChannel.deliver`
- `backend/src/quantvista/alerts/channels.py` (new) — `InAppChannel`, `EmailChannel`
- `backend/src/quantvista/alerts/email.py` (new) — `IEmailSender`, `LogEmailSender`, `BrevoEmailSender`, `get_email_sender`
- `backend/src/quantvista/core/config.py` — `email_provider`/`email_from`/`email_from_name`/`brevo_api_key`; `.env.example`
- `backend/tests/test_email_sender.py` (new) — factory + Brevo request-shape/error unit tests
- `backend/src/quantvista/alerts/repositories.py` — `pending_alert_events`, `mark_alert_event`, `insert_notification`
- `backend/src/quantvista/alerts/services.py` — `NotificationDeliveryService`
- `backend/src/quantvista/jobs/alerts.py` — `deliver_notifications` task
- `backend/src/quantvista/jobs/consumers.py` — `on_alerts_fired` (+ AlertsFired subscribe)
- `backend/tests/integration/test_deliver_notifications.py` (new)

### Change Log

- QV-049: Notification delivery — `INotificationChannel` (in-app `notifications` + email via an injectable sender; real SES/Resend deferred, `LogEmailSender` in dev); cross-tenant `NotificationDeliveryService` delivers pending/failed `alert_events` by their rule's channel, marks per-event status (+`delivered_at`), retries failed on the next `AlertsFired`. Completes the alerts pipeline (rule → fire → notify). No migration.
