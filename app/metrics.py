"""
The metric registry.

Every question the product can answer is one of these. A metric is four things:

    params    what the caller may choose, and the allowed values come from the database
    sql       a template with named holes, filled from the tenant's definitions
    checks    what must be true before the number can be sent
    render    a sentence with slots, filled from the result set by name

Two rules the whole design rests on:

  1. Nobody outside this file writes SQL. Not the API, not the interface, not the caller.
     A "custom question" is a metric name plus typed parameters, and every parameter value
     is offered from a list the database produced. There is no path from typed text to SQL.

  2. A metric never returns a bare number. It returns rows plus the checks that ran, and
     answer.py decides whether that becomes a sentence or a refusal.
"""

from datetime import date, timedelta

TODAY = date(2026, 9, 1)          # matches the live tender in the seed

MONTH_NAME = {"01": "January", "02": "February", "03": "March", "04": "April",
              "05": "May", "06": "June", "07": "July", "08": "August",
              "09": "September", "10": "October", "11": "November", "12": "December"}


# ---------------------------------------------------------------- helper fragments
# Tally stores dates as text. Parse once, here, so no metric has to remember the format.
VCH_DATE = "to_date(v.vch_date, 'DD-Mon-YYYY')"
QTL_TO_T = "(i.qty_qtl / 10.0)"     # the trade works in quintals, ten to a tonne

# Purchases, cleaned up enough to aggregate but with the channel left honest.
# channel NULL means nobody can tell whether it was raw material or bought-in pellets.
PURCHASES = f"""
    SELECT v.guid,
           {VCH_DATE}                              AS txn_date,
           to_date(v.entered_at, 'DD-Mon-YYYY')    AS entered_at,
           v.ledger_name,
           v.amount,
           i.stock_item_name,
           {QTL_TO_T}                              AS tonnes,
           i.rate,
           -- The item master says which group a name belongs to, so the rule reads the
           -- master rather than listing one company's crops. Where the name is the useless
           -- generic one, the rate band decides, and where even that is inconclusive the
           -- channel stays NULL and somebody has to look.
           CASE
             WHEN si.parent_group = 'Finished Goods'                THEN 'finished'
             WHEN si.parent_group = 'Raw Material'
              AND i.stock_item_name <> 'Biomass Material'           THEN 'feedstock'
             WHEN i.rate < 3200                                     THEN 'feedstock'
             WHEN i.rate > 6600                                     THEN 'finished'
             ELSE NULL
           END                                     AS channel
    FROM src_tally_voucher v
    JOIN src_tally_inventory_entry i ON i.voucher_guid = v.guid
    LEFT JOIN src_tally_stock_item si ON si.item_name = i.stock_item_name
    WHERE v.voucher_type = 'Purchase'
"""

# Every load, with the contract it was written against, and the contracts it could
# plausibly belong to when nobody wrote one down.
DISPATCH_CANDIDATES = """
    SELECT d.dispatch_no, d.dispatch_date, d.qty_net_t, d.destination, d.grade_code,
           d.tender_ref                            AS stated_ref,
           dt.tender_ref                           AS resolved_ref,
           array_remove(array_agg(t.tender_ref), NULL) AS possible
    FROM src_dispatch_register d
    LEFT JOIN dispatch_tender dt ON dt.dispatch_id = d.dispatch_no
    LEFT JOIN src_tender_award t
           ON d.tender_ref IS NULL
          AND upper(t.plant) = d.destination
          AND t.grade_code   = d.grade_code
          AND d.dispatch_date BETWEEN t.window_start AND t.window_end
    GROUP BY d.dispatch_no, d.dispatch_date, d.qty_net_t, d.destination, d.grade_code,
             d.tender_ref, dt.tender_ref
"""

REGISTRY = {}


def metric(name, **meta):
    def wrap(fn):
        REGISTRY[name] = dict(name=name, run=fn, **meta)
        return fn
    return wrap


# ================================================================ commitment
@metric("open_commitment",
        title="How much is left to deliver on a contract?",
        params=[("tender_ref", "contract", "tender")],
        needs=["order_book"],
        follows=['dispatch_total', 'realised_price', 'order_book'],
        about="Contracted tonnage minus everything dispatched against it.")
def open_commitment(db, tid, defs, p):
    ref = p["tender_ref"]
    d = defs["order_book"]["params"]

    award = db.fetch_one(tid, """
        SELECT tender_ref, plant, grade_code, tonnes, window_start, window_end,
               coalesce(option_pct, 0) AS option_pct, contract_type
        FROM src_tender_award WHERE tender_ref = %(ref)s""", {"ref": ref})
    if not award:
        return {"error": f"no contract called {ref}"}

    # The percentage is a term of this contract, not a setting. A public tender carries an
    # option to increase; a private monthly supply contract does not, and adding twenty
    # five percent to one of those invents tonnage the buyer never asked for. The
    # definition decides whether to count the option at all. The contract decides how big
    # it is.
    own_pct = float(award["option_pct"] or 0)
    factor = (1 + own_pct) if d["apply_option_clause"] else 1.0
    # A load counts against this contract if the register says so, or if somebody placed
    # it there. Reading only the register loses every decision the review queue ever made,
    # which is the one thing that layer exists to preserve.
    conf = db.fetch_one(tid, """
        SELECT count(*) AS loads,
               coalesce(sum(d.qty_net_t), 0) AS tonnes,
               count(*) FILTER (WHERE d.tender_ref IS NULL) AS placed_by_hand,
               coalesce(sum(d.qty_net_t) FILTER (WHERE d.tender_ref IS NULL), 0)
                                                            AS placed_by_hand_t
        FROM src_dispatch_register d
        LEFT JOIN dispatch_tender dt ON dt.dispatch_id = d.dispatch_no
        WHERE d.tender_ref = %(ref)s OR dt.tender_ref = %(ref)s""", {"ref": ref})

    # Loads that could belong to this contract and have not been settled. Two ways in:
    # a load inside the window that nobody attributed, and a load a person is still being
    # asked about, which under the one-contract-at-a-time rule means one that went out
    # after the window closed. Either way the answer is a range, not a figure.
    blocked = db.fetch(tid, """
        SELECT DISTINCT d.dispatch_no, d.dispatch_date, d.qty_net_t
        FROM src_dispatch_register d
        JOIN src_tender_award t ON t.tender_ref = %(ref)s
        LEFT JOIN dispatch_tender dt ON dt.dispatch_id = d.dispatch_no
        LEFT JOIN review_queue q ON q.kind = 'dispatch_tender' AND q.status = 'open'
                                AND q.subject_ref = d.dispatch_no
                                AND q.proposal -> 'options' ? %(ref)s
        WHERE d.tender_ref IS NULL AND dt.tender_ref IS NULL
          AND (q.review_id IS NOT NULL
               OR (d.destination = upper(t.plant) AND d.grade_code = t.grade_code
                   AND d.dispatch_date BETWEEN t.window_start AND t.window_end))
        ORDER BY d.dispatch_date""", {"ref": ref})

    contracted = float(award["tonnes"]) * factor
    option_pct = own_pct if d["apply_option_clause"] else 0.0
    out = float(conf["tonnes"])
    unknown = sum(float(b["qty_net_t"]) for b in blocked)
    return {
        "contract": ref, "plant": award["plant"],
        "awarded_t": float(award["tonnes"]),
        "contracted_t": contracted, "dispatched_t": out, "loads": conf["loads"],
        # once everything awarded has gone out, what is left is the buyer's option and
        # nothing else, which is a different thing to owe and worth saying
        "only_option_left": (d["apply_option_clause"] and own_pct > 0
                             and out >= float(award["tonnes"]) - 1),
        "placed_by_hand": conf["placed_by_hand"],
        "placed_by_hand_t": float(conf["placed_by_hand_t"]),
        "remaining_max_t": contracted - out,
        "remaining_min_t": contracted - out - unknown,
        "unattributed_t": unknown, "unattributed_loads": len(blocked),
        "blocked_rows": [dict(b) for b in blocked],
        "option_applied": d["apply_option_clause"],
        # the actual percentage on this contract, so no sentence has to guess at it
        "option_pct": option_pct,
        "option_t": contracted - float(award["tonnes"]),
    }


@metric("order_book",
        title="What have we contracted to deliver, and how much of it is left?",
        params=[], needs=["order_book"],
        follows=['open_commitment', 'capacity_free', 'cash_calendar'],
        about="Every live contract we have with a buyer: what was contracted, what has "
              "gone out, and what is still owed. Nothing a vendor has promised us appears "
              "here. That is the other side of the business and a different question.")
