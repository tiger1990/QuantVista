-- QuantVista reference/seed data (idempotent).
-- Run after `alembic upgrade head`:  psql "$DATABASE_URL" -f seeds/seed_reference.sql
-- Entitlement values mirror the tier matrix in ../../plans/01-prd.md §4.
-- Exact limits/prices are O3 (config) and can change without code changes.

BEGIN;

-- ---- markets ----
INSERT INTO markets (code, name, country, currency, timezone, trading_calendar, is_active)
VALUES ('NSE', 'National Stock Exchange of India', 'IN', 'INR', 'Asia/Kolkata', 'NSE', true)
ON CONFLICT (code) DO UPDATE
    SET name = EXCLUDED.name, currency = EXCLUDED.currency, timezone = EXCLUDED.timezone;

-- ---- plans ---- (price_inr placeholder until O3 is finalized)
INSERT INTO plans (code, name, price_inr, billing_interval, is_active) VALUES
    ('free',  'Free',  0,    'month', true),
    ('pro',   'Pro',   0,    'month', true),
    ('quant', 'Quant', 0,    'month', true)
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, is_active = EXCLUDED.is_active;

-- ---- entitlements ----
-- Helper: upsert one entitlement (limit_int NULL = unlimited; flag_bool for capabilities).
-- limit_int = -1 is NOT used; NULL means "unlimited". Booleans use flag_bool.

-- FREE
WITH p AS (SELECT id FROM plans WHERE code = 'free')
INSERT INTO entitlements (plan_id, key, limit_int, flag_bool)
SELECT p.id, k.key, k.limit_int, k.flag_bool FROM p, (VALUES
    ('universe_scores_top', 50,   NULL),     -- top-50 only
    ('saved_screens',       3,    NULL),
    ('watchlists',          1,    NULL),
    ('watchlist_items',     10,   NULL),
    ('portfolios',          1,    NULL),
    ('alerts',              3,    NULL),
    ('news_history_days',   7,    NULL),
    ('optimization',        NULL, false),
    ('backtest',            NULL, false),
    ('api_access',          NULL, false),
    ('data_export',         NULL, false)
) AS k(key, limit_int, flag_bool)
ON CONFLICT (plan_id, key) DO UPDATE
    SET limit_int = EXCLUDED.limit_int, flag_bool = EXCLUDED.flag_bool;

-- PRO
WITH p AS (SELECT id FROM plans WHERE code = 'pro')
INSERT INTO entitlements (plan_id, key, limit_int, flag_bool)
SELECT p.id, k.key, k.limit_int, k.flag_bool FROM p, (VALUES
    ('universe_scores_top', NULL, NULL),     -- full universe
    ('saved_screens',       25,   NULL),
    ('watchlists',          10,   NULL),
    ('watchlist_items',     NULL, NULL),
    ('portfolios',          5,    NULL),
    ('alerts',              50,   NULL),
    ('news_history_days',   365,  NULL),
    ('optimization',        NULL, true),     -- MVO + Risk Parity
    ('optimization_advanced', NULL, false),  -- BL/HRP gated to Quant
    ('backtest',            NULL, true),     -- limited (1y presets), enforced in API
    ('backtest_full',       NULL, false),
    ('api_access',          NULL, false),
    ('data_export',         NULL, true)
) AS k(key, limit_int, flag_bool)
ON CONFLICT (plan_id, key) DO UPDATE
    SET limit_int = EXCLUDED.limit_int, flag_bool = EXCLUDED.flag_bool;

-- QUANT
WITH p AS (SELECT id FROM plans WHERE code = 'quant')
INSERT INTO entitlements (plan_id, key, limit_int, flag_bool)
SELECT p.id, k.key, k.limit_int, k.flag_bool FROM p, (VALUES
    ('universe_scores_top', NULL, NULL),
    ('saved_screens',       NULL, NULL),
    ('watchlists',          NULL, NULL),
    ('watchlist_items',     NULL, NULL),
    ('portfolios',          NULL, NULL),
    ('alerts',              NULL, NULL),
    ('news_history_days',   NULL, NULL),
    ('optimization',        NULL, true),
    ('optimization_advanced', NULL, true),   -- Black-Litterman / HRP, custom weights
    ('backtest',            NULL, true),
    ('backtest_full',       NULL, true),     -- custom range & strategy
    ('api_access',          NULL, true),
    ('data_export',         NULL, true)
) AS k(key, limit_int, flag_bool)
ON CONFLICT (plan_id, key) DO UPDATE
    SET limit_int = EXCLUDED.limit_int, flag_bool = EXCLUDED.flag_bool;

COMMIT;

-- Nifty 200 constituents are loaded separately by the data pipeline
-- (sync_index_constituents, sprint QV-019) with point-in-time effective_from/to + weights.
