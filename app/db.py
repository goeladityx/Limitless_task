"""
Database access. One rule: every query runs inside a transaction that has set the tenant,
and nothing else is allowed to open a connection.

The tenant is set with set_config(..., true). The trailing true makes it transaction-local,
so it is discarded at COMMIT and cannot leak through a pooled connection to whoever gets it
next. SET LOCAL cannot take a bind parameter, and interpolating a tenant id into SQL is the
exact bug this layer exists to prevent, so the function form is the only correct one.
"""

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar

import psycopg
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL",
                     "postgresql://pellet_app:pellet_app@localhost:5432/pellet")


# Every query a single answer runs is collected here, so the console can show the evaluator
# exactly what was executed. It is not for debugging: it is the claim that no number in this
# product came from anywhere except a query somebody can read.
_LOG: ContextVar = ContextVar("sql_log", default=None)


@contextmanager
def recording():
    token = _LOG.set([])
    try:
        yield _LOG.get()
    finally:
        _LOG.reset(token)


def _note(sql, params):
    log = _LOG.get()
    if log is None:
        return
    tidy = re.sub(r"\n\s+", "\n", sql.strip())
    log.append({"sql": tidy, "params": {k: str(v) for k, v in (params or {}).items()}})


@contextmanager
def tenant_cursor(tenant_id: str):
    """The only way into the database. Opens a transaction, pins the tenant, hands back a
    cursor. If tenant_id is wrong or missing, Postgres raises rather than returning rows."""
    with psycopg.connect(DSN, row_factory=dict_row) as cn:
        with cn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            yield cur
        cn.commit()


def fetch(tenant_id: str, sql: str, params=None):
    _note(sql, params)
    with tenant_cursor(tenant_id) as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def fetch_one(tenant_id: str, sql: str, params=None):
    rows = fetch(tenant_id, sql, params)
    return rows[0] if rows else None


def execute(tenant_id: str, sql: str, params=None):
    with tenant_cursor(tenant_id) as cur:
        cur.execute(sql, params or {})


def tenants():
    """Read as the owner, because the tenant list itself is not tenant-scoped."""
    admin = os.environ.get("ADMIN_DATABASE_URL",
                           "postgresql://postgres:postgres@localhost:5432/pellet")
    with psycopg.connect(admin, row_factory=dict_row) as cn, cn.cursor() as cur:
        cur.execute("SELECT tenant_id, name FROM tenant ORDER BY tenant_id")
        return cur.fetchall()