def order_book(db, tid, defs, p):
    d = defs["order_book"]["params"]
    counting = bool(d["apply_option_clause"])

    def factor_for(row):
        """Each contract's own option clause, not one percentage applied to all of them."""
        return (1 + float(row["option_pct"] or 0)) if counting else 1.0

    rows = db.fetch(tid, """
        SELECT t.tender_ref, t.plant, t.grade_code, t.tonnes,
               coalesce(t.option_pct, 0) AS option_pct,
               coalesce(sum(d.qty_net_t), 0) AS out_t
        FROM src_tender_award t
        LEFT JOIN (
            -- A load counts against a contract if the register says so, OR if somebody
            -- placed it there in the review queue. Joining the raw column alone throws
            -- away every decision that layer has ever recorded, which is the one thing it
            -- exists to preserve: the refusal below would count a load as unplaced, a
            -- person would place it, the count of open questions would drop, and the
            -- tonnage would never move.
            SELECT d.dispatch_no, d.qty_net_t,
                   coalesce(d.tender_ref, dt.tender_ref) AS tender_ref
            FROM src_dispatch_register d
            LEFT JOIN dispatch_tender dt ON dt.dispatch_id = d.dispatch_no
        ) d ON d.tender_ref = t.tender_ref
        WHERE t.window_end >= %(today)s
        GROUP BY t.tender_ref, t.plant, t.grade_code, t.tonnes, t.option_pct
        ORDER BY t.tender_ref""", {"today": TODAY})

    # The wall of deadlines. Not a monthly spread: nobody owes anything in a particular
    # month, they owe a total by a date. So the tonnage sits in the month it is actually
    # due, which is the month somebody has to plan backwards from.
    # Grouped by month and product, because the chart wants the split. The renderer must
    # therefore add the products up before it talks about a month, which it was not doing:
    # it sorted by month and took the first row, and reported one product's slice as the
    # whole of March.
    by_deadline = db.fetch(tid, """
        SELECT to_char(t.window_end, 'YYYY-MM')        AS month,
               t.grade_code,
               count(*)                                AS contracts,
               sum(t.tonnes * (1 + %(opt)s * coalesce(t.option_pct, 0))) AS awarded,
               sum(coalesce(d.out_t, 0))               AS delivered,
               sum(greatest(0, t.tonnes * (1 + %(opt)s * coalesce(t.option_pct, 0))
                              - coalesce(d.out_t, 0))) AS remaining
        FROM src_tender_award t
        LEFT JOIN LATERAL (
            -- same rule as above: the register's own reference, or the one a person gave it
            SELECT sum(x.qty_net_t) AS out_t
            FROM src_dispatch_register x
            LEFT JOIN dispatch_tender xt ON xt.dispatch_id = x.dispatch_no
            WHERE coalesce(x.tender_ref, xt.tender_ref) = t.tender_ref
        ) d ON true
        WHERE t.window_end >= %(today)s
        GROUP BY 1, 2 ORDER BY 1, 2""",
        {"today": TODAY, "opt": 1 if counting else 0})

    # what our own vendors have promised us, out of the mail, and whether they keep their word
    vend = db.fetch(tid, """
        SELECT pt.name AS vendor,
               count(*)                                   AS promises,
               sum(c.qty_t)                               AS promised_t,
               count(*) FILTER (WHERE c.status = 'confirmed') AS confirmed,
               coalesce(sum(g.qty_qtl) / 10.0, 0)         AS received_t
        FROM vendor_commitment c
        JOIN party pt ON pt.party_id = c.party_id
        LEFT JOIN LATERAL (
            SELECT sum(qty_qtl) AS qty_qtl FROM src_goods_receipt r
            WHERE r.vendor_name = pt.name
              AND r.received_date BETWEEN c.promised_date - 7 AND c.promised_date + 30
        ) g ON true
        GROUP BY pt.name
        ORDER BY sum(c.qty_t) DESC
        LIMIT 12""")

    vendors = []
    for v in vend:
        promised = float(v["promised_t"] or 0)
        got = float(v["received_t"] or 0)
        ratio = (got / promised) if promised else 0
        # a rating a decision maker can read, not a score he cannot judge
        band = "high" if ratio >= 0.97 else "moderate" if ratio >= 0.85 else "low"
        vendors.append({"vendor": v["vendor"], "promises": v["promises"],
                        "promised_t": promised, "received_t": got,
                        "kept_pct": round(ratio * 100, 1), "credibility": band,
                        "confirmed": v["confirmed"]})

    unatt = db.fetch_one(tid, """
        SELECT count(*) AS n, coalesce(sum(d.qty_net_t), 0) AS t
        FROM src_dispatch_register d
        LEFT JOIN dispatch_tender dt ON dt.dispatch_id = d.dispatch_no
        WHERE d.tender_ref IS NULL AND dt.tender_ref IS NULL""")

    total = sum(max(0.0, float(r["tonnes"]) * factor_for(r) - float(r["out_t"]))
                for r in rows)
    awarded = sum(float(r["tonnes"]) * factor_for(r) for r in rows)
    delivered = sum(float(r["out_t"]) for r in rows)
    with_option = sum(1 for r in rows if counting and float(r["option_pct"] or 0) > 0)
    book = sorted(({"tender_ref": r["tender_ref"], "plant": r["plant"],
                    "grade_code": r["grade_code"],
                    "awarded_t": float(r["tonnes"]) * factor_for(r),
                    "delivered_t": float(r["out_t"]),
                    "remaining_t": max(0.0, float(r["tonnes"]) * factor_for(r)
                                       - float(r["out_t"])),
                    "done_pct": (float(r["out_t"]) / (float(r["tonnes"]) * factor_for(r))
                                 * 100) if r["tonnes"] else 0}
                   for r in rows), key=lambda x: -x["remaining_t"])
    return {"contracts": len(rows), "owed_t": total,
            "awarded_t": awarded, "delivered_t": delivered,
            "book": book,
            "option_applied": d["apply_option_clause"],
            "contracts_with_option": with_option,
            "unattributed_loads": unatt["n"], "unattributed_t": float(unatt["t"]),
            # and the same thing summed per month, so nobody has to remember to add it up
            "walls": [{"month": mo,
                       "contracts": sum(x["contracts"] for x in g),
                       "awarded": sum(float(x["awarded"]) for x in g),
                       "delivered": sum(float(x["delivered"]) for x in g),
                       "remaining": sum(float(x["remaining"]) for x in g),
                       "grades": sorted({x["grade_code"] for x in g})}
                      for mo, g in sorted(
                          {m["month"]: [x for x in by_deadline if x["month"] == m["month"]]
                           for m in by_deadline}.items())],
            "by_deadline": [dict(m) | {"remaining": float(m["remaining"]),
                                       "awarded": float(m["awarded"]),
                                       "delivered": float(m["delivered"])}
                            for m in by_deadline],
            "vendors": vendors,
            "rows": [dict(r) for r in rows[:40]]}


# Everything still owed to a buyer, split by which kind of promise it is. The point of this
# fragment is that the two halves must never be added up and reported as one thing.
OWED = """
    SELECT t.tender_ref, t.plant, t.grade_code, t.contract_type,
           t.tonnes, t.window_start, t.window_end,
           coalesce(sum(d.qty_net_t), 0)                        AS delivered,
           greatest(0, t.tonnes - coalesce(sum(d.qty_net_t), 0)) AS remaining
    FROM src_tender_award t
    LEFT JOIN src_dispatch_register d ON d.tender_ref = t.tender_ref
    WHERE t.window_end >= %(start)s
    GROUP BY t.tender_ref, t.plant, t.grade_code, t.contract_type,
             t.tonnes, t.window_start, t.window_end
"""


def _config(db, tid):
    """The plant's own figures. Falls back to nothing: a missing key is a real problem and
    the caller is told, rather than a plausible constant being substituted for it."""
    return {r["key"]: r["value"] for r in db.fetch(tid,
            "SELECT key, value FROM src_config")}


