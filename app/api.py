"""
The console, and the API behind it.

    uvicorn app.api:app --reload

One rule shapes every endpoint here: the browser never sends SQL and never sends free text
that becomes SQL. It sends a metric name and typed parameters, and every parameter value it
offers came from a list this API produced out of the database. There is no path from the
address bar to a query.
"""

import json
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import answer, db, definitions, metrics, questions

WEB = pathlib.Path(__file__).resolve().parent / "web"
app = FastAPI(title="Pellet console")


def clean(x):
    """Decimals and dates come back from psycopg in types JSON does not know."""
    from datetime import date, datetime
    from decimal import Decimal
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


@app.get("/")
def landing():
    return FileResponse(WEB / "landing.html")


@app.get("/console")
def console():
    return FileResponse(WEB / "index.html")


@app.get("/api/tenants")
def api_tenants():
    return clean(db.tenants())


@app.get("/api/questions")
def api_questions(tenant: str):
    return clean([{k: v for k, v in q.items()} for q in questions.resolve(tenant)])


@app.get("/api/metrics")
def api_metrics():
    """What can be asked, and what each one needs. The interface builds its form from this,
    so adding a metric adds a question to the console with no front-end change."""
    return [{"name": m["name"], "title": m["title"], "about": m.get("about", ""),
             "params": [{"key": k, "label": lbl, "kind": kind}
                        for k, lbl, kind in m.get("params", [])],
             "needs": m.get("needs", []),
             # What an owner asks next once he has seen this answer. The console offers
             # them as one click, because that is how the conversation actually goes.
             "follows": [f for f in m.get("follows", []) if f in metrics.REGISTRY]}
            for m in metrics.REGISTRY.values()]


_MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _months_ahead(n):
    y, m = metrics.TODAY.year, metrics.TODAY.month
    out = []
    for _ in range(n):
        out.append("%d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _month_label(m):
    return "%s %s" % (_MON[int(m[5:7])], m[:4])


@app.get("/api/options")
def api_options(tenant: str):
    """Every value the interface is allowed to offer, straight out of this tenant's data.
    A parameter the user did not pick from here does not exist."""
    def col(sql, key):
        return [r[key] for r in db.fetch(tenant, sql)]

    # Options carry a readable label as well as a value. "C-24-27" means nothing to
    # somebody seeing it for the first time.
    #
    # The tonnage has to say what it is, too. It was showing the awarded figure with no
    # word attached, next to an answer that works in awarded plus the option clause, and
    # on one contract the awarded figure happened to equal what had already gone out. So it
    # read as "17,300 t delivered" when it meant "17,300 t awarded".
    tenders = [{"value": r["tender_ref"],
                "label": "%s · %s t awarded  (%s)" % (
                    r["plant"], format(float(r["tonnes"]), ",.0f"), r["tender_ref"])}
               for r in db.fetch(tenant, """
                   SELECT tender_ref, plant, tonnes FROM src_tender_award
                   ORDER BY plant, window_start""")]
    return clean({
        "tender": tenders,
        # A plant with two years of history and one with five are different propositions,
        # and the person choosing cannot tell them apart from the name.
        "plant": [{"value": r["plant"], "label": "%s  (%s)" % (
                       r["plant"],
                       "no loads yet" if not r["yrs"] else
                       "1 year" if r["yrs"] == 1 else "%d years" % r["yrs"])}
                  for r in db.fetch(tenant, """
                      SELECT t.plant,
                             count(DISTINCT extract(year from d.dispatch_date)) AS yrs
                      FROM src_tender_award t
                      LEFT JOIN src_dispatch_register d
                             ON d.destination = upper(t.plant)
                      GROUP BY t.plant ORDER BY t.plant""")],
        "grade": col("SELECT DISTINCT grade_code FROM src_tender_award ORDER BY grade_code",
                     "grade_code"),
        "vendor": col("SELECT ledger_name FROM src_tally_ledger "
                      "WHERE parent_group = 'Sundry Creditors' ORDER BY ledger_name",
                      "ledger_name"),
        "fy": ["FY23-24", "FY24-25", "FY25-26", "FY26-27"],
        "month": [{"value": m, "label": _month_label(m)} for m in _months_ahead(18)],
        "material": col("SELECT DISTINCT code FROM item WHERE kind = 'feedstock' "
                        "ORDER BY code", "code"),
        "int": [], "float": [], "vendor_opt": [],
    })


class Ask(BaseModel):
    tenant: str
    metric: str
    params: dict = {}


@app.post("/api/ask")
def api_ask(a: Ask):
    if a.metric not in metrics.REGISTRY:
        raise HTTPException(400, "no such metric")
    return clean(dict(answer.run(a.tenant, a.metric, a.params)))


@app.get("/api/definitions")
def api_definitions(tenant: str):
    d = definitions.load(tenant)
    # SCHEMA holds Python types (bool, int) and lists of allowed values. Turn those into
    # something JSON can carry, so the interface can render the right control for each.
    schema = {}
    for word, fields in definitions.SCHEMA.items():
        schema[word] = {}
        for key, (allowed, note) in fields.items():
            kind = ("choice" if isinstance(allowed, list)
                    else "bool" if allowed is bool
                    else "number")
            # Every non-numeric setting comes back as full sentences to choose between.
            # A controller signs off on "a payment clears the oldest bill first". She does
            # not sign off on fifo.
            opts = definitions.choices(word, key)
            if not opts and kind == "bool":
                opts = definitions.choices(word, key)
            schema[word][key] = {"kind": kind, "note": definitions.note(word, key) or note,
                                 "raw_choices": allowed if isinstance(allowed, list) else None,
                                 "options": opts}
    chosen = {}
    for word, cfg in d.items():
        chosen[word] = {}
        for key, val in cfg["params"].items():
            ph = definitions.phrasing(word, key, val)
            chosen[word][key] = {"value": val,
                                 "label": ph[0] if ph else None,
                                 "detail": ph[1] if ph else None}
    return clean({"current": d, "schema": schema, "chosen": chosen})


class SetDef(BaseModel):
    tenant: str
    word: str
    params: dict


@app.post("/api/definitions")
def api_set_definition(s: SetDef):
    """Changing a value closes the current row and opens a new one, so history survives and
    an answer given last month can still be re-derived under last month's rules."""
    try:
        definitions.set_definition(s.tenant, s.word, s.params, who="console")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


TABLES = ["src_tally_voucher", "src_tally_inventory_entry", "src_tally_ledger",
          "src_tally_stock_item", "src_dispatch_register", "src_production_register",
          "src_tender_award", "src_goods_receipt", "src_email",
          "item", "party", "party_link", "dispatch_tender", "definitions", "review_queue"]

TABLE_NOTE = {
    "src_tally_voucher": "Every accounting entry in one table. Dates are text. No quantities.",
    "src_tally_inventory_entry": "The quantity behind a voucher. Quintals, ten to a tonne.",
    "src_tally_ledger": "Party names as typed. GSTIN blank on about one in five.",
    "src_dispatch_register": "Every load that left. tender_ref blank where nobody wrote it down.",
    "src_production_register": "One row a month from the plant floor.",
    "src_tender_award": "The contracts. quoted_gcv turns a rate per tonne into a rate per GCV.",
    "src_goods_receipt": "What actually turned up at the gate.",
    "src_email": "Vendor commitments, as prose. The figures are in the sentence.",
    "item": "Product codes with their validity windows. The same code can mean two things.",
    "party": "Resolved parties.",
    "party_link": "How each ledger was matched. method is gstin, pan, exact_name or human.",
    "dispatch_tender": "Loads matched to contracts. method says whether a rule or a person decided.",
    "definitions": "What each word means, per tenant, versioned.",
    "review_queue": "Everything the system would not guess at.",
}


@app.get("/api/tables")
def api_tables(tenant: str):
    out = []
    for t in TABLES:
        try:
            n = db.fetch_one(tenant, f"SELECT count(*) AS n FROM {t}")["n"]
        except Exception:                                  # noqa: BLE001
            n = 0
        out.append({"name": t, "rows": n, "note": TABLE_NOTE.get(t, "")})
    return out


@app.get("/api/table/{name}")
def api_table(name: str, tenant: str, limit: int = 50):
    if name not in TABLES:                                 # allow-list, never interpolate freely
        raise HTTPException(404, "no such table")
    rows = db.fetch(tenant, f"SELECT * FROM {name} LIMIT {min(int(limit), 500)}")
    cols = list(rows[0].keys()) if rows else []
    return clean({"columns": cols, "rows": rows})


@app.get("/api/review")
def api_review(tenant: str):
    rows = db.fetch(tenant, """
        SELECT review_id, kind, subject_ref, proposal, status
        FROM review_queue WHERE status = 'open'
        ORDER BY kind, review_id LIMIT 200""")
    # Nobody reading this knows what T-24-24 is, so every option carries the buyer and the
    # size. The code stays alongside rather than instead, because two contracts with the
    # same buyer are told apart only by their reference.
    #
    # And it says whether the contract is still open. Placing a load on a contract whose
    # window has closed is often the right answer, but it cannot change what is still owed
    # on the live order book, so without this the reader answers a question, watches the
    # headline sit still, and reasonably concludes the product is broken.
    names = {}
    for r in db.fetch(tenant, """
            SELECT tender_ref, plant, tonnes, window_end,
                   (window_end >= current_date) AS live
            FROM src_tender_award"""):
        names[r["tender_ref"]] = "%s \u00b7 %s t (%s, %s)" % (
            r["plant"], format(float(r["tonnes"]), ",.0f"), r["tender_ref"],
            "still open" if r["live"] else "closed " + r["window_end"].strftime("%b %Y"))
    for r in rows:
        pr = r.get("proposal") or {}
        if pr.get("options"):
            pr["labels"] = {o: names.get(o, o) for o in pr["options"]}
            r["proposal"] = pr
    counts = db.fetch(tenant, """
        SELECT kind, count(*) AS n FROM review_queue WHERE status = 'open' GROUP BY 1""")
    return clean({"items": rows, "counts": {c["kind"]: c["n"] for c in counts}})


class Resolve(BaseModel):
    tenant: str
    review_id: int
    choice: str


@app.post("/api/review/resolve")
def api_resolve(r: Resolve):
    """A person answering one question the system would not guess at.

    The decision is stored against the source system's own key, so the next import replays
    it instead of asking again."""
    item = db.fetch_one(r.tenant, """
        SELECT review_id, kind, subject_ref, proposal FROM review_queue
        WHERE review_id = %(id)s AND status = 'open'""", {"id": r.review_id})
    if not item:
        raise HTTPException(404, "not in the queue")

    with db.tenant_cursor(r.tenant) as cur:
        if item["kind"] == "dispatch_tender":
            cur.execute("""INSERT INTO dispatch_tender
                             (tenant_id, dispatch_id, tender_ref, method, decided_by)
                           VALUES (%s,%s,%s,'human','console')
                           ON CONFLICT (tenant_id, dispatch_id)
                           DO UPDATE SET tender_ref = EXCLUDED.tender_ref,
                                         method = 'human', decided_by = 'console'""",
                        (r.tenant, item["subject_ref"], r.choice))
        elif item["kind"] == "purchase_channel":
            # The person names the material. The channel follows from it, because a
            # bought-in pellet is the only material that is not feedstock, and the material
            # is what the cost per kilocalorie actually needs.
            channel = "finished" if "pellet" in r.choice.lower() else "feedstock"
            cur.execute("""UPDATE purchase
                              SET channel = %s, channel_method = 'human', material = %s
                            WHERE src_guid = %s""",
                        (channel, r.choice, item["subject_ref"]))
            cur.execute("""UPDATE src_tally_inventory_entry SET stock_item_name = %s
                            WHERE voucher_guid = %s AND stock_item_name = 'Biomass Material'""",
                        (r.choice, item["subject_ref"]))
        elif item["kind"] == "party_match":
            # The ledger is confirmed as a party somebody named. method 'human' is the point:
            # six months on you can see this link rests on a person's judgement, not a rule.
            cur.execute("""INSERT INTO party (tenant_id, name, gstin, kind)
                           VALUES (%s,%s,NULL,%s) RETURNING party_id""",
                        (r.tenant, r.choice, (item["proposal"] or {}).get("kind", "vendor")))
            pid = cur.fetchone()["party_id"]
            cur.execute("""INSERT INTO party_link
                             (tenant_id, system, source_key, party_id, method, decided_by)
                           VALUES (%s,'tally',%s,%s,'human','console')
                           ON CONFLICT DO NOTHING""",
                        (r.tenant, item["subject_ref"], pid))
        cur.execute("""UPDATE review_queue SET status = 'resolved', resolved_by = 'console',
                              resolved_at = now() WHERE review_id = %s""", (r.review_id,))
    return {"ok": True}


@app.get("/api/summary")
def api_summary(tenant: str):
    """What the console shows at rest: how much is known, and how much is waiting on a person."""
    q = db.fetch_one(tenant, """
        SELECT count(*) FILTER (WHERE status = 'open') AS open,
               count(*) FILTER (WHERE status = 'resolved') AS done
        FROM review_queue""")
    d = db.fetch_one(tenant, """
        SELECT count(*) AS loads,
               count(*) FILTER (WHERE tender_ref IS NULL) AS untagged,
               coalesce(sum(qty_net_t), 0) AS tonnes
        FROM src_dispatch_register""")
    c = db.fetch_one(tenant, "SELECT count(*) AS n FROM src_tender_award")
    live = db.fetch_one(tenant, "SELECT count(*) AS n FROM src_tender_award "
                                "WHERE window_end >= date '2026-09-01'")
    return clean({"open_reviews": q["open"], "resolved_reviews": q["done"],
                  "loads": d["loads"], "untagged": d["untagged"], "tonnes": float(d["tonnes"]),
                  "contracts": c["n"], "live_contracts": live["n"]})


@app.get("/api/story")
def api_story(tenant: str):
    """The numbers behind the landing page.

    Every figure in the story comes from here, so the narrative cannot drift away from the
    data. If somebody clears the review queue, the story changes with it."""
    live = db.fetch(tenant, """
        SELECT t.tender_ref, t.plant, t.tonnes, t.window_start, t.window_end,
               t.rate_per_t, t.quoted_gcv,
               coalesce(sum(d.qty_net_t), 0) AS delivered
        FROM src_tender_award t
        LEFT JOIN src_dispatch_register d ON d.tender_ref = t.tender_ref
        WHERE t.window_end >= date '2026-09-01'
        GROUP BY t.tender_ref, t.plant, t.tonnes, t.window_start, t.window_end,
                 t.rate_per_t, t.quoted_gcv
        ORDER BY t.window_start""")

    # The tender on his desk: the most recently awarded one, and the one furthest from
    # being delivered. Prefer one with nothing shipped yet, but fall back to the newest,
    # because in a seed where every contract has history there is no untouched one.
    new = db.fetch_one(tenant, """
        SELECT t.tender_ref, t.plant, t.tonnes, t.window_start, t.window_end,
               t.rate_per_t, t.quoted_gcv,
               coalesce(sum(d.qty_net_t), 0) AS delivered
        FROM src_tender_award t
        LEFT JOIN src_dispatch_register d ON d.tender_ref = t.tender_ref
        WHERE t.window_end >= date '2026-09-01'
        GROUP BY t.tender_ref, t.plant, t.tonnes, t.window_start, t.window_end,
                 t.rate_per_t, t.quoted_gcv
        ORDER BY (coalesce(sum(d.qty_net_t), 0) / nullif(t.tonnes, 0)) ASC,
                 t.window_start DESC, t.tonnes DESC
        LIMIT 1""")

    blocked = db.fetch_one(tenant, """
        SELECT count(*) AS loads, coalesce(sum(d.qty_net_t), 0) AS tonnes
        FROM src_dispatch_register d
        LEFT JOIN dispatch_tender dt ON dt.dispatch_id = d.dispatch_no
        WHERE d.tender_ref IS NULL AND dt.tender_ref IS NULL""")

    unclassified = db.fetch_one(tenant, """
        SELECT count(*) AS n FROM review_queue
        WHERE kind = 'purchase_channel' AND status = 'open'""")

    emails = db.fetch_one(tenant, "SELECT count(*) AS n FROM src_email")
    vouchers = db.fetch_one(tenant, "SELECT count(*) AS n FROM src_tally_voucher")
    ledgers = db.fetch_one(tenant, """
        SELECT count(*) AS n, count(*) FILTER (WHERE gstin IS NULL) AS no_gstin
        FROM src_tally_ledger""")

    # what the plant has typically managed each month, against what is already promised
    typical = {r["m"]: float(r["t"]) for r in db.fetch(tenant, """
        SELECT right(month, 2) AS m, avg(actual_qty_t) AS t
        FROM src_production_register GROUP BY 1""")}
    ahead = db.fetch(tenant, """
        SELECT to_char(gs, 'YYYY-MM') AS month, to_char(gs, 'MM') AS mm,
               coalesce(sum(t.tonnes / greatest(1,
                   (extract(year from age(t.window_end, t.window_start)) * 12
                    + extract(month from age(t.window_end, t.window_start)) + 1))), 0) AS committed
        FROM generate_series(date '2026-09-01', date '2027-08-01', '1 month') gs
        LEFT JOIN src_tender_award t ON gs BETWEEN t.window_start AND t.window_end
        GROUP BY 1, 2 ORDER BY 1""")
    months = [{"month": r["month"], "committed_t": float(r["committed"]),
               "capacity_t": typical.get(r["mm"], 0),
               "spare_t": typical.get(r["mm"], 0) - float(r["committed"])} for r in ahead]

    return clean({
        "tenant": tenant,
        "live_contracts": len(live),
        "committed_t": sum(float(r["tonnes"]) - float(r["delivered"]) for r in live),
        "contracts": [dict(r) for r in live[:40]],
        "new_tender": dict(new) if new else None,
        "blocked_loads": blocked["loads"], "blocked_t": float(blocked["tonnes"]),
        "unclassified": unclassified["n"],
        "emails": emails["n"], "vouchers": vouchers["n"],
        "ledgers": ledgers["n"], "ledgers_no_gstin": ledgers["no_gstin"],
        "months": months,
    })
