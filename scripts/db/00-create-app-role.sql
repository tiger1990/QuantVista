-- Postgres initdb hook (runs once, as the POSTGRES_USER admin role, on first boot).
-- Creates a NON-superuser, NON-BYPASSRLS application role so Row-Level Security
-- actually enforces tenant isolation locally (project-context.md rule #2). The app
-- (api/worker/beat) connects as this role; migrations/seed run as the admin role.
--
-- Credentials here are LOCAL-DEV ONLY and match .env.example. Never reuse in cloud.

CREATE ROLE quantvista_app WITH LOGIN PASSWORD 'quantvista_app' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE quantvista TO quantvista_app;
GRANT USAGE ON SCHEMA public TO quantvista_app;

-- Tables/sequences are created later by `alembic upgrade head` (run as the admin role).
-- Grant the app role DML on everything the admin creates, going forward.
ALTER DEFAULT PRIVILEGES FOR ROLE quantvista IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO quantvista_app;
ALTER DEFAULT PRIVILEGES FOR ROLE quantvista IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO quantvista_app;
