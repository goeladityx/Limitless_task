"""
Prove that changing a definition, or answering a question in the review queue, actually
moves the numbers.

Both of those claims are easy to make and easy to get wrong. A metric can declare it needs a
definition and never read it. A review decision can be written to a table nothing queries.
In either case every screen still looks right and the product is quietly lying about what it
is doing.

So this changes things for real, against the live database, and asserts the answers moved:

    1. flip a definition, re-ask, and require the figure to change
    2. answer a review item, re-ask, and require the refusal to become an answer
    3. put both back, and require the numbers to return to exactly what they were

Run:  python -m app.test_wiring
"""

import json
import sys

from . import answer, db, definitions, metrics


def figure(a):
    """The headline figure, as a number, so two answers can be compared."""
    return round(sum(float(v) for v in (a.get("numbers") or {}).values()
                     if isinstance(v, (int, float))), 4)


def check(name, ok, detail=""):
    print(f"  {'pass' if ok else 'FAIL'}  {name}")
    if detail:
        print(f"          {detail}")
    return 0 if ok else 1


def definition_wiring(tid):
    """Change what a word means and the answers that depend on it have to move."""
    bad = 0
    print(f"\n  definitions, tenant {tid}")

    before = definitions.load(tid)["order_book"]["params"]
    flipped = dict(before, apply_option_clause=not before["apply_option_clause"])

    a1 = answer.run(tid, "order_book", {})
    definitions.set_definition(tid, "order_book", flipped, who="test_wiring")
    a2 = answer.run(tid, "order_book", {})
    definitions.set_definition(tid, "order_book", before, who="test_wiring")
    a3 = answer.run(tid, "order_book", {})

    bad += check("flipping the option clause moves the order book",
                 a1["raw"]["owed_t"] != a2["raw"]["owed_t"],
                 f"{a1['raw']['owed_t']:,.1f} t -> {a2['raw']['owed_t']:,.1f} t")
    bad += check("putting it back restores the figure exactly",
                 a1["raw"]["owed_t"] == a3["raw"]["owed_t"],
                 f"{a3['raw']['owed_t']:,.1f} t")
    bad += check("the answer says which rule it used",
                 a1["definitions_used"]["order_book"]["params"]["apply_option_clause"]
                 != a2["definitions_used"]["order_book"]["params"]["apply_option_clause"])

    # a metric that declares a definition must actually read it, or the layer is decoration
    unread = []
    src = open(metrics.__file__, encoding="utf-8").read()
    for name, spec in metrics.REGISTRY.items():
        for word in spec.get("needs", []):
            body = src[src.index(f'def {name}('):]
            body = body[:body.index("\n@metric(")] if "\n@metric(" in body else body
            if f'defs["{word}"]' not in body and f"defs['{word}']" not in body:
                # a metric may read it through another metric it calls
                if not any(f"{other}(db, tid, defs" in body for other in metrics.REGISTRY):
                    unread.append(f"{name} declares {word} and never reads it")
    bad += check("every metric that declares a definition reads it",
                 not unread, "; ".join(unread))

    # a definition the schema does not describe is a code change, not a setting
    try:
        definitions.set_definition(tid, "order_book", dict(before, made_up=True))
        bad += check("a setting outside the schema is rejected", False, "it was accepted")
    except ValueError:
        bad += check("a setting outside the schema is rejected", True)
    return bad


