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
    -- First row types the derived-table columns (limit_int int, flag_bool boolean).
    ('universe_scores_top', 50::int, NULL::boolean),  -- top-50 only
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
    ('universe_scores_top', NULL::int, NULL::boolean),  -- full universe (first row types the columns)
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
    ('universe_scores_top', NULL::int, NULL::boolean),  -- first row types the columns
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

-- ---- bootstrap Nifty universe (SUBSET, QV-005) ----
-- A small set of liquid Nifty large-caps so the universe exists before features and
-- early manual/dev testing has data. Global reference (no tenant_id, no RLS). The full
-- ~200 names, historical point-in-time membership, and weights are loaded by the data
-- pipeline (sync_index_constituents, QV-019) which supersedes this bootstrap.
INSERT INTO stocks (market_id, symbol, company_name, sector, is_active, listed_on)
SELECT m.id, v.symbol, v.company_name, v.sector, true, v.listed_on
FROM markets m, (VALUES
    ('RELIANCE',   'Reliance Industries Ltd',          'Energy',                 DATE '1977-11-29'),
    ('TCS',        'Tata Consultancy Services Ltd',    'Information Technology',  DATE '2004-08-25'),
    ('HDFCBANK',   'HDFC Bank Ltd',                    'Financial Services',     DATE '1995-11-08'),
    ('INFY',       'Infosys Ltd',                      'Information Technology',  DATE '1993-06-14'),
    ('ICICIBANK',  'ICICI Bank Ltd',                   'Financial Services',     DATE '1997-09-17'),
    ('HINDUNILVR', 'Hindustan Unilever Ltd',           'Fast Moving Consumer Goods', DATE '1956-01-01'),
    ('ITC',        'ITC Ltd',                          'Fast Moving Consumer Goods', DATE '1970-01-01'),
    ('SBIN',       'State Bank of India',              'Financial Services',     DATE '1994-03-01'),
    ('BHARTIARTL', 'Bharti Airtel Ltd',                'Telecommunication',      DATE '2002-02-18'),
    ('LT',         'Larsen & Toubro Ltd',              'Construction',           DATE '1950-01-01'),
    ('KOTAKBANK',  'Kotak Mahindra Bank Ltd',          'Financial Services',     DATE '1990-01-01'),
    ('AXISBANK',   'Axis Bank Ltd',                    'Financial Services',     DATE '1998-11-16')
) AS v(symbol, company_name, sector, listed_on)
WHERE m.code = 'NSE'
ON CONFLICT (market_id, symbol) DO UPDATE
    SET company_name = EXCLUDED.company_name,
        sector       = EXCLUDED.sector,
        is_active    = EXCLUDED.is_active;

-- Current NIFTY200 membership (point-in-time: effective_to NULL = active member).
-- Idempotent without a unique key via a WHERE NOT EXISTS guard on the open membership.
INSERT INTO index_constituents (index_code, stock_id, effective_from, effective_to)
SELECT 'NIFTY200', s.id, DATE '2024-01-01', NULL
FROM stocks s
JOIN markets m ON m.id = s.market_id AND m.code = 'NSE'
WHERE s.symbol IN (
        'RELIANCE','TCS','HDFCBANK','INFY','ICICIBANK','HINDUNILVR',
        'ITC','SBIN','BHARTIARTL','LT','KOTAKBANK','AXISBANK')
  AND NOT EXISTS (
        SELECT 1 FROM index_constituents ic
        WHERE ic.index_code = 'NIFTY200'
          AND ic.stock_id = s.id
          AND ic.effective_to IS NULL);

COMMIT;
