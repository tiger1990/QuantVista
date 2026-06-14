# Data Models — QuantVista (DB layer)

> Documented from live code: `db/migrations/versions/0001`→`0012` + `db/seeds/seed_reference.sql`.
> Design reference: `plans/03-data-architecture.md`.

## Two data domains (the core rule)

| Domain | `tenant_id`? | RLS? | Written by | Tables |
|--------|--------------|------|-----------|--------|
| **Global reference / market** | No | No | Background jobs only | `markets`, `stocks`, `index_constituents`, `corporate_actions`, `macro_series`, `daily_prices`, `fundamentals`, `shareholding`, `technical_indicators`, `factor_values`, `scores`, `news`, `sentiment`, `plans`, `entitlements`, `audit_log`, `jobs_runs` |
| **Tenant-scoped** | Yes | **Yes (RLS)** | User actions | `tenants`, `users`, `memberships`, `subscriptions`, `portfolios`, `portfolio_positions`, `optimization_runs`, `risk_snapshots`, `watchlists`, `watchlist_items`, `saved_screens`, `alert_rules`, `alert_events`, `notifications`, `backtests` |

## Migration map

| Rev | Title | Introduces |
|-----|-------|-----------|
| `0001` | Extensions & helpers | `pgcrypto`, `btree_gin`; fns `app_current_tenant()`, `set_updated_at()`, `create_month_partition()` |
| `0002` | Identity, tenancy, billing | `tenants`, `users`, `memberships`, `plans`, `entitlements`, `subscriptions` + RLS on tenant-scoped |
| `0003` | Reference & market (global) | `markets`, `stocks` (survivorship-aware), `index_constituents` (PIT), `corporate_actions`, `macro_series` |
| `0004` | Prices (partitioned) | `daily_prices` — append-only, **monthly RANGE partition on `date`** |
| `0005` | Fundamentals (bitemporal PIT) | `fundamentals` (bitemporal), `shareholding` |
| `0006` | Indicators / factors / scores | `technical_indicators`, `factor_values`, `scores` — partitioned monthly, global |
| `0007` | News & sentiment | `news`, `sentiment` |
| `0008` | Portfolio & risk | `portfolios`, `portfolio_positions`, `optimization_runs`, `risk_snapshots` (RLS) |
| `0009` | Watchlists & screens | `watchlists`, `watchlist_items`, `saved_screens` (RLS) |
| `0010` | Alerts & notifications | `alert_rules`, `alert_events`, `notifications` (RLS) |
| `0011` | Backtests | `backtests` (RLS) |
| `0012` | Platform | `audit_log`, `jobs_runs` (global, append-mostly) |

## Tenant isolation (RLS)

- Each request runs `SET LOCAL app.tenant_id = '<uuid>'` inside its transaction.
- `app_current_tenant()` (rev `0001`) reads it: `NULLIF(current_setting('app.tenant_id', true), '')::uuid`.
- Policy pattern: `USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())`.
- `tenants` keys its policy on `id` (a tenant is its own boundary).
- **Every tenant-scoped table must have an RLS policy + a cross-tenant denial test** (CI gate).

## Point-in-time correctness

- **`fundamentals` is bitemporal:** `period_end` (what period the data describes) + `knowledge_from` /
  `knowledge_to` (when we knew it). A score for date D reads the row where
  `knowledge_from <= D < knowledge_to`. Revisions insert a new version and close the prior one.
  Unique index `uq_fundamentals_open` enforces exactly one open version per `(stock_id, period_end, statement_type)` (`knowledge_to IS NULL`).
- **`stocks.delisted_on`** keeps delisted names queryable → survivorship-bias-free history.
- **`index_constituents`** uses `effective_from` / `effective_to` (NULL = current) → backtests read the
  *historical* Nifty 200 membership, not today's.

## Partitioning

- `daily_prices`, `technical_indicators`, `scores` are **PARTITION BY RANGE (`date`)**, monthly.
- `create_month_partition(parent, month_start)` (rev `0001`) creates idempotent partitions named
  `<parent>_YYYY_MM`; a DEFAULT partition catches out-of-range rows.
- Old partitions can be detached/archived to Parquet on S3/MinIO (data-lake phase).

## Conventions

- UUID PKs via `gen_random_uuid()`. Money/weights = `NUMERIC` (never float). `updated_at` maintained by
  the `set_updated_at()` trigger. Constraint/index naming follows `env.py` (`ix_`, `uq_`, `ck_`, `fk_`, `pk_`).
- Migrations are **hand-written DDL** (partitioning, bitemporal, RLS) — `target_metadata = None`, so
  Alembic autogenerate is OFF until ORM models exist.

## Seed data

`db/seeds/seed_reference.sql` — idempotent: `markets` (NSE), `plans` (free/pro/quant), `entitlements`,
and PIT `index_constituents` for NIFTY200. Re-running is a no-op.
