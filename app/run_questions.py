"""
The test script the brief asks for: runs all twenty questions and prints how many were
right, how many were withheld, how many were wrong.

    python -m app.run_questions          both tenants
    python -m app.run_questions a        one tenant
    python -m app.run_questions a -v     with the full answers

What "wrong" means here matters. It is not just a bad number. Refusing something the answer
key says is answerable counts as wrong too, because a system that refuses everything scores
zero wrong and is useless. Coverage is printed alongside, for the same reason.
"""

import sys

from . import answer, db, questions


def run_tenant(tid, name, verbose=False):
    right = withheld_ok = wrong = 0
    print(f"\n{'=' * 78}\n  {tid.upper()}  {name}\n{'=' * 78}")

    for q in questions.resolve(tid):
        a = answer.run(tid, q["metric"], q["params"])
        got, want = a["verdict"], q["expect"]
        ok = got == want

        if not ok:
            wrong += 1
            mark = "WRONG"
        elif got == "withheld":
            withheld_ok += 1
            mark = "withheld"
        else:
            right += 1
            mark = "answered"

        print(f"\n  {q['id']:<4} {mark:<9} {q['ask']}")
        if not ok:
            print(f"       expected {want}, got {got}")
        if a.get("gate_failed"):
            print(f"       GATE: {a['gate_failed']}")
        if verbose or not ok:
            for line in a["text"].split("\n"):
                print(f"       {line}")
            if a.get("fix"):
                print(f"       -> {a['fix']}")
        elif got == "withheld":
            print(f"       because: {a.get('reason')}")

    total = right + withheld_ok + wrong
    print(f"\n  {'-' * 74}")
    print(f"  {total} questions  |  {right} answered  |  {withheld_ok} withheld  |  {wrong} wrong")
    print(f"  coverage {right / total * 100:.0f}%   "
          f"{'PASS' if wrong == 0 else 'FAIL, and a wrong number is the one thing that must never happen'}")
    return wrong


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv
    rows = db.tenants()
    if args:
        rows = [r for r in rows if r["tenant_id"] in args]
    bad = sum(run_tenant(r["tenant_id"], r["name"], verbose) for r in rows)
    print()
    sys.exit(1 if bad else 0)
