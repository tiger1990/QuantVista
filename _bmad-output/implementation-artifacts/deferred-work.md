# Deferred Work

Tracks items deferred during code review that are real but not actionable in the current story.

---

## Deferred from: code review of 7-2-qv-052-portfolio-crud-api (2026-07-13)

- **TOCTOU in `idempotent()`**: Both concurrent `produce()` calls execute before the UNIQUE guard fires; the rollback is correct for DB-only side effects, but if a future caller of `idempotent()` has external side effects (email, webhooks), duplicates are possible. Document constraint in `api/idempotency.py` docstring and address when adopting for alerts/screens routes.
- **Quota race on `POST /portfolios`**: `count_portfolios` + `enforce_portfolio_limit` is not serializable under concurrent creates. Two requests from the same Free-tier tenant can both read count=0, both pass, both insert — exceeding the quota by 1. Fix requires `SELECT count(*) FOR UPDATE` or a `SERIALIZABLE` transaction. Defer to a hardening sprint.
- **No TTL/expiry on `idempotency_keys`**: The table grows without bound. Add an `expires_at` column and a pg_cron cleanup job (or APScheduler beat task) before the table exceeds millions of rows in production.
- **Session rollback model**: `idempotent()` issues `session.rollback()` after `IntegrityError`; correctness depends on the calling session using `autocommit=False` (standard SQLAlchemy). This is true today but should be documented in the helper's docstring.
- **`p['target_weight']` psycopg type coercion**: The `cast()` in `routes_portfolios.py` is a mypy cast only. If psycopg ever returns NUMERIC as `str` instead of `Decimal`, the weight sum would be computed over strings. Confirm driver config + add an explicit `Decimal(str(v))` coercion if driver behavior changes.
