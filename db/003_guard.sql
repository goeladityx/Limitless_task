-- Step 5, part 3: the guard.
--
-- This is the part that still works in six months when somebody new adds a table and
-- forgets. It raises rather than warns, so a migration that leaves a table unprotected
-- fails the build instead of shipping.

DO $$
DECLARE
    missing_tenant text[];
    missing_rls    text[];
    missing_policy text[];
BEGIN
    -- every table in public must carry tenant_id, except the tenant list itself
    SELECT array_agg(c.relname ORDER BY c.relname) INTO missing_tenant
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND c.relname <> 'tenant'
      AND NOT EXISTS (
          SELECT 1 FROM pg_attribute a
          WHERE a.attrelid = c.oid AND a.attname = 'tenant_id' AND a.attnum > 0
      );

    -- and it must have row level security enabled AND forced
    SELECT array_agg(c.relname ORDER BY c.relname) INTO missing_rls
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND (c.relrowsecurity = false OR c.relforcerowsecurity = false);

    -- and an actual policy on it
    SELECT array_agg(c.relname ORDER BY c.relname) INTO missing_policy
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND NOT EXISTS (SELECT 1 FROM pg_policies p
                      WHERE p.schemaname = 'public' AND p.tablename = c.relname);

    IF missing_tenant IS NOT NULL THEN
        RAISE EXCEPTION 'tables without tenant_id: %', missing_tenant;
    END IF;
    IF missing_rls IS NOT NULL THEN
        RAISE EXCEPTION 'tables without ENABLE + FORCE row level security: %', missing_rls;
    END IF;
    IF missing_policy IS NOT NULL THEN
        RAISE EXCEPTION 'tables with no isolation policy: %', missing_policy;
    END IF;

    RAISE NOTICE 'tenant isolation guard passed';
END $$;
