"""
The twenty questions, as the owner would type them, each mapped to a metric and its
parameters.

The mapping lives here rather than in the metrics, because the same metric answers several
questions with different parameters. That is the whole reason there are a dozen metrics
rather than twenty queries: when the definition of "order_book" changes, one template
changes, not twenty.

`expect` is what the answer key says should happen. The test script compares against it, so
answering something that should have been refused counts as a failure just as loudly as
refusing something answerable.
"""

Q = [
    # ---- the quoting sequence, which is what he actually does before a bid
    dict(id="A1", ask="How much is left to deliver on this contract?",
         metric="open_commitment", params={"tender_ref": "__CONTESTED__"}, expect="withheld",
         why="loads went to that plant in that window with no contract written against them"),

    dict(id="A2", ask="How much is left on a contract nobody has left loose ends on?",
         metric="open_commitment", params={"tender_ref": "__CLEAN__"}, expect="answered",
         why="every load to that plant is accounted for, so the subtraction is exact"),

    dict(id="A3", ask="What have we contracted to deliver, and how much of it is left?",
         metric="order_book", params={}, expect="withheld",
         why="the unattributed loads make any total an upper bound"),

    dict(id="A4", ask="When have I got production capacity free over the next year?",
         metric="capacity_free", params={"months": 12}, expect="answered"),

    dict(id="A5", ask="Which raw material is actually cheaper, per unit of energy?",
         metric="material_cost_per_gcv", params={}, expect="answered",
         why="the per tonne answer and the per GCV answer can disagree"),

    dict(id="A6", ask="What does a tonne cost me to make, month by month?",
         metric="production_cost", params={"grade_code": "__GRADE1__"}, expect="answered",
         why="feedstock is seasonal, so the same product costs different money in different "
             "months and the spread is worth more than the average"),

    # The other half of the same decision. A cost to make means nothing on its own.
    dict(id="A6b", ask="And what does it cost to buy the same thing in ready made?",
         metric="buy_in_cost", params={"grade_code": "__GRADE1__"}, expect="answered",
         why="priced per kilocalorie against making it, by month and by vendor, because a "
             "finished pellet is not a commodity with one price"),

    dict(id="A7", ask="And for the other line?",
         metric="production_cost", params={"grade_code": "__GRADE2__"}, expect="answered"),

    # A quote is not a property of a product. It is a property of the months you will be
    # producing in, because feedstock is seasonal, so the window is part of the question.
    dict(id="A8", ask="So what should I quote at 3,200 GCV, delivering over the next year?",
         metric="quote_for_tender",
         params={"grade_code": "__GRADE1__", "quoted_gcv": 3200, "margin_per_gcv": 0.30,
                 "deliver_from": "__M1__", "deliver_to": "__M12__"},
         expect="answered",
         why="the same product costs different money depending on when it is made"),

    dict(id="A9", ask="And if I deliver the same tonnage in the cheap half of the year?",
         metric="quote_for_tender",
         params={"grade_code": "__GRADE1__", "quoted_gcv": 3200, "margin_per_gcv": 0.30,
                 "deliver_from": "__M1__", "deliver_to": "__M6__"},
         expect="answered",
         why="shift the window and the quote moves, which is the whole point"),

    # He is not handed a deadline with the tender. The useful answer is a date.
    dict(id="A9b", ask="The tender on my desk is 3,000 t. By when could I have it made?",
         metric="delivery_runway", params={"tonnes": 3000}, expect="answered",
         why="adds up the room month by month and says when the total first covers the "
             "order, so a delivery date can be quoted rather than guessed at"),

    # ---- money
    dict(id="A10", ask="What did we actually get per tonne on our biggest buyer in FY24-25?",
         metric="realised_price", params={"plant": "__PLANT1__", "fy": "FY24-25"},
         expect="answered"),

    dict(id="A11", ask="And on a second buyer, same year?",
         metric="realised_price", params={"plant": "__PLANT2__", "fy": "FY24-25"},
         expect="answered"),

    dict(id="A12", ask="Who owes us money, and how much?",
         metric="outstanding", params={}, expect="answered"),

    dict(id="A13", ask="What did we dispatch to that buyer in FY24-25?",
         metric="dispatch_total", params={"plant": "__PLANT1__", "fy": "FY24-25"},
         expect="answered", why="the register and the books agree for that year"),

    dict(id="A14", ask="How much did we produce ourselves in FY24-25?",
         metric="channel_split", params={"fy": "FY24-25"}, expect="answered",
         why="that year is clean, which is what makes the R2 refusal precise not blanket"),

    # ---- the six that refuse, each for a different reason
    dict(id="R1", ask="How did this product compare between FY23-24 and FY24-25?",
         metric="item_period_comparison",
         params={"grade_code": "__CHANGED__", "fy_a": "__FY_BEFORE__",
                 "fy_b": "__FY_AFTER__"},
         expect="withheld", why="the code meant two different recipes either side"),

    dict(id="R2", ask="How much of FY25-26 did we produce ourselves, and how much did we buy in?",
         metric="channel_split", params={"fy": "FY25-26"}, expect="withheld",
         why="purchases that cannot be told apart as raw material or bought-in pellets"),

    dict(id="R3", ask="How much more could this vendor supply us next season?",
         metric="vendor_capacity", params={"vendor": "__VENDOR__"}, expect="withheld",
         why="never recorded anywhere. Different in kind from the other refusals"),

    dict(id="R4", ask="Which vendors have kept their word?",
         metric="vendor_reliability", params={}, expect="withheld",
         why="the commitments are still sitting in email, unextracted"),

    # A price per tonne divided by a tonnage the dispatch question refuses to publish is
    # two answers to one question. This is the refusal that stops that happening.
    dict(id="R7", ask="What did we actually get per tonne on this buyer in FY25-26?",
         metric="realised_price",
         params={"plant": "__PLANT_DISPUTED__", "fy": "FY25-26"}, expect="withheld",
         why="the tonnage it would divide by is itself disputed, and the dispatch question "
             "refuses that same tonnage"),

    dict(id="R5", ask="What did we dispatch in FY26-27?",
         metric="dispatch_total", params={"plant": "__PLANT3__", "fy": "FY26-27"},
         expect="withheld", why="loads went out with nothing raised against them"),

    # Quoting above what the product tests at is not a bid, it is a shortfall planned in
    # advance. The answer's own warning is that quoting high and delivering low is not a
    # rounding error, so it refuses to be the one that does it.
    dict(id="R6", ask="What should I quote if I claim a GCV my product does not reach?",
         metric="quote_for_tender",
         params={"grade_code": "__GRADE1__", "quoted_gcv": "__GCV_TOO_HIGH__",
                 "margin_per_gcv": 0.30, "deliver_from": "__M1__", "deliver_to": "__M6__"},
         expect="withheld",
         why="every load would land under the figure on the contract and the deduction "
             "would follow, so it will not price it"),
]


