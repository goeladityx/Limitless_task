"""
One command from an empty database to a console you can click.

    python setup.py

It creates the schema, loads both companies, resolves what can be resolved by rule, queues
what cannot, reads the vendor emails, seeds the definitions, and then runs the three test
suites. If any of them fails it stops and says so, because a demo that starts with a broken
number is worse than one that does not start.

Assumes Postgres is up and DATABASE_URL points at it. docker compose up -d does that.
"""

import os
import subprocess
import sys

REGENERATE = [
    ("rebuild the truth, tenant a",  [sys.executable, "truth_gen.py", "a"]),
    ("rebuild the truth, tenant b",  [sys.executable, "truth_gen.py", "b"]),
    ("rebuild the sources, tenant a", [sys.executable, "make_sources.py", "a"]),
    ("rebuild the sources, tenant b", [sys.executable, "make_sources.py", "b"]),
]
STEPS = [
    ("schema and data",     [sys.executable, "db/load.py"]),
    ("definitions",         [sys.executable, "-m", "app.definitions"]),
    ("resolve tenant a",    [sys.executable, "-m", "app.canonical", "a"]),
    ("resolve tenant b",    [sys.executable, "-m", "app.canonical", "b"]),
    ("read the emails, a",  [sys.executable, "-m", "app.extract", "a"]),
    ("read the emails, b",  [sys.executable, "-m", "app.extract", "b"]),
]
CHECKS = [
    ("the twenty questions", [sys.executable, "-m", "app.run_questions"]),
    ("every answer audited", [sys.executable, "-m", "app.audit"]),
    ("definitions and queue wiring", [sys.executable, "-m", "app.test_wiring"]),
    # runs on its own, so a clone with the three listed dependencies proves isolation
    # without needing a test runner installed as well
    ("tenant isolation",     [sys.executable, "tests/test_tenant_isolation.py"]),
]


def run(label, cmd, fatal=True):
    print(f"\n=== {label}")
    r = subprocess.run(cmd)
    if r.returncode and fatal:
        print(f"\n  {label} failed. Stopping here rather than serving a broken number.")
        sys.exit(r.returncode)
    return r.returncode


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL",
                          "postgresql://pellet_app:pellet_app@localhost:5432/pellet")
    os.environ.setdefault("ADMIN_DATABASE_URL",
                          "postgresql://postgres:postgres@localhost:5432/pellet")
    # sources/ is committed, so a clone runs without this. Pass --regenerate to rebuild it
    # from seed_inputs/, which is how you change the company: edit a CSV, run this again.
    if "--regenerate" in sys.argv:
        run("contract book", [sys.executable, "seed_contracts.py"])
        for label, cmd in REGENERATE:
            run(label, cmd)
    for label, cmd in STEPS:
        run(label, cmd)
    failed = [label for label, cmd in CHECKS if run(label, cmd, fatal=False)]
    print()
    if failed:
        print("  these checks did not pass: " + ", ".join(failed))
        sys.exit(1)
    print("  everything passes. Start it with:")
    print("      python -m uvicorn app.api:app --port 8000")
    print("  then open http://localhost:8000")
