"""
The canonical layer: working out who each party is and what each item is.

Two jobs, and they are deliberately different in character.

ITEMS are decided by a rule and nothing else. A product code plus a date resolves to exactly
one recipe, because the item master says when each recipe was in force. There is no judgement
here and no similarity: PLT-A1 on 2023-06-01 is one product and PLT-A1 on 2024-06-01 is
another, and the date settles it. This is the only thing that catches a reused code.

PARTIES are decided by GSTIN where there is one, and by exact name where there is not. Where
neither settles it, nothing is decided: a row goes into the review queue for a person to
confirm. Similarity is allowed to propose a candidate and is never allowed to write a link.
That is why party_link.method has no 'similarity' value in the schema.

    python -m app.canonical [a|b]
"""

import csv, json, pathlib, sys

from . import db

ROOT = pathlib.Path(__file__).resolve().parent.parent


def seed_dir(tid):
    return ROOT / ("seed_inputs" if tid == "a" else f"seed_inputs_{tid}")


def read(tid, name):
    with open(seed_dir(tid) / f"{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_items(tid):
    """The item master, with its validity windows and the energy each recipe produces.

    GCV comes from the materials, not from the code. A blend inherits the average of what
    went into it, which is why 'made_from' is the column that matters here."""
    mats = {m["material"]: m for m in read(tid, "materials")}

    def gcv(made_from):
        parts = [p.strip() for p in made_from.split("+")]
        known = [mats[p] for p in parts if p in mats]
        if not known:
            return 3200, 3200, 3200
        return (sum(float(k["gcv_min"]) for k in known) / len(known),
                sum(float(k["gcv_typical"]) for k in known) / len(known),
                sum(float(k["gcv_max"]) for k in known) / len(known))

    with db.tenant_cursor(tid) as cur:
        cur.execute("DELETE FROM item_link")
        cur.execute("DELETE FROM item")
        n = 0
        for g in read(tid, "grades"):
            lo, ty, hi = gcv(g["made_from"])
            cur.execute("""INSERT INTO item (tenant_id, code, valid_from, valid_to, made_from,
                                             gcv_min, gcv_typical, gcv_max, kind)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pellet')""",
                        (tid, g["code"], g["valid_from"], g["valid_to"], g["made_from"],
                         lo, ty, hi))
            n += 1
        for m in read(tid, "materials"):
            cur.execute("""INSERT INTO item (tenant_id, code, valid_from, valid_to, made_from,
                                             gcv_min, gcv_typical, gcv_max, kind)
                           VALUES (%s,%s,'2023-04-01','2030-03-31',%s,%s,%s,%s,'feedstock')""",
                        (tid, m["material"].title(), m["material"],
                         m["gcv_min"], m["gcv_typical"], m["gcv_max"]))
            n += 1
    return n


def build_parties(tid):
    """Ledger names become parties. GSTIN decides it where there is one.

    Where GSTIN is blank, an exact name match against the seed still settles it. Anything
    left over is not guessed: it goes to the review queue with whatever similarity suggests,
    and a person decides. The method column records which of those happened, so six months
    later you can see exactly which links rest on somebody's judgement."""
    vendors = {v["name"]: v for v in read(tid, "vendors")}
    ledgers = db.fetch(tid, "SELECT ledger_name, parent_group, gstin FROM src_tally_ledger")
    # every name this company knows, so a question can offer something to click
    known = list(vendors) + [b["name"] for b in read(tid, "buyers")] \
        + [pl["name"] for pl in read(tid, "plants")]

    made = {"gstin": 0, "exact_name": 0, "queued": 0}
    with db.tenant_cursor(tid) as cur:
        cur.execute("DELETE FROM party_link")
        cur.execute("DELETE FROM party")
        cur.execute("DELETE FROM review_queue WHERE kind = 'party_match'")

        for lg in ledgers:
            kind = "vendor" if lg["parent_group"] == "Sundry Creditors" else "buyer"
            gstin = lg["gstin"]
            method = None
            if gstin:
                method = "gstin"
            elif lg["ledger_name"] in vendors:
                gstin = vendors[lg["ledger_name"]]["gstin"]
                method = "exact_name"

            if not method:
                # Nothing certain. Propose, never decide.
                #
                # Proposing means putting real candidates in front of a person. A question
                # with no options is not a question. The candidates come from this company's
                # own buyer, plant and vendor lists. The machine still will not pick one on a
                # name resemblance, which is why party_link.method has no 'similarity' value.
                words = {w for w in lg["ledger_name"].lower().split() if len(w) > 3}
                cands = sorted(
                    ((len(words & {w for w in nm.lower().split() if len(w) > 3}), nm)
                     for nm in known if nm != lg["ledger_name"]),
                    reverse=True)
                options = [nm for score, nm in cands[:4] if score]

                cur.execute("""INSERT INTO review_queue (tenant_id, kind, subject_ref, proposal)
                               VALUES (%s, 'party_match', %s, %s)""",
                            (tid, lg["ledger_name"],
                             json.dumps({
                                 "question": ("This name is on the books with no GSTIN and "
                                              "matches nothing exactly. Which %s is it?"
                                              % kind),
                                 "ledger": lg["ledger_name"], "kind": kind,
                                 "options": options,
                                 "because": ("no GSTIN on the ledger, so nothing is certain. "
                                             "These are the closest names on file and the "
                                             "machine will not choose between them"),
                                 "no_gstin": True})))
                made["queued"] += 1
                continue

            cur.execute("""INSERT INTO party (tenant_id, name, gstin, kind)
                           VALUES (%s,%s,%s,%s) RETURNING party_id""",
                        (tid, lg["ledger_name"], gstin, kind))
            pid = cur.fetchone()["party_id"]
            cur.execute("""INSERT INTO party_link
                             (tenant_id, system, source_key, party_id, method, decided_by)
                           VALUES (%s,'tally',%s,%s,%s,'rule')""",
                        (tid, lg["ledger_name"], pid, method))
            made[method] += 1
    return made


def queue_unattributed_dispatches(tid):
    """Loads with no contract written against them.

    A buyer runs one contract at a time, so a destination and a date normally pick out
    exactly one contract and a rule settles it. What a rule cannot settle is a load that
    went out after the window closed, on an extension nobody recorded. No window is open on
    that day, so the machine offers the contracts on either side and stops.

    There is no third branch that picks the likeliest. That is how you get a confident wrong
    commitment figure."""
    rows = db.fetch(tid, """
        SELECT d.dispatch_no, d.dispatch_date, d.qty_net_t, d.destination,
               array_remove(array_agg(t.tender_ref), NULL) AS possible
        FROM src_dispatch_register d
        LEFT JOIN src_tender_award t
               ON upper(t.plant) = d.destination
              AND t.grade_code   = d.grade_code
              AND d.dispatch_date BETWEEN t.window_start AND t.window_end
        WHERE d.tender_ref IS NULL
        GROUP BY d.dispatch_no, d.dispatch_date, d.qty_net_t, d.destination""")

    settled = queued = unplaceable = 0
    with db.tenant_cursor(tid) as cur:
        cur.execute("DELETE FROM review_queue WHERE kind = 'dispatch_tender'")
        for r in rows:
            poss = r["possible"] or []
            if len(poss) == 1:
                cur.execute("""INSERT INTO dispatch_tender
                                 (tenant_id, dispatch_id, tender_ref, method, decided_by)
                               VALUES (%s,%s,%s,'only_candidate','rule')
                               ON CONFLICT DO NOTHING""",
                            (tid, r["dispatch_no"], poss[0]))
                settled += 1
            else:
                q = "which contract was this load against?"
                if not poss:
                    # Nothing was open that day. Offer the contract that had just closed and
                    # the one that opened next, and say plainly why the machine is asking.
                    near = db.fetch(tid, """
                        SELECT tender_ref FROM src_tender_award
                        WHERE upper(plant) = %(p)s
                        ORDER BY abs(%(d)s::date - window_end) LIMIT 2""",
                                    {"p": r["destination"], "d": r["dispatch_date"]})
                    poss = [x["tender_ref"] for x in near]
                    q = ("this load went out after the contract for that plant had closed. "
                         "Was it an extension of the closing contract, or the start of the "
                         "next one?")
                cur.execute("""INSERT INTO review_queue (tenant_id, kind, subject_ref, proposal)
                               VALUES (%s,'dispatch_tender',%s,%s)""",
                            (tid, r["dispatch_no"],
                             json.dumps({"question": q,
                                         "date": str(r["dispatch_date"]),
                                         "tonnes": float(r["qty_net_t"]),
                                         "plant": r["destination"],
                                         "options": poss})))
                queued += 1
                if not poss:
                    unplaceable += 1
    return settled, queued, unplaceable


def queue_unclassified_purchases(tid):
    """Purchases where nothing in the books says what was actually bought.

    The item master settles most of them. The rate band settles more, because residue and
    finished pellets are thousands of rupees apart. What is left carries the useless generic
    item name and a rate in the gap between the two bands, and that genuinely cannot be told
    apart from the books.

    The question a person gets is not "feedstock or finished". That is our vocabulary, and
    answering it still leaves the material unknown, which is useless: GCV is a property of the
    material and not of the product code, so a purchase filed as feedstock with no material
    named cannot be costed per kilocalorie. So the question offers the materials this company
    actually buys, and puts the likeliest one forward with the reason for thinking so."""
    names = [m["code"] for m in db.fetch(tid, """
        SELECT code FROM item WHERE kind = 'feedstock' ORDER BY code""")]

    # what each material has actually cost here, so a suggestion is evidence and not a hunch
    seen = {r["material"]: float(r["mid"]) for r in db.fetch(tid, """
        SELECT stock_item_name AS material, avg(rate) AS mid
        FROM src_tally_inventory_entry
        WHERE stock_item_name <> 'Biomass Material'
        GROUP BY 1""")}

    # and what this vendor has sent before, which is the strongest clue in the book
    hist = {}
    for r in db.fetch(tid, """
        SELECT v.ledger_name, i.stock_item_name AS material, count(*) AS n
        FROM src_tally_voucher v
        JOIN src_tally_inventory_entry i ON i.voucher_guid = v.guid
        WHERE v.voucher_type = 'Purchase' AND i.stock_item_name <> 'Biomass Material'
        GROUP BY 1, 2"""):
        best = hist.get(r["ledger_name"])
        if not best or r["n"] > best[1]:
            hist[r["ledger_name"]] = (r["material"], r["n"])

    rows = db.fetch(tid, """
        SELECT v.guid, v.vch_date, v.ledger_name, v.amount, v.narration,
               i.stock_item_name, i.qty_qtl / 10.0 AS tonnes, i.rate
        FROM src_tally_voucher v
        JOIN src_tally_inventory_entry i ON i.voucher_guid = v.guid
        WHERE v.voucher_type = 'Purchase'
          AND i.stock_item_name = 'Biomass Material'
          AND i.rate BETWEEN 3200 AND 6600
        ORDER BY v.guid""")

    with db.tenant_cursor(tid) as cur:
        cur.execute("DELETE FROM review_queue WHERE kind = 'purchase_channel'")
        for r in rows:
            rate = float(r["rate"])
            past = hist.get(r["ledger_name"])
            near = sorted(((abs(rate - mid), nm) for nm, mid in seen.items() if nm in names),
                          key=lambda x: x[0])
            why = []
            if past:
                why.append("%s has sent us %s %d times before"
                           % (r["ledger_name"], past[0], past[1]))
            if near:
                why.append("Rs %s a tonne is closest to what we normally pay for %s"
                           % (format(rate, ",.0f"), near[0][1]))
            suggest = past[0] if past and past[0] in names else (near[0][1] if near else None)

            cur.execute("""INSERT INTO review_queue (tenant_id, kind, subject_ref, proposal)
                           VALUES (%s,'purchase_channel',%s,%s)""",
                        (tid, r["guid"],
                         json.dumps({
                             "question": ("The bill says only \u201cBiomass Material\u201d and "
                                          "the rate sits between what residue costs and what "
                                          "finished pellets cost, so nothing in the books "
                                          "settles it. What did we actually buy?"),
                             "date": r["vch_date"], "vendor": r["ledger_name"],
                             "tonnes": float(r["tonnes"]), "rate": rate,
                             "item": r["stock_item_name"], "narration": r["narration"],
                             "options": names, "suggest": suggest,
                             "because": ". ".join(why) if why else None})))
    return len(rows)


def build(tid):
    print(f"tenant {tid}")
    print(f"  items                {build_items(tid)}")
    p = build_parties(tid)
    print(f"  parties by GSTIN     {p['gstin']}")
    print(f"  parties by name      {p['exact_name']}")
    print(f"  parties to review    {p['queued']}")
    s, q, u = queue_unattributed_dispatches(tid)
    print(f"  loads placed by rule {s}")
    print(f"  loads to review      {q}   (of which {u} match no contract at all)")
    print(f"  purchases to review  {queue_unclassified_purchases(tid)}")


if __name__ == "__main__":
    ids = sys.argv[1:] or [t["tenant_id"] for t in db.tenants()]
    for t in ids:
        build(t)