def resolve(tenant_id):
    """Fill in the placeholders from whatever this tenant actually has.

    The same twenty questions run against both companies, and neither company's contract
    references, plant names or product codes appear anywhere in the list above. If they did,
    the suite would only ever test tenant A."""
    from . import db

    picks = {}

    # A buyer runs one contract at a time, so a date and a destination normally settle a
    # loose load on their own. What is left contested is a contract an open review item
    # still points at: a load that went out after the window closed, on an extension.
    r = db.fetch_one(tenant_id, """
        SELECT t.tender_ref FROM src_tender_award t
        JOIN review_queue q ON q.kind = 'dispatch_tender' AND q.status = 'open'
                           AND q.proposal -> 'options' ? t.tender_ref
        WHERE EXISTS (SELECT 1 FROM src_dispatch_register d2 WHERE d2.tender_ref = t.tender_ref)
        ORDER BY t.tonnes DESC LIMIT 1""")
    picks["__CONTESTED__"] = r and r["tender_ref"]

    # a contract with no open question hanging over it
    r = db.fetch_one(tenant_id, """
        SELECT t.tender_ref FROM src_tender_award t
        WHERE NOT EXISTS (
          SELECT 1 FROM review_queue q
          WHERE q.kind = 'dispatch_tender' AND q.status = 'open'
            AND q.proposal -> 'options' ? t.tender_ref)
          AND NOT EXISTS (
          SELECT 1 FROM src_dispatch_register d
          LEFT JOIN dispatch_tender dt ON dt.dispatch_id = d.dispatch_no
          WHERE d.tender_ref IS NULL AND dt.tender_ref IS NULL
            AND d.destination = upper(t.plant) AND d.grade_code = t.grade_code
            AND d.dispatch_date BETWEEN t.window_start AND t.window_end)
          AND EXISTS (SELECT 1 FROM src_dispatch_register d2 WHERE d2.tender_ref = t.tender_ref)
        ORDER BY t.tonnes DESC LIMIT 1""")
    picks["__CLEAN__"] = r and r["tender_ref"]

    # a contract with nothing shipped against it at all
    r = db.fetch_one(tenant_id, """
        SELECT t.tender_ref FROM src_tender_award t
        WHERE NOT EXISTS (SELECT 1 FROM src_dispatch_register d WHERE d.tender_ref = t.tender_ref)
        ORDER BY t.window_start DESC LIMIT 1""")
    picks["__EMPTY__"] = r and r["tender_ref"]

    # the planning window, so the quote questions have real months to work in
    from .metrics import TODAY
    def ahead(k):
        y, m = TODAY.year, TODAY.month + k - 1
        return "%d-%02d" % (y + m // 12, m % 12 + 1)
    picks["__M1__"], picks["__M6__"], picks["__M12__"] = ahead(1), ahead(6), ahead(12)

    grades = [x["grade_code"] for x in db.fetch(tenant_id,
              "SELECT DISTINCT grade_code FROM src_tender_award ORDER BY 1")]
    picks["__GRADE1__"] = grades[0] if grades else None
    # a GCV this product cannot actually reach, taken from the item master rather than
    # picked out of the air
    g = db.fetch_one(tenant_id, """
        SELECT gcv_typical FROM item WHERE code = %(g)s AND kind = 'pellet'
        ORDER BY valid_from DESC LIMIT 1""", {"g": grades[0] if grades else None})
    picks["__GCV_TOO_HIGH__"] = int(float(g["gcv_typical"])) + 200 if g else 4000
    # the product whose recipe changed, and the year it changed in. Picking whichever grade
    # happens to sort first would test nothing: most of them never changed at all.
    # The two companies changed a recipe in different years, so the question has to find
    # the change rather than assume it. Asking about two years that both sit on one side of
    # it would test nothing and would rightly be answered.
    r = db.fetch_one(tenant_id, """
        SELECT i.code, min(i.valid_from) AS changed_on
        FROM item i WHERE i.kind = 'pellet'
        GROUP BY i.code HAVING count(DISTINCT i.made_from) > 1
        ORDER BY i.code LIMIT 1""")
    picks["__CHANGED__"] = r and r["code"]
    if r:
        cut = db.fetch_one(tenant_id, """
            SELECT min(valid_from) AS d FROM item
            WHERE code = %(c)s AND kind = 'pellet' AND valid_from > %(f)s""",
            {"c": r["code"], "f": r["changed_on"]})
        d = cut and cut["d"]
        if d:
            # a financial year here runs April to March, so the year the change lands in is
            # the one that opens on it, and the year before is the one that closes on it
            y = d.year if d.month >= 4 else d.year - 1
            picks["__FY_BEFORE__"] = f"FY{str(y - 1)[2:]}-{str(y)[2:]}"
            picks["__FY_AFTER__"] = f"FY{str(y)[2:]}-{str(y + 1)[2:]}"
    picks["__GRADE2__"] = grades[1] if len(grades) > 1 else picks["__GRADE1__"]

    # Buyers whose dispatch register and sales ledger agree for the year being asked
    # about, so the realised price question has a tonnage worth dividing by. Picking the
    # busiest plant instead means the question sometimes lands on a buyer whose books do
    # not reconcile, and the honest answer there is a refusal, not a price.
    plants = [x["plant"] for x in db.fetch(tenant_id, """
        WITH reg AS (
            SELECT DISTINCT ON (dispatch_no) dispatch_no, destination, invoice_no
            FROM src_dispatch_register
            WHERE dispatch_date BETWEEN date '2024-04-01' AND date '2025-03-31')
        SELECT p.plant, r.n
        FROM (SELECT DISTINCT plant FROM src_tender_award) p
        JOIN LATERAL (
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE invoice_no IS NULL) AS uninv
            FROM reg WHERE reg.destination = upper(p.plant)) r ON true
        WHERE r.n > 0 AND r.uninv = 0
          AND r.n = (SELECT count(*) FROM src_tally_voucher v
                     WHERE v.voucher_type = 'Sales' AND v.ledger_name = p.plant
                       AND to_date(v.vch_date, 'DD-Mon-YYYY')
                           BETWEEN date '2024-04-01' AND date '2025-03-31')
        ORDER BY r.n DESC""")]
    picks["__PLANT1__"] = plants[0] if plants else None
    picks["__PLANT2__"] = plants[1] if len(plants) > 1 else picks["__PLANT1__"]

    # and a buyer whose two systems do NOT agree, which is a refusal worth showing
    r = db.fetch_one(tenant_id, """
        SELECT t.plant, count(*) AS n
        FROM (SELECT DISTINCT plant FROM src_tender_award) t
        JOIN src_dispatch_register d ON d.destination = upper(t.plant)
        WHERE d.dispatch_date BETWEEN date '2025-04-01' AND date '2026-03-31'
          AND d.invoice_no IS NULL
        GROUP BY t.plant ORDER BY 2 DESC LIMIT 1""")
    picks["__PLANT_DISPUTED__"] = (r and r["plant"]) or picks["__PLANT1__"]

    # a plant that has loads with nothing raised against them
    r = db.fetch_one(tenant_id, """
        SELECT t.plant FROM src_dispatch_register d
        JOIN src_tender_award t ON upper(t.plant) = d.destination
        WHERE d.invoice_no IS NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""")
    picks["__PLANT3__"] = (r and r["plant"]) or picks["__PLANT1__"]

    r = db.fetch_one(tenant_id, """
        SELECT ledger_name FROM src_tally_ledger
        WHERE parent_group = 'Sundry Creditors' ORDER BY ledger_name LIMIT 1""")
    picks["__VENDOR__"] = r and r["ledger_name"]

    out = []
    for q in Q:
        q = {**q, "params": {k: picks.get(v, v) if isinstance(v, str) else v
                             for k, v in q["params"].items()}}
        out.append(q)
    return out
