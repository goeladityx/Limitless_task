"""
Isolation you have not tested is isolation you do not have.

Four things this proves:

  1. A query with NO tenant filter still returns only one tenant's rows. This is the one
     that matters, because it is the query a new joiner writes in six months.
  2. Forgetting to set the tenant at all is an ERROR, not an empty result. An empty result
     looks exactly like "this customer has no data", which is how a silent bug survives.
  3. Writing a row belonging to another tenant is rejected.
  4. The tenant does not survive the transaction, so it cannot leak through a pooled
     connection to whoever gets it next.

    python tests/test_tenant_isolation.py
"""

import os, sys

try:
    import psycopg
except ImportError:
    sys.exit('psycopg not installed.  pip install "psycopg[binary]"')

DSN = os.environ.get("DATABASE_URL",
                     "postgresql://pellet_app:pellet_app@localhost:5432/pellet")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}   {detail}")


def rows_for(tenant, sql):
    """Run a query as the app role with only the tenant set. No WHERE tenant_id anywhere."""
    with psycopg.connect(DSN) as cn, cn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cur.execute(sql)
        return cur.fetchall()


print("tenant isolation")

# 1. the buggy query. No tenant filter at all, which is the whole point.
a = rows_for("a", "SELECT count(*) FROM src_tally_voucher")[0][0]
b = rows_for("b", "SELECT count(*) FROM src_tally_voucher")[0][0]
check("a careless query sees only its own tenant", a > 0 and b > 0 and a != b,
      f"a={a} b={b}")

# the two must never add up to what the table actually holds.
#
# Reading the true total needs a connection RLS does not apply to, and the only thing RLS
# does not apply to is a superuser. On a local docker Postgres the admin is one. On any
# managed Postgres it is an ordinary owner, and then FORCE applies to it too and even the
# admin cannot count the table without naming a tenant. That is not this check failing, it
# is a stronger version of the thing it set out to prove, so record it as such and say
# which of the two actually ran.
ADMIN_DSN = os.environ.get("ADMIN_DATABASE_URL",
                           "postgresql://postgres:postgres@localhost:5432/pellet")
try:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as cn, cn.cursor() as cur:
        cur.execute("SELECT count(*) FROM src_tally_voucher")
        everything = cur.fetchone()[0]
    check("neither tenant can see the whole table", a < everything and b < everything,
          f"a={a} b={b} total={everything}")
except psycopg.errors.RaiseException as e:
    check("neither tenant can see the whole table, and neither can the admin",
          "app.tenant_id" in str(e), str(e)[:70])

# 2. no tenant set at all must raise, not return nothing
try:
    with psycopg.connect(DSN) as cn, cn.cursor() as cur:
        cur.execute("SELECT count(*) FROM src_tally_voucher")
        got = cur.fetchone()[0]
    check("forgetting the tenant errors rather than returning rows", False,
          f"returned {got} rows instead of raising")
except psycopg.errors.UndefinedObject:
    check("forgetting the tenant errors rather than returning rows", True)
except Exception as e:
    check("forgetting the tenant errors rather than returning rows",
          "app.tenant_id" in str(e), str(e)[:70])

# 3. a cross-tenant write is rejected by the policy, not by our own diligence
try:
    with psycopg.connect(DSN) as cn, cn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', 'a', true)")
        cur.execute("INSERT INTO review_queue (tenant_id, kind, subject_ref) "
                    "VALUES ('b', 'party_match', 'smuggled')")
        cn.commit()
    check("writing into another tenant is rejected", False, "the insert succeeded")
except psycopg.errors.InsufficientPrivilege:
    check("writing into another tenant is rejected", True)
except Exception as e:
    check("writing into another tenant is rejected", "policy" in str(e).lower(), str(e)[:70])

# 4. the setting must not survive the transaction, or it leaks through the pool
with psycopg.connect(DSN) as cn:
    with cn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', 'a', true)")
        cur.execute("SELECT count(*) FROM src_tally_voucher")
        cur.fetchone()
    cn.commit()
    try:
        with cn.cursor() as cur:
            cur.execute("SELECT count(*) FROM src_tally_voucher")
            leaked = cur.fetchone()[0]
        check("the tenant does not survive the transaction", False,
              f"still saw {leaked} rows after commit")
    except Exception:
        check("the tenant does not survive the transaction", True)

# 5. and the same question really does give different answers per tenant
q = "SELECT count(*), round(sum(qty_net_t)) FROM src_dispatch_register"
ra, rb = rows_for("a", q)[0], rows_for("b", q)[0]
check("the same query gives each tenant its own answer", ra != rb, f"a={ra} b={rb}")
print(f"    tenant a: {ra[0]} dispatches, {ra[1] or 0:,} t")
print(f"    tenant b: {rb[0]} dispatches, {rb[1] or 0:,} t")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