def _month_list(n):
    out, y, m = [], TODAY.year, TODAY.month
    for _ in range(n):
        out.append("%d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _capacity(db, tid, defs, months):
    """What the plant has actually managed in each calendar month, on the tenant's basis.
    Not a rating off a nameplate. What the production register says it did."""
    agg = "max" if defs["capacity"]["params"]["basis"] == "best" else "avg"
    by_mm = {r["m"]: float(r["t"]) for r in db.fetch(tid, f"""
        SELECT right(month, 2) AS m, {agg}(actual_qty_t) AS t
        FROM src_production_register GROUP BY 1""")}
    return {m: by_mm.get(m[5:7], 0.0) for m in months}


def _pace(owed, months, how):
    """What has to go out each month to clear the tender deadlines.

    'even' spreads what is left evenly over the months remaining in the window, which is the
    pace a planner would actually run at. 'deadline' assumes nothing goes until it has to,
    which is what a producer who only reacts to the due date ends up with. Two tenants can
    reasonably hold either view and the number moves a long way between them, which is why
    it is a definition and not a constant."""
    pace = {m: 0.0 for m in months}
    detail = {m: [] for m in months}
    for r in owed:
        if r["contract_type"] != "cumulative" or float(r["remaining"]) <= 0:
            continue
        end = str(r["window_end"])[:7]
        win = [m for m in months if m <= end] or [months[0]]
        put = [win[-1]] if how == "deadline" else win
        share = float(r["remaining"]) / len(put)
        for m in put:
            pace[m] += share
            detail[m].append({"tender_ref": r["tender_ref"], "plant": r["plant"],
                              "tonnes": share, "deadline": end,
                              "months_left": len(win)})
    return pace, detail


def _runway(owed, months, spare):
    """Per tender: what is still owed against the room left before its own deadline."""
    out = []
    for r in owed:
        if r["contract_type"] != "cumulative" or float(r["remaining"]) <= 0:
            continue
        end = str(r["window_end"])[:7]
        win = [m for m in months if m <= end]
        room = sum(max(0.0, spare[m]) for m in win)
        need = float(r["remaining"])
        out.append({"tender_ref": r["tender_ref"], "plant": r["plant"],
                    "grade_code": r["grade_code"], "remaining_t": need, "deadline": end,
                    "months_left": len(win), "room_t": room,
                    "shortfall_t": max(0.0, need - room), "fits": need <= room,
                    "needed_per_month": need / max(1, len(win))})
    out.sort(key=lambda x: (x["fits"], x["deadline"]))
    return out


@metric("capacity_free",
        title="When have I got production capacity free?",
        params=[("months", "how far ahead", "int")], needs=["capacity"],
        follows=['month_pressure', 'capacity_compare', 'fit_new_tender', 'supply_outlook'],
        about="What the plant can make each month, less the draws a private buyer contracted "
              "for that month and the pace needed to clear the tender deadlines. What is "
              "left is what a new order could actually go into.")
def capacity_free(db, tid, defs, p):
    n = min(24, max(1, int(p.get("months", 12))))
    how = defs["capacity"]["params"]["tender_planning"]
    months = _month_list(n)
    cap = _capacity(db, tid, defs, months)

    # the only real monthly obligations in the book
    fixed = {m: 0.0 for m in months}
    fixed_rows = {m: [] for m in months}
    for r in db.fetch(tid, """
            SELECT s.month, s.qty_t, s.tender_ref, t.plant
            FROM src_contract_schedule s
            JOIN src_tender_award t ON t.tender_ref = s.tender_ref
            WHERE s.month >= to_char(%(start)s::date, 'YYYY-MM')
            ORDER BY s.month""", {"start": TODAY}):
        if r["month"] in fixed:
            fixed[r["month"]] += float(r["qty_t"])
            fixed_rows[r["month"]].append({"tender_ref": r["tender_ref"], "plant": r["plant"],
                                           "tonnes": float(r["qty_t"])})

    owed = db.fetch(tid, OWED, {"start": TODAY})
    pace, pace_rows = _pace(owed, months, how)

    # A month with 488 tonnes spare out of 17,318 is not free, it is full. Calling it free
    # because the subtraction came out positive is how somebody ends up bidding for work he
    # has no room to make, so the months carry a state and not just a number.
    ROOM = 0.10                          # a tenth of the month, or it is not worth calling room
    out = []
    for m in months:
        c, f, q = cap[m], fixed[m], pace[m]
        spare = c - f - q
        out.append({"month": m,
                    "capacity_t": c,
                    "scheduled_t": f,                    # contracted for this month
                    "required_t": q,                     # pace needed for the deadlines
                    "committed_t": f + q,
                    "free_t": spare,
                    "oversold_t": max(0.0, -spare),
                    "used_pct": ((f + q) / c * 100) if c else 0,
                    "state": ("oversold" if spare < 0
                              else "full" if c and spare < c * ROOM
                              else "room")})

    spare = {m["month"]: m["free_t"] for m in out}
    runway = _runway(owed, months, spare)
    pool = sum(float(r["remaining"]) for r in owed if r["contract_type"] == "cumulative")
    free = [m for m in out if m["state"] == "room"]
    tight = [m for m in out if m["state"] == "full"]
    over = [m for m in out if m["state"] == "oversold"]

    # the months with room, described the way somebody would say them out loud
    span, contiguous = None, False
    if free:
        idx = [months.index(m["month"]) for m in free]
        contiguous = idx == list(range(idx[0], idx[0] + len(idx)))
        if len(free) == len(out):
            span = "every month"
        elif contiguous and idx[-1] == len(months) - 1:
            span = free[0]["month"] + " onward"
        elif contiguous:
            span = free[0]["month"] + " to " + free[-1]["month"]
    return {"months": out, "planning": how,
            "free_months": free, "tight_months": tight, "oversold_months": over,
            "span": span, "contiguous": contiguous,
            "total_free_t": sum(m["free_t"] for m in free),
            "total_oversold_t": sum(m["oversold_t"] for m in over),
            "tender_pool_t": pool, "runway": runway,
            "at_risk": [r for r in runway if not r["fits"]],
            "fixed_rows": fixed_rows, "pace_rows": pace_rows,
            "first_free": free[0]["month"] if free else None,
            "worst": min(out, key=lambda x: x["free_t"])["month"] if out else None}


@metric("month_pressure",
        title="Why is one month tight, and what could I move out of it?",
        params=[("month", "which month", "month")], needs=["capacity"],
        follows=['open_commitment', 'capacity_free', 'fit_new_tender'],
        about="Splits one month into what is contracted for it and cannot move, and what is "
              "only there because a tender deadline is pulling it forward.")
def month_pressure(db, tid, defs, p):
    m = p.get("month")
    months = _month_list(24)
    if m not in months:
        return {"month": m, "unknown_month": True}

    base = capacity_free(db, tid, defs, {"months": 24})
    row = next(x for x in base["months"] if x["month"] == m)

    fixed = db.fetch(tid, """
        SELECT s.tender_ref, s.qty_t, t.plant
        FROM src_contract_schedule s
        JOIN src_tender_award t ON t.tender_ref = s.tender_ref
        WHERE s.month = %(m)s ORDER BY s.qty_t DESC""", {"m": m})

    # a tender with months to spare can be slowed down. One due this month cannot.
    pace = base["pace_rows"][m]
    movable = [x for x in pace if x["deadline"] > m]
    pinned = [x for x in pace if x["deadline"] <= m]
    return {
        "month": m, "capacity_t": row["capacity_t"],
        "scheduled_t": row["scheduled_t"], "required_t": row["required_t"],
        "free_t": row["free_t"], "over_t": row["oversold_t"],
        "used_pct": row["used_pct"],
        "movable_t": sum(x["tonnes"] for x in movable),
        "pinned_t": sum(x["tonnes"] for x in pinned),
        "movable": sorted(movable, key=lambda x: -x["tonnes"])[:10],
        "pinned": sorted(pinned, key=lambda x: -x["tonnes"])[:10],
        "fixed_rows": [{"tender_ref": r["tender_ref"], "plant": r["plant"],
                        "tonnes": float(r["qty_t"])} for r in fixed],
        # a private schedule can only change by agreement, and no contract here records
        # whether that is allowed, so the machine will not offer an opinion on it
        "reschedule_terms_known": False,
    }


@metric("fit_new_tender",
        title="How much of it can I take on, and when could I make it?",
        params=[("tonnes", "how many tonnes", "int"),
                ("by_month", "deliver by", "month")], needs=["capacity"],
        follows=['quote_for_tender', 'buy_in_cost', 'supply_outlook'],
        about="Runs the quantity against the room actually left in each month up to the "
              "deadline, and says not just whether it fits but how comfortably.")
def fit_new_tender(db, tid, defs, p):
    want = float(p.get("tonnes") or 0)
    by = p.get("by_month")
    months = _month_list(24)
    if by not in months or want <= 0:
        return {"unknown_month": by not in months, "tonnes": want}
    upto = months[:months.index(by) + 1]

    # Ask for the whole horizon and then look at the part that matters. Asking only for the
    # months up to the deadline would truncate the window the pace is spread over, and a
    # tender due next March would have its entire remainder charged to this month.
    base = capacity_free(db, tid, defs, {"months": len(months)})
    rows = [m for m in base["months"] if m["month"] in upto]
    avail = sum(max(0.0, m["free_t"]) for m in rows)

    # take it month by month, in order, and record what each month gives up
    fill, left, covered = [], want, None
    running = 0.0
    for m in rows:
        room = max(0.0, m["free_t"])
        take = min(left, room)
        running += take
        left -= take
        if left <= 0 and covered is None:
            covered = m["month"]
        fill.append({"month": m["month"], "room_t": room, "take_t": take,
                     "after_t": room - take, "cumulative_t": running,
                     "eats_pct": (take / room * 100) if room else 0,
                     "state": m["state"], "used_pct": m["used_pct"]})

    used = [f for f in fill if f["take_t"] > 0]
    dry = [f for f in rows if f["free_t"] <= 0]
    worst = max((f["eats_pct"] for f in used), default=0)
    tight = [f for f in used if f["eats_pct"] >= 80]

    # How comfortably this fits is a question about how much room there is against how much
    # is wanted. It is not a question about the order the fill happened to run in.
    #
    # Filling earliest month first drains a tight October before it touches a wide open
    # June, so the hardest month reads as a hundred percent even when there is thirty six
    # times the room needed further out. Judging comfort on that made a comfortable yes come
    # back looking like a warning.
    headroom = (avail / want) if want else 0
    return {"tonnes": want, "by_month": by, "months_available": len(upto),
            "room_covers_pct": headroom * 100,
            "free_t": avail, "shortfall_t": max(0.0, want - running),
            "fits": want <= avail, "covered_by": covered,
            "fill": fill, "months_used": len(used), "months_dry": len(dry),
            "spare_after_t": avail - running,
            "worst_eats_pct": worst, "tight_months": len(tight),
            "headroom_x": headroom,
            "comfortable": headroom >= 2.0,
            "only_just": headroom < 1.25,
            "rows": rows}


@metric("delivery_runway",
        title="If I take this on, by when could I have it made?",
        params=[("tonnes", "how many tonnes", "int")], needs=["capacity"],
        follows=['quote_for_tender', 'fit_new_tender', 'supply_outlook', 'buy_in_cost'],
        about="No deadline required. It adds up the room month by month and says when the "
              "total first covers the order, so a delivery date can be quoted rather than "
              "guessed at.")
def delivery_runway(db, tid, defs, p):
    want = float(p.get("tonnes") or 0)
    if want <= 0:
        return {"no_quantity": True}

    months = _month_list(24)
    base = capacity_free(db, tid, defs, {"months": len(months)})

    run, rows, ready = 0.0, [], None
    for m in base["months"]:
        room = max(0.0, m["free_t"])
        before = run
        run += room
        rows.append({"month": m["month"], "room_t": room, "cumulative_t": run,
                     "state": m["state"], "capacity_t": m["capacity_t"],
                     "covers": run >= want,
                     # how much of the order is still outstanding at the end of this month
                     "still_short_t": max(0.0, want - run)})
        if ready is None and run >= want:
            ready = {"month": m["month"], "cumulative_t": run,
                     "months_out": len(rows),
                     # the last month contributes only part of its room
                     "part_of_month": want - before}

    # the milestones somebody would actually quote against
    marks = []
    for k in (3, 6, 12):
        if k <= len(rows):
            marks.append({"months": k, "month": rows[k - 1]["month"],
                          "tonnes": rows[k - 1]["cumulative_t"]})

    return {"tonnes": want, "ready": ready, "rows": rows, "marks": marks,
            "total_room_t": run,
            "never": ready is None,
            "first_month_with_room": next((r["month"] for r in rows if r["room_t"] > 0),
                                          None),
            "dead_months": sum(1 for r in rows if r["room_t"] <= 0)}


@metric("capacity_compare",
        title="Why can I make less in one month than another?",
        params=[("month_a", "this month", "month"), ("month_b", "against this one", "month")],
        needs=["capacity"],
        follows=['capacity_free', 'material_by_month', 'production_cost'],
        about="Every year the register holds for those two calendar months, side by side, "
              "with how each one ran against its own plan and how much feedstock it took "
              "to make a tonne.")
def capacity_compare(db, tid, defs, p):
    a, b = p.get("month_a"), p.get("month_b")
    if not a or not b or a == b:
        return {"bad_params": True, "month_a": a, "month_b": b}
    rows = db.fetch(tid, """
        SELECT month, right(month, 2) AS mm, opening_stock_t, planned_qty_t,
               actual_qty_t, feedstock_consumed_t
        FROM src_production_register
        WHERE right(month, 2) IN (%(a)s, %(b)s)
        ORDER BY month""", {"a": a[5:7], "b": b[5:7]})

    def side(mm):
        rs = [r for r in rows if r["mm"] == mm]
        if not rs:
            return None
        act = [float(r["actual_qty_t"]) for r in rs]
        plan = [float(r["planned_qty_t"] or 0) for r in rs]
        feed = [float(r["feedstock_consumed_t"] or 0) for r in rs]
        made = sum(act)
        return {"mm": mm, "years": len(rs),
                "avg_t": made / len(rs), "best_t": max(act), "worst_t": min(act),
                "avg_plan_t": sum(plan) / len(rs),
                "hit_plan_pct": (made / sum(plan) * 100) if sum(plan) else None,
                "feed_per_t": (sum(feed) / made) if made else None,
                "rows": [{"month": r["month"], "planned_t": float(r["planned_qty_t"] or 0),
                          "actual_t": float(r["actual_qty_t"]),
                          "feed_t": float(r["feedstock_consumed_t"] or 0)} for r in rs]}

    A, B = side(a[5:7]), side(b[5:7])
    if not A or not B:
        return {"no_history": True, "month_a": a, "month_b": b}
    # Always measured against the larger month, so naming the two months in the other
    # order gives the same percentage. With the smaller as the base it changed from 12.5 to
    # 14.3 for the same pair of numbers, which is two answers to one question.
    hi = max(A["avg_t"], B["avg_t"])
    return {
        "month_a": a, "month_b": b, "a": A, "b": B,
        "gap_t": A["avg_t"] - B["avg_t"],
        "gap_pct": (abs(A["avg_t"] - B["avg_t"]) / hi * 100) if hi else None,
        "gap_base_t": hi,
        "consistent": all(x["actual_t"] for x in A["rows"]),
        # The register records what was made. Nothing in this company records a breakdown,
        # a shift that did not turn up, or a wet fortnight, so the cause is not in here and
        # the metric says so rather than inventing one.
        "cause_recorded": False,
    }


# ================================================================ what the market offers
@metric("material_by_month",
        title="Which raw material can I get in which month, and at what cost per unit of energy?",
        params=[], needs=[],
        follows=['production_cost', 'buy_in_cost', 'supply_outlook'],
        about="Every purchase in the book, grouped by calendar month and material, priced "
              "per kilocalorie rather than per tonne, with how much energy the market "
              "actually put in front of us in that month.")
def material_by_month(db, tid, defs, p):
    rows = db.fetch(tid, f"""
        WITH pu AS ({PURCHASES})
        SELECT to_char(txn_date, 'MM')                   AS mm,
               stock_item_name                           AS material,
               sum(amount) / nullif(sum(tonnes), 0)      AS rate_per_t,
               sum(tonnes)                               AS tonnes,
               count(DISTINCT to_char(txn_date, 'YYYY')) AS years,
               count(*)                                  AS n
        FROM pu WHERE channel = 'feedstock'
        GROUP BY 1, 2 ORDER BY 1, 2""")
    gcv = {r["material"]: float(r["gcv"]) for r in db.fetch(tid, """
        SELECT code AS material, gcv_typical AS gcv FROM item WHERE kind = 'feedstock'""")}

    cells = []
    for r in rows:
        g = gcv.get(r["material"])
        if not g:
            continue                                   # no GCV, no rate per kilocalorie
        t = float(r["tonnes"]) / max(1, r["years"])    # a typical year, not three summed
        rate = float(r["rate_per_t"])
        cells.append({"mm": r["mm"], "month": MONTH_NAME[r["mm"]], "material": r["material"],
                      "rate_per_t": rate, "gcv": g, "cost_per_gcv": rate / g,
                      "tonnes": t, "energy_gcal": t * g / 1000.0, "n": r["n"]})

    by_month = {}
    for c in cells:
        by_month.setdefault(c["mm"], []).append(c)
    summary = []
    for mm in sorted(by_month):
        cs = by_month[mm]
        best = min(cs, key=lambda x: x["cost_per_gcv"])
        summary.append({"mm": mm, "month": MONTH_NAME[mm],
                        "best_material": best["material"],
                        "best_cost_per_gcv": best["cost_per_gcv"],
                        # the tonnage that actually comes at that price, not the month's
                        # total across every material. Quoting one and pricing the other
                        # plans a purchase against a supply that does not exist
                        "best_tonnes": best["tonnes"],
                        "best_energy_gcal": best["energy_gcal"],
                        "energy_gcal": sum(c["energy_gcal"] for c in cs),
                        "tonnes": sum(c["tonnes"] for c in cs),
                        "materials": len(cs)})
    cheapest = min(summary, key=lambda x: x["best_cost_per_gcv"]) if summary else None
    dearest = max(summary, key=lambda x: x["best_cost_per_gcv"]) if summary else None
    spread = None
    if cheapest and dearest and cheapest["best_cost_per_gcv"]:
        spread = round((dearest["best_cost_per_gcv"] / cheapest["best_cost_per_gcv"] - 1) * 100, 1)
    return {"cells": cells, "months": summary,
            # the materials that actually turned up, not every code in the item master
            "materials": sorted({c["material"] for c in cells}),
            "known_codes": sorted(gcv),
            "cheapest_month": cheapest, "dearest_month": dearest, "spread_pct": spread}


@metric("supply_outlook",
        title="How much material can I actually count on, month by month?",
        params=[("months", "how far ahead", "int")], needs=["capacity", "vendor_reliability"],
        follows=['material_by_month', 'capacity_free', 'vendor_reliability'],
        about="Three lines instead of one: what the plant makes itself, what vendors have "
              "confirmed in writing, and the ceiling if every unconfirmed promise also "
              "lands. The gap between the floor and the ceiling is the real answer.")
def supply_outlook(db, tid, defs, p):
    n = min(24, max(1, int(p.get("months", 12))))
    months = _month_list(n)
    cap = _capacity(db, tid, defs, months)

    # A commitment a person confirmed is a floor. One the extractor proposed and nobody
    # confirmed is not something to plan on, so it only ever raises the ceiling.
    rows = db.fetch(tid, """
        SELECT to_char(c.promised_date, 'YYYY-MM') AS month,
               c.status, pt.name AS vendor, sum(c.qty_t) AS qty_t, count(*) AS n
        FROM vendor_commitment c
        JOIN party pt ON pt.party_id = c.party_id
        WHERE to_char(c.promised_date, 'YYYY-MM') = ANY(%(ms)s)
        GROUP BY 1, 2, 3 ORDER BY 1""", {"ms": months})

    kept = {r["vendor"]: float(r["kept"] or 0) for r in db.fetch(tid, """
        SELECT pt.name AS vendor,
               coalesce(sum(g.qty_qtl) / 10.0, 0) / nullif(sum(c.qty_t), 0) AS kept
        FROM vendor_commitment c
        JOIN party pt ON pt.party_id = c.party_id
        LEFT JOIN LATERAL (
            SELECT sum(qty_qtl) AS qty_qtl FROM src_goods_receipt r
            WHERE r.vendor_name = pt.name
              AND r.received_date BETWEEN c.promised_date - 7 AND c.promised_date + 30
        ) g ON true
        GROUP BY pt.name""")}

    out = {m: {"month": m, "own_t": cap[m], "firm_t": 0.0, "unconfirmed_t": 0.0,
               "likely_t": 0.0, "vendors": []} for m in months}
    for r in rows:
        m, q = r["month"], float(r["qty_t"])
        k = min(1.0, kept.get(r["vendor"], 0.0))
        if r["status"] == "confirmed":
            out[m]["firm_t"] += q
            out[m]["likely_t"] += q
        else:
            out[m]["unconfirmed_t"] += q
            out[m]["likely_t"] += q * k       # discounted by what that vendor has ever kept
        out[m]["vendors"].append({"vendor": r["vendor"], "tonnes": q,
                                  "status": r["status"], "kept_pct": round(k * 100, 1)})
    series = []
    for m in months:
        o = out[m]
        o["floor_t"] = o["own_t"] + o["firm_t"]
        o["expected_t"] = o["own_t"] + o["likely_t"]
        o["ceiling_t"] = o["own_t"] + o["firm_t"] + o["unconfirmed_t"]
        o["vendors"] = sorted(o["vendors"], key=lambda v: -v["tonnes"])[:8]
        series.append(o)
    firm_total = sum(o["firm_t"] for o in series)
    unconf_total = sum(o["unconfirmed_t"] for o in series)
    return {"months": series,
            # No promise at all and a promise nobody has checked are different problems.
            # Only the second one is about trust, and saying so when the truth is the first
            # sends somebody looking through a review queue that has nothing in it.
            "nothing_promised": firm_total <= 0 and unconf_total <= 0,
            "floor_t": sum(o["floor_t"] for o in series),
            "expected_t": sum(o["expected_t"] for o in series),
            "ceiling_t": sum(o["ceiling_t"] for o in series),
            "firm_t": firm_total,
            "unconfirmed_t": sum(o["unconfirmed_t"] for o in series),
            "any_confirmed": firm_total > 0}


# ================================================================ cost and quoting
@metric("material_cost_per_gcv",
        title="Which raw material is cheaper per unit of energy?",
        params=[], needs=[],
        follows=['material_by_month', 'production_cost'],
        about="Rate per tonne against rate per GCV. The two can disagree.")
def material_cost_per_gcv(db, tid, defs, p):
    rows = db.fetch(tid, f"""
        WITH pu AS ({PURCHASES})
        SELECT stock_item_name AS material,
               sum(amount) / nullif(sum(tonnes), 0) AS rate_per_t,
               count(*) AS n
        FROM pu WHERE channel = 'feedstock'
        GROUP BY 1 ORDER BY 2""")
    gcv = {r["material"]: float(r["gcv"]) for r in db.fetch(tid, """
        SELECT code AS material, gcv_typical AS gcv FROM item WHERE kind = 'feedstock'""")} \
        or {"Rice Husk": 3000, "Mustard Stalk": 3350, "Cotton Stalk": 3200}
    out = []
    for r in rows:
        g = gcv.get(r["material"], 3200)
        out.append({"material": r["material"], "rate_per_t": float(r["rate_per_t"]),
                    "gcv": g, "cost_per_gcv": float(r["rate_per_t"]) / g, "n": r["n"]})
    out.sort(key=lambda x: x["cost_per_gcv"])
    return {"rows": out, "cheapest_energy": out[0]["material"] if out else None,
            "cheapest_per_tonne": min(out, key=lambda x: x["rate_per_t"])["material"] if out else None}


@metric("production_cost",
        title="What does a tonne cost me to make, month by month?",
        params=[("grade_code", "product", "grade")], needs=[],
        follows=['buy_in_cost', 'quote_for_tender', 'material_by_month'],
        about="Feedstock at each calendar month's own rate, times the conversion ratio, "
              "plus conversion cost. Both of those come from the plant's config, not from "
              "a number somebody typed into the code.")
def production_cost(db, tid, defs, p):
    grade = p.get("grade_code")
    cfg = _config(db, tid)
    if "feed_per_pellet" not in cfg or "conversion_cost" not in cfg:
        return {"missing_config": [k for k in ("feed_per_pellet", "conversion_cost")
                                   if k not in cfg]}
    FEED, CONV = float(cfg["feed_per_pellet"]), float(cfg["conversion_cost"])

    rows = db.fetch(tid, f"""
        WITH pu AS ({PURCHASES})
        SELECT to_char(txn_date, 'MM') AS mm,
               sum(amount) / nullif(sum(tonnes), 0) AS feed_rate,
               count(*) AS n
        FROM pu WHERE channel = 'feedstock' GROUP BY 1 ORDER BY 1""")
    it = db.fetch_one(tid, """
        SELECT gcv_typical, gcv_min, gcv_max FROM item
        WHERE code = %(g)s AND kind = 'pellet' ORDER BY valid_from DESC LIMIT 1""",
        {"g": grade})
    if not it:
        return {"no_such_grade": grade}

    out = []
    for r in rows:
        feed = float(r["feed_rate"])
        per_t = FEED * feed + CONV
        out.append({"month": MONTH_NAME[r["mm"]], "mm": r["mm"],
                    "feed_rate_per_t": feed,
                    "feed_cost_per_t": FEED * feed,
                    "conversion_per_t": CONV,
                    "cost_per_t": per_t,
                    "cost_per_gcv": per_t / float(it["gcv_typical"]),
                    "cost_per_gcv_worst": per_t / float(it["gcv_min"]),
                    "n": r["n"]})
    if not out:
        return {"no_purchases": True}
    out.sort(key=lambda x: x["cost_per_gcv"])
    return {"grade": grade, "gcv_typical": float(it["gcv_typical"]),
            "gcv_min": float(it["gcv_min"]), "gcv_max": float(it["gcv_max"]),
            "feed_per_pellet": FEED, "conversion_cost": CONV,
            "cheapest": out[0], "dearest": out[-1],
            "rows": sorted(out, key=lambda x: x["mm"])}


@metric("quote_for_tender",
        title="What should I quote, and how did that number come out?",
        params=[("grade_code", "product", "grade"),
                ("deliver_from", "delivering from", "month"),
                ("deliver_to", "delivering until", "month"),
                ("quoted_gcv", "GCV I intend to quote", "int"),
                ("margin_per_gcv", "margin I want, rupees per GCV", "float")],
        needs=[], follows=['production_cost', 'capacity_free', 'material_by_month', 'realised_price'],
        about="A quote is not a property of a product. It is a property of the months you "
              "will actually be producing in, because feedstock is seasonal. This works "
              "through the delivery window month by month and shows every step.")
def quote_for_tender(db, tid, defs, p):
    cfg = _config(db, tid)
    need = ("gcv_floor_full", "gcv_reject", "gcv_penalty", "gcv_quote_step")
    missing = [k for k in need if k not in cfg]
    base = production_cost(db, tid, defs, {"grade_code": p["grade_code"]})
    if missing or "rows" not in base:
        return {"missing_config": missing or base.get("missing_config"),
                "no_such_grade": base.get("no_such_grade")}

    FLOOR = float(cfg["gcv_floor_full"])
    REJECT = float(cfg["gcv_reject"])
    PENALTY = float(cfg["gcv_penalty"])
    STEP = float(cfg["gcv_quote_step"])
    gcv = float(p["quoted_gcv"])
    margin = float(p["margin_per_gcv"])

    # A quoted GCV outside the range this trade works in is not a quote, it is a typo, and
    # 12 GCV happily produces a confident Rs 26 a tonne. The bounds come from the contract
    # terms already in config: below the rejection floor there is no contract to bid on,
    # and no biomass pellet in this market runs past 5,000.
    prod_gcv_check = float(base["gcv_typical"])
    if gcv > prod_gcv_check:
        # The answer's own warning is that quoting high and delivering low is not a
        # rounding error. Quoting above what this product tests at is exactly that, done
        # deliberately, so it is refused rather than priced.
        return {"quoted_above_product": True, "quoted_gcv": gcv,
                "product_gcv": prod_gcv_check, "grade": p["grade_code"],
                "shortfall_per_t": (gcv - prod_gcv_check) * (margin + 1.0)}
    if gcv < REJECT or gcv > 5000:
        return {"gcv_out_of_range": True, "quoted_gcv": gcv,
                "floor": REJECT, "ceiling": 5000.0}
    if margin < 0:
        return {"negative_margin": True, "margin": margin}

    # the months the delivery window actually covers. This is the whole correction: you do
    # not get to price off your best ever month unless you are producing in it.
    a = p.get("deliver_from") or _month_list(1)[0]
    b = p.get("deliver_to") or _month_list(12)[-1]
    reversed_window = b < a
    if reversed_window:
        a, b = b, a
    span, y, m = [], int(a[:4]), int(a[5:7])
    while f"{y}-{m:02d}" <= b and len(span) < 36:
        span.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1

    by_mm = {r["mm"]: r for r in base["rows"]}
    window = []
    for mo in span:
        r = by_mm.get(mo[5:7])
        if r:
            window.append(dict(r, month_key=mo))
    if not window:
        return {"no_history_for_window": True, "from": a, "to": b}

    avg_t = sum(w["cost_per_t"] for w in window) / len(window)
    avg_feed = sum(w["feed_rate_per_t"] for w in window) / len(window)
    best = min(window, key=lambda w: w["cost_per_t"])
    worst = max(window, key=lambda w: w["cost_per_t"])
    prod_gcv = base["gcv_typical"]
    cost_per_gcv = avg_t / prod_gcv
    quote_per_gcv = cost_per_gcv + margin
    quote_per_t = quote_per_gcv * gcv

    # The working, in the order somebody would do it on paper. Every line carries the two
    # numbers it came from, so nothing in the chain has to be taken on trust.
    working = [
        {"step": "Months you will be producing in",
         "detail": f"{len(window)} months, {span[0]} to {span[-1]}",
         "value": len(window), "unit": "months"},
        {"step": "Feedstock, averaged over those months",
         "detail": f"cheapest {best['month']} at {best['feed_rate_per_t']:.0f}, "
                   f"dearest {worst['month']} at {worst['feed_rate_per_t']:.0f}",
         "value": avg_feed, "unit": "Rs per tonne of residue"},
        {"step": "Residue needed for one tonne of pellets",
         "detail": "from the plant config, not from the code",
         "value": base["feed_per_pellet"], "unit": "tonnes"},
        {"step": "Feedstock in a tonne of product",
         "detail": f"{avg_feed:.0f} x {base['feed_per_pellet']}",
         "value": avg_feed * base["feed_per_pellet"], "unit": "Rs per tonne"},
        {"step": "Conversion and overhead",
         "detail": "from the plant config",
         "value": base["conversion_cost"], "unit": "Rs per tonne"},
        {"step": "Cost to make a tonne, in this window",
         "detail": f"{avg_feed * base['feed_per_pellet']:.0f} + {base['conversion_cost']:.0f}",
         "value": avg_t, "unit": "Rs per tonne"},
        {"step": "What that tonne is worth in energy",
         "detail": f"{p['grade_code']} runs at {prod_gcv:.0f} GCV",
         "value": prod_gcv, "unit": "GCV"},
        {"step": "Cost of one unit of energy",
         "detail": f"{avg_t:.0f} / {prod_gcv:.0f}",
         "value": cost_per_gcv, "unit": "Rs per GCV"},
        {"step": "Margin you asked for",
         "detail": "your input",
         "value": margin, "unit": "Rs per GCV"},
        {"step": "Rate to quote, per unit of energy",
         "detail": f"{cost_per_gcv:.3f} + {margin:.3f}",
         "value": quote_per_gcv, "unit": "Rs per GCV"},
        {"step": "Rate to quote, per tonne",
         "detail": f"{quote_per_gcv:.3f} x {gcv:.0f} GCV quoted",
         "value": quote_per_t, "unit": "Rs per tonne"},
    ]

    # The same arithmetic as the working, expressed in rupees a tonne so it can be drawn
    # as one stack. Everything is scaled to the GCV being quoted, because that is the tonne
    # the buyer is paying for, not the tonne we happen to make.
    scale = gcv / prod_gcv
    feed_share = avg_feed * base["feed_per_pellet"] * scale
    conv_share = base["conversion_cost"] * scale
    margin_share = margin * gcv
    build = [
        {"label": "Feedstock", "value": feed_share,
         "note": f"{avg_feed:,.0f} a tonne of residue, times {base['feed_per_pellet']}"},
        {"label": "Conversion and overhead", "value": conv_share,
         "note": "from the plant's own config"},
        {"label": "Cost to make it", "value": feed_share + conv_share, "total": True,
         "note": f"at the {gcv:,.0f} GCV you are quoting"},
        {"label": "Your margin", "value": margin_share,
         "note": f"{margin:.3f} per unit of GCV, times {gcv:,.0f} quoted"},
        {"label": "Quote", "value": feed_share + conv_share + margin_share, "total": True,
         "note": "rupees a tonne"},
    ]
    return {"grade": p["grade_code"], "from": span[0], "to": span[-1],
            "reversed_window": reversed_window,
            "build": build,
            "feed_share": feed_share, "conv_share": conv_share,
            "margin_share": margin_share,
            "months": len(window), "window": window,
            "feed_rate_per_t": avg_feed, "feed_per_pellet": base["feed_per_pellet"],
            # every intermediate the working quotes, so the gate can account for each one
            "best_feed_rate": best["feed_rate_per_t"],
            "worst_feed_rate": worst["feed_rate_per_t"],
            "feed_in_a_tonne": avg_feed * base["feed_per_pellet"],
            "conversion_cost": base["conversion_cost"],
            "cost_per_t": avg_t, "product_gcv": prod_gcv,
            "cost_per_gcv": cost_per_gcv, "margin_per_gcv": margin,
            "quote_per_gcv": quote_per_gcv, "quoted_gcv": gcv,
            "quote_per_t": quote_per_t,
            "best_month": best["month"], "best_cost_per_t": best["cost_per_t"],
            "worst_month": worst["month"], "worst_cost_per_t": worst["cost_per_t"],
            "swing_per_t": worst["cost_per_t"] - best["cost_per_t"],
            "working": working,
            # what the same quote is worth if the load lands in a lower band
            "gcv_floor": FLOOR, "gcv_reject": REJECT, "gcv_penalty": PENALTY,
            "if_below_floor": quote_per_gcv * (FLOOR - STEP) * (1 - PENALTY),
            "gcv_test": FLOOR - STEP,
            "gcv_step": STEP,
            "per_step_gcv": quote_per_gcv * STEP}


@metric("buy_in_cost",
        title="What does it cost to buy finished pellets in, and from whom?",
        params=[("grade_code", "against making this yourself", "grade")],
        needs=[],
        follows=['fit_new_tender', 'capacity_free', 'realised_price'],
        about="Every purchase of finished pellets, by month and by vendor, priced per "
              "kilocalorie and set against what the same tonne costs to make in that month.")
def buy_in_cost(db, tid, defs, p):
    grade = p.get("grade_code")
    own = production_cost(db, tid, defs, {"grade_code": grade})
    if "rows" not in own:
        return {"no_such_grade": grade, "missing_config": own.get("missing_config")}
    own_by_mm = {r["mm"]: r for r in own["rows"]}
    gcv_own = float(own["gcv_typical"])

    gcv_row = db.fetch_one(tid, """
        SELECT gcv_typical FROM item
        WHERE kind = 'feedstock' AND code = 'Bought-In Pellets' LIMIT 1""")
    if not gcv_row:
        return {"no_gcv": True}
    gcv = float(gcv_row["gcv_typical"])

    rows = db.fetch(tid, f"""
        WITH pu AS ({PURCHASES})
        SELECT to_char(txn_date, 'MM')            AS mm,
               ledger_name                        AS vendor,
               sum(tonnes)                        AS tonnes,
               sum(amount) / nullif(sum(tonnes), 0) AS rate_per_t,
               count(*)                           AS lots,
               min(txn_date)                      AS first_seen,
               max(txn_date)                      AS last_seen
        FROM pu WHERE channel = 'finished'
        GROUP BY 1, 2 ORDER BY 1, 4""")
    if not rows:
        return {"never_bought": True, "grade": grade}

    buys = []
    for r in rows:
        rate = float(r["rate_per_t"])
        mine = own_by_mm.get(r["mm"])
        buys.append({
            "mm": r["mm"], "month": MONTH_NAME[r["mm"]], "vendor": r["vendor"],
            "tonnes": float(r["tonnes"]), "lots": r["lots"],
            "rate_per_t": rate, "gcv": gcv, "cost_per_gcv": rate / gcv,
            "make_per_t": mine["cost_per_t"] if mine else None,
            "make_per_gcv": mine["cost_per_gcv"] if mine else None,
            # the only comparison that means anything: rupees for the same heat
            "gap_per_gcv": (rate / gcv - mine["cost_per_gcv"]) if mine else None,
            "cheaper_to_buy": bool(mine and rate / gcv < mine["cost_per_gcv"]),
            "first_seen": str(r["first_seen"]), "last_seen": str(r["last_seen"])})

    # What the decision was actually worth, in rupees.
    #
    # It cannot be done per tonne without lying: a bought-in pellet runs at a different GCV
    # from ours, so a tonne of theirs is not a tonne of ours. So price the energy. Take the
    # energy we bought, work out what making that much energy here would have cost, and the
    # difference is the money the decision moved.
    for b in buys:
        b["energy_gcal"] = b["tonnes"] * b["gcv"] / 1000.0
        b["spent"] = b["tonnes"] * b["rate_per_t"]
        if b["make_per_gcv"] is not None:
            b["make_same_energy"] = b["tonnes"] * b["gcv"] * b["make_per_gcv"]
            b["extra_spent"] = b["spent"] - b["make_same_energy"]
            # and the like for like tonnage: how many tonnes of our own product carry the
            # same heat as one tonne of theirs
            b["our_tonnes_for_theirs"] = b["gcv"] / gcv_own
            b["make_per_t"] = b["make_per_gcv"] * gcv_own
        else:
            b["make_same_energy"] = b["extra_spent"] = None
            b["our_tonnes_for_theirs"] = b["make_per_t"] = None

    cheapest = min(buys, key=lambda b: b["cost_per_gcv"])
    dearest = max(buys, key=lambda b: b["cost_per_gcv"])
    wins = [b for b in buys if b["cheaper_to_buy"]]
    # A month is cheaper to buy in if the tonnage weighted rate for that month beats what
    # the plant would have spent. Counting vendor lots and calling them months turns three
    # months into fifteen.
    months_seen = sorted({b["mm"] for b in buys})
    month_wins = []
    for mm in months_seen:
        here = [b for b in buys if b["mm"] == mm]
        tot = sum(b["tonnes"] for b in here) or 1.0
        rate = sum(b["cost_per_gcv"] * b["tonnes"] for b in here) / tot
        mine = here[0]["make_per_gcv"]
        if mine is not None and rate < mine:
            month_wins.append({"mm": mm, "month": here[0]["month"], "buy_per_gcv": rate,
                               "make_per_gcv": mine, "gap": mine - rate,
                               "tonnes": tot,
                               "vendors": sorted({b["vendor"] for b in here})})
    by_vendor = {}
    for b in buys:
        v = by_vendor.setdefault(b["vendor"], {"vendor": b["vendor"], "tonnes": 0.0,
                                               "spend": 0.0, "lots": 0, "months": set()})
        v["tonnes"] += b["tonnes"]
        v["spend"] += b["tonnes"] * b["rate_per_t"]
        v["lots"] += b["lots"]
        v["months"].add(b["month"])
    vendors = sorted(({"vendor": v["vendor"], "tonnes": v["tonnes"], "lots": v["lots"],
                       "months": len(v["months"]),
                       "rate_per_t": v["spend"] / v["tonnes"] if v["tonnes"] else 0,
                       "cost_per_gcv": (v["spend"] / v["tonnes"] / gcv) if v["tonnes"] else 0}
                      for v in by_vendor.values()), key=lambda v: v["cost_per_gcv"])

    priced = [b for b in buys if b["extra_spent"] is not None]
    spent = sum(b["spent"] for b in priced)
    would_have = sum(b["make_same_energy"] for b in priced)
    return {"grade": grade, "gcv": gcv, "own_gcv": gcv_own,
            "rows": buys, "vendors": vendors,
            "tonnes": sum(b["tonnes"] for b in buys),
            "energy_gcal": sum(b["energy_gcal"] for b in buys),
            "feed_per_pellet": own["feed_per_pellet"],
            "conversion_cost": own["conversion_cost"],
            # the money, which is the answer he is actually after
            "spent": spent,
            "would_have_cost_to_make": would_have,
            "extra_spent": spent - would_have,
            "make_cheapest_per_t": own["cheapest"]["cost_per_t"],
            "make_dearest_per_t": own["dearest"]["cost_per_t"],
            "buy_cheapest_per_t": cheapest["rate_per_t"],
            "buy_dearest_per_t": dearest["rate_per_t"],
            "cheapest": cheapest, "dearest": dearest,
            "months_cheaper_to_buy": len(month_wins),
            "months_seen": len(months_seen),
            "month_wins": month_wins,
            # the decision worth acting on is the biggest saving, not the lowest ticket
            "best_buy": max(month_wins, key=lambda b: b["gap"]) if month_wins else None,
            "lots_cheaper_to_buy": len(wins),
            "own_cheapest": own["cheapest"], "own_dearest": own["dearest"]}


# ================================================================ vendors
@metric("vendor_reliability",
        title="Which vendors keep their word?",
        params=[("vendor", "vendor, or leave blank for all", "vendor_opt")],
        needs=["vendor_reliability"],
        follows=['supply_outlook', 'buy_in_cost', 'material_by_month'],
        about="What was promised in email against what actually arrived. Only commitments "
              "a person has confirmed count, because a score built on an extraction nobody "
              "checked is a guess wearing a percentage sign.")
def vendor_reliability(db, tid, defs, p):
    d = defs["vendor_reliability"]["params"]
    minobs = int(d["min_observations"])
    want = p.get("vendor") or None
    rows = db.fetch(tid, """
        SELECT c.party_id, pt.name AS vendor,
               count(*) FILTER (WHERE c.status = 'confirmed') AS promised_times,
               count(*)                                       AS extracted,
               count(*) FILTER (WHERE c.status = 'confirmed') AS confirmed
        FROM vendor_commitment c
        LEFT JOIN party pt ON pt.party_id = c.party_id
        GROUP BY 1, 2""")
    if not rows:
        # commitments have not been pulled out of the mail at all yet
        return {"rows": [], "not_extracted": True, "min_observations": minobs}
    out = [dict(r) for r in rows if not want or r["vendor"] == want]
    # The parser read them. Nobody has agreed that it read them correctly. Until somebody
    # does, there is no evidence here, only a proposal, and a reliability score built on a
    # proposal is exactly the kind of confident wrong number this product exists to avoid.
    if not any(r["confirmed"] for r in out):
        return {"rows": out, "unconfirmed_only": True,
                "extracted": sum(r["extracted"] for r in out),
                "min_observations": minobs}
    return {"rows": out, "min_observations": minobs,
            "thin": [r for r in out if r["promised_times"] < minobs]}


@metric("vendor_capacity",
        title="How much more could a vendor supply us?",
        params=[("vendor", "vendor", "vendor")], needs=[],
        follows=['vendor_reliability', 'material_by_month'],
        about="Never recorded anywhere. This one always refuses, on purpose.")
def vendor_capacity(db, tid, defs, p):
    rows = db.fetch(tid, f"""
        WITH pu AS ({PURCHASES})
        SELECT to_char(txn_date, 'YYYY-MM') AS month, sum(tonnes) AS t
        FROM pu WHERE ledger_name = %(v)s GROUP BY 1 ORDER BY 2 DESC""",
        {"v": p["vendor"]})
    return {"vendor": p["vendor"], "months_traded": len(rows),
            "best_month_t": float(rows[0]["t"]) if rows else 0,
            "never_recorded": True}


# ================================================================ money
@metric("realised_price",
        title="What did we actually get per tonne?",
        params=[("plant", "plant", "plant"), ("fy", "financial year", "fy")],
        needs=["realised_price"],
        follows=['production_cost', 'dispatch_total', 'outstanding'],
        about="What landed in the bank, against what was billed.")
def realised_price(db, tid, defs, p):
    d = defs["realised_price"]["params"]
    rows = db.fetch(tid, """
        SELECT count(*) FILTER (WHERE v.voucher_type = 'Sales')      AS invoices,
               sum(CASE WHEN v.voucher_type = 'Sales'
                        THEN v.amount ELSE 0 END)                    AS billed,
               sum(CASE WHEN v.voucher_type = 'Credit Note'
                        THEN v.amount ELSE 0 END)                    AS deducted
        FROM src_tally_voucher v
        WHERE v.voucher_type IN ('Sales', 'Credit Note')
          AND v.ledger_name = %(plant)s
          AND to_date(v.vch_date, 'DD-Mon-YYYY')
              BETWEEN %(start)s AND %(end)s""",
        {"plant": p["plant"], "start": p["fy_start"], "end": p["fy_end"]})
    tons = db.fetch_one(tid, """
        SELECT coalesce(sum(qty_net_t), 0) AS t FROM src_dispatch_register
        WHERE destination = upper(%(plant)s)
          AND dispatch_date BETWEEN %(start)s AND %(end)s""",
        {"plant": p["plant"], "start": p["fy_start"], "end": p["fy_end"]})
    r = rows[0]
    billed = float(r["billed"] or 0)
    ded = float(r["deducted"] or 0)
    t = float(tons["t"] or 0)
    value = billed - ded if d["net_of_recoveries"] else billed

    # The tonnage this divides by is the same tonnage dispatch_total will refuse to publish
    # if the register and the books disagree about it. One screen refusing a figure while
    # another quietly divides by it is the failure this product exists to prevent, so the
    # same check runs here and the answer carries the result.
    rec = db.fetch_one(tid, """
        SELECT count(*) AS loads,
               count(*) FILTER (WHERE invoice_no IS NULL) AS uninvoiced,
               coalesce(sum(qty_net_t) FILTER (WHERE invoice_no IS NULL), 0) AS uninvoiced_t
        FROM src_dispatch_register
        WHERE destination = upper(%(plant)s)
          AND dispatch_date BETWEEN %(start)s AND %(end)s""",
        {"plant": p["plant"], "start": p["fy_start"], "end": p["fy_end"]})
    vouchers = db.fetch_one(tid, """
        SELECT count(*) AS n FROM src_tally_voucher
        WHERE voucher_type = 'Sales' AND ledger_name = %(plant)s
          AND to_date(vch_date, 'DD-Mon-YYYY') BETWEEN %(start)s AND %(end)s""",
        {"plant": p["plant"], "start": p["fy_start"], "end": p["fy_end"]})

    out = {"plant": p["plant"], "fy": p["fy"], "invoices": r["invoices"],
           "billed": billed, "deducted": ded, "tonnes": t,
           "net_of_recoveries": d["net_of_recoveries"], "over": d["over"],
           "per_tonne": value / t if t else 0,
           "reg_loads": rec["loads"], "book_vouchers": vouchers["n"],
           "uninvoiced_loads": rec["uninvoiced"],
           "uninvoiced_t": float(rec["uninvoiced_t"]),
           "tonnage_disputed": rec["loads"] != vouchers["n"] or rec["uninvoiced"] > 0}
    if t <= 0:
        # A buyer runs one contract at a time and does not win every year, so an empty year
        # is normal. Say which years this plant did trade in, rather than leaving somebody
        # to work through the dropdown looking for one that answers.
        out["traded"] = [
            {"fy": x["fy"], "tonnes": float(x["t"])} for x in db.fetch(tid, """
            SELECT CASE WHEN extract(month from dispatch_date) >= 4
                        THEN 'FY' || to_char(dispatch_date, 'YY') || '-'
                             || to_char(dispatch_date + interval '1 year', 'YY')
                        ELSE 'FY' || to_char(dispatch_date - interval '1 year', 'YY') || '-'
                             || to_char(dispatch_date, 'YY') END AS fy,
                   sum(qty_net_t) AS t
            FROM src_dispatch_register
            WHERE destination = upper(%(plant)s)
            GROUP BY 1 ORDER BY 1""", {"plant": p["plant"]})]
    return out


@metric("outstanding",
        title="Who owes us money?",
        params=[], needs=["outstanding"], follows=['cash_calendar', 'realised_price', 'dispatch_total'],
        about="Sales raised, less what has been received.")
def outstanding(db, tid, defs, p):
    d = defs["outstanding"]["params"]
    rows = db.fetch(tid, """
        SELECT ledger_name,
               sum(CASE WHEN voucher_type = 'Sales' THEN amount ELSE 0 END)       AS billed,
               sum(CASE WHEN voucher_type = 'Credit Note' THEN amount ELSE 0 END) AS credited,
               sum(CASE WHEN voucher_type = 'Receipt' THEN amount ELSE 0 END)     AS received
        FROM src_tally_voucher
        WHERE voucher_type IN ('Sales', 'Credit Note', 'Receipt')
        GROUP BY 1 ORDER BY 1""")
    out, total = [], 0.0
    billed = credited = received = 0.0
    for r in rows:
        b, c, m = (float(r["billed"] or 0), float(r["credited"] or 0),
                   float(r["received"] or 0))
        billed, credited, received = billed + b, credited + c, received + m
        due = b - c - m
        if due > 1:
            out.append({"party": r["ledger_name"], "outstanding": due,
                        "billed": b, "credited": c, "received": m})
            total += due
    # the three figures the total is made of, so the derivation can show arithmetic rather
    # than assert a sum out of nowhere
    return {"rows": sorted(out, key=lambda x: -x["outstanding"]), "total": total,
            "billed": billed, "credited": credited, "received": received,
            "customers": len(out),
            "net_advances": d["net_advances"]}


@metric("cash_calendar",
        title="How much money is due to land, and in which week?",
        params=[("weeks", "how many weeks ahead", "int")], needs=["outstanding", "overdue"],
        follows=['outstanding', 'realised_price'],
        about="Every unpaid bill, given the due date its own buyer's contract implies, laid "
              "out week by week. A bottling plant pays in fifteen days and a PSU in thirty, "
              "so the same rupee of sales lands in different weeks.")
def cash_calendar(db, tid, defs, p):
    weeks = min(26, max(1, int(p.get("weeks", 8))))
    d = defs["outstanding"]["params"]
    newest_first = d.get("apply_receipts") == "lifo"

    terms = {r["ledger_name"]: r for r in db.fetch(tid, """
        SELECT ledger_name, buyer, kind, pay_days FROM src_buyer_terms""")}

    vouchers = db.fetch(tid, f"""
        SELECT v.ledger_name, v.voucher_type, v.amount, {VCH_DATE} AS d
        FROM src_tally_voucher v
        WHERE v.voucher_type IN ('Sales', 'Credit Note', 'Receipt')
        ORDER BY v.ledger_name, 4""")

    # A receipt says "against bill" and names no bill, so a rule has to decide which one it
    # cleared. The rule is the tenant's, it is in the definitions table, and swapping it
    # moves money between weeks without changing a rupee of the total.
    by_party = {}
    for v in vouchers:
        by_party.setdefault(v["ledger_name"], []).append(v)

    open_bills, unapplied = [], 0.0
    for party, vs in by_party.items():
        bills = [{"date": v["d"], "amount": float(v["amount"])}
                 for v in vs if v["voucher_type"] == "Sales"]
        bills.sort(key=lambda b: b["date"], reverse=newest_first)
        cash = sum(float(v["amount"]) for v in vs
                   if v["voucher_type"] in ("Receipt", "Credit Note"))
        for b in bills:
            take = min(cash, b["amount"])
            cash -= take
            left = b["amount"] - take
            if left > 1:
                days = int(terms.get(party, {}).get("pay_days") or 30)
                open_bills.append({"party": party,
                                   "buyer": (terms.get(party) or {}).get("buyer", party),
                                   "kind": (terms.get(party) or {}).get("kind", ""),
                                   "billed_on": b["date"], "pay_days": days,
                                   "due_on": b["date"] + timedelta(days=days),
                                   "amount": left})
        unapplied += max(0.0, cash)

    buckets, seen = [], TODAY
    overdue = [b for b in open_bills if b["due_on"] < TODAY]
    for i in range(weeks):
        a = seen + timedelta(days=7 * i)
        z = a + timedelta(days=6)
        hits = [b for b in open_bills if a <= b["due_on"] <= z]
        buckets.append({"week": i + 1, "from": a.isoformat(), "to": z.isoformat(),
                        "amount": sum(b["amount"] for b in hits),
                        "bills": len(hits),
                        "by_buyer": _sum_by(hits, "buyer")})
    later = [b for b in open_bills
             if b["due_on"] > seen + timedelta(days=7 * weeks - 1)]
    return {"weeks": buckets,
            "overdue_amount": sum(b["amount"] for b in overdue),
            "overdue_bills": len(overdue),
            "overdue_by_buyer": _sum_by(overdue, "buyer"),
            "in_window": sum(w["amount"] for w in buckets),
            "later_amount": sum(b["amount"] for b in later),
            "total_open": sum(b["amount"] for b in open_bills),
            "unapplied_receipts": unapplied,
            "apply_receipts": d.get("apply_receipts"),
            "terms": sorted(({"buyer": t["buyer"], "kind": t["kind"],
                              "pay_days": t["pay_days"]} for t in terms.values()),
                            key=lambda t: t["pay_days"]),
            "soonest": next((w for w in buckets if w["amount"] > 0), None)}


def _sum_by(rows, key):
    agg = {}
    for r in rows:
        agg[r[key]] = agg.get(r[key], 0.0) + r["amount"]
    return sorted(({"name": k, "amount": v} for k, v in agg.items()),
                  key=lambda x: -x["amount"])


# ================================================================ the ones that refuse
@metric("channel_split",
        title="How much did we produce ourselves, and how much did we buy in?",
        params=[("fy", "financial year", "fy")], needs=[],
        follows=['buy_in_cost', 'production_cost', 'material_by_month'],
        about="Splitting purchases into raw material and bought-in pellets.")
def channel_split(db, tid, defs, p):
    rows = db.fetch(tid, f"""
        WITH pu AS ({PURCHASES})
        SELECT coalesce(channel, 'unknown') AS channel,
               count(*) AS n, sum(tonnes) AS t
        FROM pu WHERE txn_date BETWEEN %(start)s AND %(end)s
        GROUP BY 1""", {"start": p["fy_start"], "end": p["fy_end"]})
    by = {r["channel"]: r for r in rows}
    unknown = by.get("unknown")
    feed = float(by.get("feedstock", {}).get("t", 0) or 0)

    # "How much did we produce ourselves" is the other half of this question and it was not
    # being answered. Raw material tonnage is not production: residue becomes pellets at the
    # plant's own conversion ratio, and 2.8 lakh tonnes of husk is not 2.8 lakh tonnes of
    # pellets. Set beside the bought-in figure without converting it, the comparison is
    # between two different things.
    cfg = _config(db, tid)
    ratio = float(cfg["feed_per_pellet"]) if cfg.get("feed_per_pellet") else None
    made = db.fetch_one(tid, """
        SELECT coalesce(sum(actual_qty_t), 0) AS t FROM src_production_register
        WHERE month BETWEEN to_char(%(start)s::date, 'YYYY-MM')
                        AND to_char(%(end)s::date, 'YYYY-MM')""",
        {"start": p["fy_start"], "end": p["fy_end"]})
    return {"fy": p["fy"],
            "feedstock_t": feed,
            "finished_t": float(by.get("finished", {}).get("t", 0) or 0),
            "feed_per_pellet": ratio,
            # what the residue implies the plant could have made, and what it says it did
            "implied_from_feed_t": (feed / ratio) if ratio else None,
            "made_here_t": float(made["t"]),
            "unknown_n": (unknown or {}).get("n", 0),
            "unknown_t": float((unknown or {}).get("t", 0) or 0)}


def _straddles(recipes, a_start, a_end, b_start, b_end):
    """Did this code mean different things in the two periods being asked about?

    Not "has it ever changed". A product code redefined in April 2025 is irrelevant to a
    comparison of 2023 with 2024, and refusing that comparison is as wrong as making a bad
    one. The test is whether the two periods land on different recipes, or whether either
    period straddles a change on its own."""
    def live(start, end):
        return {r["made_from"] for r in recipes
                if str(r["valid_from"]) <= str(end) and str(r["valid_to"]) >= str(start)}
    in_a, in_b = live(a_start, a_end), live(b_start, b_end)
    if len(in_a) > 1 or len(in_b) > 1:
        return True                      # one of the periods contains the change itself
    return bool(in_a and in_b and in_a != in_b)


@metric("item_period_comparison",
        title="Compare one product across two periods",
        params=[("grade_code", "product", "grade"),
                ("fy_a", "first year", "fy"), ("fy_b", "second year", "fy")],
        needs=[],
        follows=['dispatch_total', 'production_cost'],
        about="Refuses if the code meant different things in the two periods.")
def item_period_comparison(db, tid, defs, p):
    defs_rows = db.fetch(tid, """
        SELECT code, valid_from, valid_to, made_from, gcv_typical
        FROM item WHERE code = %(g)s AND kind = 'pellet' ORDER BY valid_from""",
        {"g": p["grade_code"]})
    out = {}
    for side, s, e in (("a", p["fy_a_start"], p["fy_a_end"]),
                       ("b", p["fy_b_start"], p["fy_b_end"])):
        r = db.fetch_one(tid, """
            SELECT count(*) AS loads, coalesce(sum(qty_net_t), 0) AS t
            FROM src_dispatch_register
            WHERE grade_code = %(g)s AND dispatch_date BETWEEN %(s)s AND %(e)s""",
            {"g": p["grade_code"], "s": s, "e": e})
        out[side] = {"loads": r["loads"], "tonnes": float(r["t"])}
    recipes = {str(r["valid_from"]): r["made_from"] for r in defs_rows}
    # Which year came first is a fact about the calendar, not about the order somebody
    # typed them in. Without this, naming the recent year first reported a fall as a rise.
    swapped = str(p["fy_a_start"]) > str(p["fy_b_start"])
    early, late = ("b", "a") if swapped else ("a", "b")
    return {"grade": p["grade_code"], "fy_a": p["fy_a"], "fy_b": p["fy_b"],
            "same_period": p["fy_a"] == p["fy_b"],
            "earlier_fy": p["fy_b"] if swapped else p["fy_a"],
            "later_fy": p["fy_a"] if swapped else p["fy_b"],
            "earlier": out[early], "later": out[late],
            "a": out["a"], "b": out["b"],
            "recipes": [dict(r) for r in defs_rows],
            # The question is not whether this code has ever meant two things. It is
            # whether it meant two things across the two periods being compared. A recipe
            # that changed in 2025 does not stop FY23-24 being comparable with FY24-25, and
            # refusing that comparison is as wrong as making a bad one.
            "changed_meaning": _straddles(defs_rows, p["fy_a_start"], p["fy_a_end"],
                                          p["fy_b_start"], p["fy_b_end"])}


@metric("dispatch_total",
        title="What did we dispatch in total?",
        params=[("plant", "plant", "plant"), ("fy", "financial year", "fy")],
        needs=[],
        follows=['realised_price', 'open_commitment', 'order_book'],
        about="Refuses if the register and the books disagree on how many loads there were.")
def dispatch_total(db, tid, defs, p):
    reg = db.fetch_one(tid, """
        SELECT count(*) AS loads, coalesce(sum(qty_net_t), 0) AS t,
               count(*) FILTER (WHERE invoice_no IS NULL) AS uninvoiced,
               -- the tonnage sitting on the loads nobody billed, which is what turns the
               -- disagreement into a range a person can actually use
               coalesce(sum(qty_net_t) FILTER (WHERE invoice_no IS NULL), 0) AS uninvoiced_t
        FROM src_dispatch_register
        WHERE destination = upper(%(plant)s)
          AND dispatch_date BETWEEN %(s)s AND %(e)s""",
        {"plant": p["plant"], "s": p["fy_start"], "e": p["fy_end"]})
    books = db.fetch_one(tid, """
        SELECT count(*) AS vouchers FROM src_tally_voucher
        WHERE voucher_type = 'Sales' AND ledger_name = %(plant)s
          AND to_date(vch_date, 'DD-Mon-YYYY') BETWEEN %(s)s AND %(e)s""",
        {"plant": p["plant"], "s": p["fy_start"], "e": p["fy_end"]})
    return {"plant": p["plant"], "fy": p["fy"],
            "register_loads": reg["loads"], "tonnes": float(reg["t"]),
            "book_vouchers": books["vouchers"], "uninvoiced": reg["uninvoiced"],
            "uninvoiced_t": float(reg["uninvoiced_t"])}
