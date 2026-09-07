-- Step 5, part 2: tenant isolation.
--
-- The point is not to stop an attacker. It is to stop a query somebody writes wrong in six
-- months. Application-level filtering fails the moment one person forgets a WHERE clause.
-- Postgres row level security cannot be forgotten, because the database applies it.
--
-- Three properties this has to have:
--
--   1. It fails CLOSED. If nobody set the tenant, the query errors. It does not quietly
--      return everything, and it does not quietly return nothing either.
--   2. FORCE, so it applies to the table owner too. Otherwise migrations and any script
--      running as the owner sail straight through.
--   3. Set per TRANSACTION, not per session. Transaction-mode pooling (PgBouncer) hands
--      the same server connection to different clients, so session state leaks between
--      tenants. SET LOCAL inside the transaction is the only version that is safe.

BEGIN;

-- The app connects as this role. It deliberately does NOT have BYPASSRLS, and it is not
-- the owner of any table, so FORCE applies to it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pellet_app') THEN
        CREATE ROLE pellet_app LOGIN PASSWORD 'pellet_app';
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO pellet_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pellet_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pellet_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pellet_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO pellet_app;

-- Fails closed, and does it loudly.
--
-- Two cases have to raise, not return nothing:
--   the tenant was never set on this connection      -> current_setting would raise anyway
--   a previous transaction set it and then committed -> the GUC resets to empty string,
--                                                       and current_setting stops raising
--
-- The second one is the trap. It leaves you with a policy that matches nothing, so the
-- query returns zero rows, which looks exactly like "this customer has no data". That is
-- how a silent bug survives for months. So check for empty and raise explicitly.
CREATE OR REPLACE FUNCTION current_tenant() RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v text;
BEGIN
    v := current_setting('app.tenant_id', true);
    IF v IS NULL OR v = '' THEN
        RAISE EXCEPTION 'app.tenant_id is not set for this transaction'
            USING HINT = 'SELECT set_config(''app.tenant_id'', $1, true) at the start of the transaction';
    END IF;
    RETURN v;
END $$;

-- Apply the same policy to every tenant-scoped table. Doing it in a loop rather than by
-- hand means a table added later cannot be missed by accident, and 003_guard.sql fails
-- the build if one ever is.
DO $$
DECLARE t text;
BEGIN
    FOR t IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'
        WHERE n.nspname = 'public' AND c.relkind = 'r'
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I
                 USING (tenant_id = current_tenant())
                 WITH CHECK (tenant_id = current_tenant())', t);
    END LOOP;
END $$;

-- One deliberate exception, stated out loud rather than left as an accident.
--
-- The tenant registry is control plane, not customer data. It is what the connection
-- dependency reads to find out which tenants exist, and it has to be readable BEFORE a
-- tenant has been chosen, which is the one moment current_tenant() cannot answer. It kept
-- working locally only because the admin on a docker Postgres is a superuser, and a
-- superuser is the single thing RLS does not apply to. Point it at any managed Postgres,
-- where the admin is an ordinary owner, and every screen dies on the tenant list.
--
-- So the table keeps row level security enabled AND forced, 003_guard.sql still covers it,
-- and it carries one extra policy making the list of tenants readable. Policies are OR'd
-- for SELECT, so this widens reads only. Writes stay tenant scoped through the WITH CHECK
-- on tenant_isolation. What it exposes is which tenants exist and what they are called,
-- which is what the company selector at the top of the console already shows on purpose.
-- No row of anybody's accounting is reachable through it.
DROP POLICY IF EXISTS tenant_registry_readable ON tenant;
CREATE POLICY tenant_registry_readable ON tenant FOR SELECT USING (true);

COMMIT;

-- How the application uses it, and the only correct way:
--
--     BEGIN;
--     SELECT set_config('app.tenant_id', $1, true);   -- true means LOCAL
--     ... every query for this request ...
--     COMMIT;
--
-- set_config with a trailing true is SET LOCAL that accepts a bind parameter. SET LOCAL
-- itself takes no parameters, and interpolating a tenant id straight into SQL is exactly
-- the class of bug this layer exists to prevent, so the function form is the only correct
-- one. Local means it is discarded at COMMIT and cannot leak into whoever gets this pooled
-- connection next. One place in the code sets it, a connection dependency, and nothing
-- else is allowed to.
--
-- What this costs us, stated plainly because it is not free:
--
--   Migrations run as the owner with BYPASSRLS, so RLS does not protect us from our own
--   DDL. A bad migration can still cross tenants.
--
--   Debugging gets harder. An empty result means either "no data" or "wrong tenant" and
--   the result itself cannot tell you which.
--
--   Every index has to lead with tenant_id or plans degrade, because the policy predicate
--   is evaluated on every scan.
--
--   Anything outside a request (the loader, a cron job, a backfill) has to set the tenant
--   explicitly, and forgetting produces an error rather than silence. That is noisy, and
--   the noise is the feature.
--
-- Rejected alternative: a schema per tenant. Better isolation, but it multiplies every
-- migration by the number of tenants, and at that point the migrations become the thing
-- most likely to break.
