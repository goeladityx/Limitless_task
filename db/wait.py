"""
Is Postgres up yet?

Exits 0 as soon as it can connect, 1 if it never can. The launcher uses this both to decide
whether it needs to start a database at all, and to wait for one it has just started.

    python db/wait.py            check once
    python db/wait.py 60         keep trying for sixty seconds
"""

import os
import sys
import time

try:
    import psycopg
except ImportError:
    sys.exit("psycopg is not installed")

DSN = os.environ.get("ADMIN_DATABASE_URL",
                     "postgresql://postgres:postgres@localhost:5432/pellet")

deadline = time.time() + (float(sys.argv[1]) if len(sys.argv) > 1 else 0)
while True:
    try:
        psycopg.connect(DSN, connect_timeout=2).close()
        sys.exit(0)
    except Exception:                                          # noqa: BLE001
        if time.time() >= deadline:
            sys.exit(1)
        time.sleep(2)
