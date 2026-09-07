"""
Step 6: run the migrations, then load sources/ into Postgres for both tenants.

    python db/load.py

Needs a running Postgres and psycopg 3:

    docker compose up -d db
    pip install "psycopg[binary]"

Two things worth knowing about how this loads.

Nothing is cleaned on the way in. Dates stay as the text Tally wrote, quantities stay in
quintals, party names stay as somebody typed them. If we tidied here, the product would be
grading itself on data we had already fixed, and we would lose the ability to show a
controller the row exactly as it appears in his own system.

The loader sets the tenant per transaction like everything else, using SET LOCAL. It does
not get a bypass. If a table were left unprotected, the guard in 003 would already have
failed the migration.
"""

import csv, os, sys, pathlib

try:
    import psycopg
except ImportError:
    sys.exit('psycopg not installed.  pip install "psycopg[binary]"')

DSN = os.environ.get("DATABASE_URL",
                     "postgresql://pellet_app:pellet_app@localhost:5432/pellet")
ADMIN_DSN = os.environ.get("ADMIN_DATABASE_URL",
                           "postgresql://postgres:postgres@localhost:5432/pellet")
ROOT = pathlib.Path(__file__).resolve().parent.parent

TENANTS = {"a": ("sources", "Marudhar Biofuels Pvt Ltd"),
           "b": ("sources_b", "Saurashtra Green Pellets LLP")}

# csv file -> table, and which columns are real dates that Postgres should parse.
# Anything not listed stays exactly as it was written.
FILES = [
    ("tally_ledger",          "src_tally_ledger",          []),
    ("tally_stock_item",      "src_tally_stock_item",      []),
    ("tally_voucher",         "src_tally_voucher",         []),
    ("tally_inventory_entry", "src_tally_inventory_entry", []),
    ("dispatch_register",     "src_dispatch_register",     ["dispatch_date"]),
    ("production_register",   "src_production_register",   []),
    ("tender_award",          "src_tender_award",          ["window_start", "window_end"]),
    ("contract_schedule",     "src_contract_schedule",     []),
    ("buyer_terms",           "src_buyer_terms",           []),
    ("config",                "src_config",                []),
    ("goods_receipt",         "src_goods_receipt",         ["received_date"]),
    ("emails",                "src_email",                 ["sent_at"]),
]


def run_migrations():
    """Migrations run as the owner, which bypasses RLS. That is unavoidable and it is why
    003_guard.sql exists: the owner can create a table without protection, so something
    has to fail the build when it happens."""
    for name in ("001_schema.sql", "002_rls.sql", "003_guard.sql"):
        sql = (ROOT / "db" / name).read_text(encoding="utf-8")
        with psycopg.connect(ADMIN_DSN, autocommit=True) as cn:
            with cn.cursor() as cur:
                cur.execute(sql)
        print(f"  {name}")


def load_tenant(tid, folder, name):
    src = ROOT / folder
    if not src.exists():
        print(f"  {folder}/ missing, skipping tenant {tid}")
        return

    # The tenant registry carries a tenant_id of its own, so FORCE row level security
    # applies to this insert exactly like any other. It ran for months without setting the
    # tenant only because the admin on a local docker Postgres is a superuser, and a
    # superuser is the one thing RLS does not apply to. Point it at a managed Postgres,
    # where the admin is an ordinary owner, and this raises. Which is the policy working:
    # forgetting the tenant is supposed to be noisy. So set it, the way everything else does.
    with psycopg.connect(ADMIN_DSN) as cn:
        with cn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tid,))
            cur.execute("INSERT INTO tenant (tenant_id, name) VALUES (%s, %s) "
                        "ON CONFLICT (tenant_id) DO UPDATE SET name = EXCLUDED.name", (tid, name))
        cn.commit()

    total = 0
    with psycopg.connect(DSN) as cn:
        with cn.cursor() as cur:
            # set_config(..., true) is SET LOCAL with a bind parameter. The trailing true
            # is what makes it local: discarded at COMMIT, so it cannot leak into whoever
            # gets this pooled connection next. SET LOCAL itself takes no parameters, and
            # interpolating a tenant id into SQL is exactly the bug this whole layer exists
            # to prevent.
            cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tid,))

            for fname, table, datecols in FILES:
                path = src / f"{fname}.csv"
                if not path.exists():
                    continue
                with open(path, newline="", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                if not rows:
                    continue

                # Scoped explicitly, not left to the policy. The row level security on
                # this table would normally confine the delete to the tenant we just set,
                # but that is only true for a connection the policy applies to. Run the
                # loader as a superuser and RLS silently stops applying, at which point
                # loading the second tenant deletes the first one's rows and the failure
                # looks like "that company has no data". Naming the tenant costs nothing
                # and does not depend on who is connected.
                cur.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tid,))
                cols = ["tenant_id"] + list(rows[0].keys())
                ph = ", ".join(["%s"] * len(cols))
                stmt = f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({ph})'

                batch = []
                for r in rows:
                    vals = [tid]
                    for c in rows[0].keys():
                        v = r[c]
                        # empty string is a real signal here: a blank tender_ref means
                        # nobody wrote the contract down. Keep it as NULL, not "".
                        vals.append(None if v == "" else v)
                    batch.append(vals)
                cur.executemany(stmt, batch)
                total += len(batch)
                print(f"    {table:<28} {len(batch):>6}")
        cn.commit()
    print(f"  tenant {tid}: {total} rows")


if __name__ == "__main__":
    print("migrations")
    run_migrations()
    for tid, (folder, name) in TENANTS.items():
        print(f"loading tenant {tid} from {folder}/")
        load_tenant(tid, folder, name)
    print("done")
