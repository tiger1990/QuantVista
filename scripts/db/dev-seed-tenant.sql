-- OPTIONAL local-dev convenience: seed one demo tenant + user + watchlist so there is
-- something to explore in psql / pgAdmin and to point early manual API tests at.
--
-- This is NOT reference data and is NOT run automatically (not by compose, not by CI).
-- Real tenants are created via user registration (QV-006). Safe to re-run (idempotent).
-- Run as the admin/superuser role:
--   psql "$ADMIN_DATABASE_URL" -f scripts/db/dev-seed-tenant.sql
-- Then, as the app role, with app.tenant_id set to the tenant below, you will see its rows.

INSERT INTO tenants (id, name)
VALUES ('00000000-0000-0000-0000-0000000000aa', 'tenant-test')
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, email, status, mfa_enabled, created_at, updated_at)
VALUES ('00000000-0000-0000-0000-0000000000bb', 'dev@tenant-test.local', 'active', false, now(), now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO watchlists (id, tenant_id, user_id, name, created_at)
VALUES ('00000000-0000-0000-0000-0000000000cc',
        '00000000-0000-0000-0000-0000000000aa',
        '00000000-0000-0000-0000-0000000000bb',
        'My First Watchlist', now())
ON CONFLICT (id) DO NOTHING;