def review_wiring(tid):
    """Answer a question in the queue and the number it was blocking has to change."""
    bad = 0
    print(f"\n  review queue, tenant {tid}")

    item = db.fetch_one(tid, """
        SELECT review_id, subject_ref, proposal FROM review_queue
        WHERE kind = 'dispatch_tender' AND status = 'open'
        ORDER BY review_id LIMIT 1""")
    if not item:
        print("          nothing open to test with")
        return 0
    options = (item["proposal"] or {}).get("options") or []
    if not options:
        print("          the open item has no options, nothing to choose")
        return 0

    # Take the option whose contract is STILL OPEN, not simply the first one.
    #
    # This mattered more than it looks. The first option is the contract that has just
    # closed, and placing a load there is often the right answer but it cannot change what
    # is still owed, because nothing is owed on a closed contract. So this test used to
    # answer the queue, watch the doubt narrow, and never once look at the headline figure.
    #
    # That is exactly the gap a real bug walked through: order_book credited a load only
    # when the register named the contract, and ignored dispatch_tender entirely. Answering
    # an item moved the count of open questions and left the tonnage frozen. Every suite
    # passed. Somebody clicking the product found it in a minute.
    live = db.fetch(tid, """
        SELECT tender_ref FROM src_tender_award
        WHERE tender_ref = ANY(%(refs)s) AND window_end >= %(today)s""",
        {"refs": list(options), "today": metrics.TODAY})
    live_refs = {r["tender_ref"] for r in live}
    choice = next((o for o in options if o in live_refs), options[0])
    moves_the_ceiling = choice in live_refs

    load_t = float(db.fetch_one(tid, """
        SELECT qty_net_t FROM src_dispatch_register WHERE dispatch_no = %(d)s""",
        {"d": item["subject_ref"]})["qty_net_t"])

    a1 = answer.run(tid, "order_book", {})
    open_before = db.fetch_one(tid, "SELECT count(*) AS n FROM review_queue "
                                    "WHERE status = 'open'")["n"]

    # answer it exactly as the console does
    with db.tenant_cursor(tid) as cur:
        cur.execute("""INSERT INTO dispatch_tender
                         (tenant_id, dispatch_id, tender_ref, method, decided_by)
                       VALUES (%s,%s,%s,'human','test_wiring')
                       ON CONFLICT (tenant_id, dispatch_id)
                       DO UPDATE SET tender_ref = EXCLUDED.tender_ref,
                                     method = 'human', decided_by = 'test_wiring'""",
                    (tid, item["subject_ref"], choice))
        cur.execute("UPDATE review_queue SET status = 'resolved', resolved_by = 'test_wiring'"
                    " WHERE review_id = %s", (item["review_id"],))

    a2 = answer.run(tid, "order_book", {})
    open_after = db.fetch_one(tid, "SELECT count(*) AS n FROM review_queue "
                                   "WHERE status = 'open'")["n"]

    bad += check("answering one item takes it off the queue",
                 open_after == open_before - 1, f"{open_before} -> {open_after} open")
    bad += check("the load it was blocking is no longer unattributed",
                 a2["raw"]["unattributed_loads"] < a1["raw"]["unattributed_loads"],
                 f"{a1['raw']['unattributed_loads']} -> "
                 f"{a2['raw']['unattributed_loads']} loads")
    bad += check("the range narrows because of it",
                 a2["raw"]["unattributed_t"] < a1["raw"]["unattributed_t"],
                 f"{a1['raw']['unattributed_t']:,.1f} t -> "
                 f"{a2['raw']['unattributed_t']:,.1f} t of doubt")

    # The one the old version of this test never asked. Placing a load on a contract that
    # is still running credits it as delivered, so the order book must fall by exactly that
    # load's tonnage. Not "must change": by that number, or the decision reached the table
    # and not the sum.
    if moves_the_ceiling:
        moved = a1["raw"]["owed_t"] - a2["raw"]["owed_t"]
        bad += check("and the order book itself falls by that load's tonnage",
                     abs(moved - load_t) < 0.05,
                     f"{a1['raw']['owed_t']:,.1f} t -> {a2['raw']['owed_t']:,.1f} t, "
                     f"down {moved:,.1f} t against a load of {load_t:,.1f} t")

    # put it back, because a test that leaves the database changed is not a test
    with db.tenant_cursor(tid) as cur:
        cur.execute("DELETE FROM dispatch_tender WHERE dispatch_id = %s AND "
                    "decided_by = 'test_wiring'", (item["subject_ref"],))
        cur.execute("UPDATE review_queue SET status = 'open', resolved_by = NULL, "
                    "resolved_at = NULL WHERE review_id = %s", (item["review_id"],))
    a3 = answer.run(tid, "order_book", {})
    bad += check("undoing it restores the original answer",
                 a3["raw"]["unattributed_t"] == a1["raw"]["unattributed_t"]
                 and a3["raw"]["owed_t"] == a1["raw"]["owed_t"])

    # and a decision has to survive a re-import, because that is the whole point of keying
    # it on the source system's own number rather than on a row id we generated
    bad += check("the decision is keyed on the source dispatch number",
                 isinstance(item["subject_ref"], str) and item["subject_ref"].startswith("DR"),
                 f"subject_ref = {item['subject_ref']!r}")
    return bad


def main():
    bad = 0
    for tid in [r["tenant_id"] for r in db.tenants()]:
        bad += definition_wiring(tid)
        bad += review_wiring(tid)
    print()
    if bad:
        print(f"  {bad} wiring checks failed. A setting or a decision is not reaching "
              f"the answers.")
    else:
        print("  every definition and every review decision changes the answers it should, "
              "and nothing else.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
