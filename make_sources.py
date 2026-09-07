"""
Step 3: break the truth into the mess the company actually has.

    truth/*.csv     what really happened          (clean, complete, never queried by the product)
    sources/*.csv   what the company actually has (what the product reads)

The product must be able to rebuild the truth from the sources, EXCEPT where we deliberately
destroyed something. Those gaps are precisely what it has to refuse on.

What gets destroyed, and why each one is realistic:

    the channel column          deleted on the ambiguous purchases. Tally has no such field;
                                husk and bought-in pellets are both just "Purchase"
    the tender reference        blanked on a share of dispatch rows. The loader knows which
                                contract it was for. The register does not always say
    dates                       become text, "15-Apr-2024", which is how Tally stores them
    quantities                  become quintals, because that is the trade unit
    party identity              becomes a typed ledger name. GSTIN is often blank
    vendor commitments          stop being a table and become email threads
    a few rows                  exist in one place and never made it to the other

Run:  python make_sources.py [a|b]
"""

import csv, os, random, sys
from datetime import date, timedelta

TENANT = (sys.argv[1] if len(sys.argv) > 1 else "a").lower()
IN_SEED = "seed_inputs" if TENANT == "a" else f"seed_inputs_{TENANT}"
IN_TRUTH = "truth" if TENANT == "a" else f"truth_{TENANT}"
OUT = "sources" if TENANT == "a" else f"sources_{TENANT}"
rng = random.Random(4242 if TENANT == "a" else 9191)
os.makedirs(OUT, exist_ok=True)

TODAY = date(2026, 9, 1)

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load(folder, name):
    with open(f"{folder}/{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def w(name, rows):
    if not rows:
        return
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(f"{OUT}/{name}.csv", "w", newline="", encoding="utf-8") as f:
        cw = csv.DictWriter(f, fieldnames=cols, restval="")
        cw.writeheader()
        cw.writerows(rows)


def tally_date(iso):
    """2024-04-15 becomes 15-Apr-2024, which is how Tally actually stores it."""
    y, m, d = iso.split("-")
    return f"{int(d):02d}-{MON[int(m) - 1]}-{y}"


def qtl(tonnes):
    """The trade works in quintals. One tonne is ten quintals."""
    return round(float(tonnes) * 10, 1)


vendors = load(IN_SEED, "vendors")
buyers = {b["buyer_id"]: b for b in load(IN_SEED, "buyers")}
plants = {p["plant_id"]: p for p in load(IN_SEED, "plants")}
contracts = load(IN_SEED, "contracts")
purchases = load(IN_TRUTH, "purchase")
dispatches = load(IN_TRUTH, "dispatch")
invoices = load(IN_TRUTH, "invoice")
payments = load(IN_TRUTH, "payment")
recoveries = {r["invoice_id"]: r for r in load(IN_TRUTH, "recovery")}
commitments = load(IN_TRUTH, "commitment")
production = load(IN_TRUTH, "production")
advances = load(IN_TRUTH, "advance")
V = {v["vendor_id"]: v for v in vendors}

# ============================================================ 1. Tally: the party master
# Free text names. GSTIN missing on about a fifth of them, which is where the canonical
# layer has to fall back from a hard key to a proposal a human confirms.
ledgers = []
for v in vendors:
    ledgers.append(dict(ledger_name=v["name"], parent_group="Sundry Creditors",
                        gstin="" if rng.random() < 0.2 else v["gstin"], opening_balance=0))
for p in plants.values():
    ledgers.append(dict(ledger_name=p["name"], parent_group="Sundry Debtors",
                        gstin="", opening_balance=0))
w("tally_ledger", ledgers)

# Item master. Deliberately vague: a generic raw-material group that gives no clue whether
# a purchase was feedstock or a finished pellet someone bought in.
#
# The names come from this tenant's own material list. Marudhar buys rice husk and mustard
# stalk in Rajasthan; Saurashtra buys cotton stalk and groundnut shell in Gujarat. Hard
# coding one company's crops into the other's ledger is the kind of quiet wrong that makes
# every downstream answer about cost per kilocalorie meaningless.
materials = load(IN_SEED, "materials")
ITEM_NAME = {}
for m in materials:
    if m["material"] in ("contaminated", "bought-in pellets"):
        continue
    ITEM_NAME.setdefault(m["buys_as"], m["material"].title())

w("tally_stock_item",
  [dict(item_name=nm, parent_group="Raw Material") for nm in ITEM_NAME.values()] +
  [dict(item_name="Biomass Material", parent_group="Raw Material"),   # the useless one
   dict(item_name="Pellets", parent_group="Finished Goods")])

# ============================================================ 2. Tally: vouchers
vouchers, inv_entries = [], []
gid = 0


def voucher(vtype, dt, ledger, amount, dr_cr, narration, entered=None):
    global gid
    gid += 1
    vouchers.append(dict(guid=f"{TENANT.upper()}V{gid:05d}", voucher_type=vtype,
                         vch_no=gid, vch_date=tally_date(dt), ledger_name=ledger,
                         amount=round(float(amount), 2), dr_cr=dr_cr, narration=narration,
                         entered_at=tally_date(entered or dt)))
    return f"{TENANT.upper()}V{gid:05d}"


# ---- purchases. The channel column simply does not exist in Tally.
for p in purchases:
    amb = str(p.get("ambiguous", "")).lower() in ("true", "1")
    if amb:
        item = "Biomass Material"          # nothing here says which it was
        narr = rng.choice(["material recd", "biomass purchase", "as per bill",
                           "supply against order"])
    elif p["channel"] == "finished":
        item = "Pellets"
        narr = "pellets purchase"
    else:
        item = ITEM_NAME.get(p["item"], "Biomass Material")
        narr = f"{p['item']} purchase"
    g = voucher("Purchase", p["txn_date"], V[p["vendor_id"]]["name"],
                float(p["qty_t"]) * float(p["rate"]), "Dr", narr, p["entered_at"])
    inv_entries.append(dict(guid=g + "-1", voucher_guid=g, stock_item_name=item,
                            qty_qtl=qtl(p["qty_t"]), rate=p["rate"]))

# ---- sales, credit notes, receipts
for inv in invoices:
    pl = plants[inv["plant"]]["name"]
    voucher("Sales", inv["invoice_date"], pl, inv["amount"], "Cr",
            f"supply against {inv['tender_ref']}")
    rec = recoveries.get(inv["id"])
    if rec and float(rec["amount"]) > 1:
        voucher("Credit Note", inv["crac_date"], pl, rec["amount"], "Dr",
                f"GCV shortfall {rec['gcv']} vs {rec['quoted_gcv']}")
for pm in payments:
    inv = next((i for i in invoices if i["id"] == pm["invoice_id"]), None)
    if inv:
        voucher("Receipt", pm["paid_date"], plants[inv["plant"]]["name"], pm["amount"], "Cr",
                "against bill")
for a in advances:
    nm = V[a["party"]]["name"] if a["party"] in V else \
        next((p["name"] for p in plants.values() if p["buyer_id"] == a["party"]), a["party"])
    voucher("Payment" if a["direction"] == "paid" else "Receipt", a["adv_date"], nm,
            a["amount"], "Dr" if a["direction"] == "paid" else "Cr", "advance")

# a couple of credit notes with nothing behind them
for i in range(2):
    voucher("Credit Note", "2025-1{}-14".format(i + 1), list(plants.values())[i]["name"],
            rng.randint(180000, 420000), "Dr", "adjustment")

w("tally_voucher", vouchers)
w("tally_inventory_entry", inv_entries)

# ============================================================ 3. dispatch register
# Gross and net weight. Only net is the delivered tonnage. The contract reference is
# missing on a share of rows: recoverable by asking the yard, not ambiguous.
dmg = {r["code"]: r for r in load(IN_SEED, "damage")}
blank_n = int(float(dmg["D8"]["size"]))
blank = set(rng.sample([x["id"] for x in dispatches], min(blank_n, len(dispatches))))

# A delivery that ran past the closing date. NTPC grants an extension, the loads go out in
# April against a contract that ended on 31 March, and nobody notes which one it belonged
# to. Now the date alone cannot place it, because no window is open on that day. This is
# the only genuinely ambiguous dispatch in the book, and it is ambiguous for a real reason.
CWIN = {c["tender_ref"]: (c["window_start"], c["window_end"]) for c in contracts}
late_n = int(float(dmg.get("D11", {"size": 0})["size"]))
# only contracts that have already closed, and only the last load on each, so the extension
# reads the way it would in the register: one straggler after the window shut
closed = sorted({r for r in CWIN if CWIN[r][1] < TODAY.isoformat()},
                key=lambda r: CWIN[r][1], reverse=True)
last_of = {}
for x in dispatches:
    r = x["tender_ref"]
    if r in CWIN and (r not in last_of or x["dispatch_date"] > last_of[r]["dispatch_date"]):
        last_of[r] = x
late_ids = {}
for r in closed[:late_n]:
    x = last_of.get(r)
    if x:
        late_ids[x["id"]] = (date.fromisoformat(CWIN[r][1])
                             + timedelta(days=rng.randint(4, 15))).isoformat()
blank |= set(late_ids)
uninvoiced = set(rng.sample([x["id"] for x in dispatches[-200:]],
                            int(float(dmg["D5"]["size"]))))

reg = []
for x in dispatches:
    net = float(x["qty_t"])
    reg.append(dict(dispatch_no=x["id"].replace("D", "DR"),
                    dispatch_date=late_ids.get(x["id"], x["dispatch_date"]),
                    vehicle_no=f"{'RJ' if TENANT == 'a' else 'GJ'}"
                               f"{rng.randint(1, 27):02d}GA{rng.randint(1000, 9999)}",
                    grade_code=x["grade_code"],
                    destination=plants[x["plant"]]["name"].upper(),
                    tender_ref="" if x["id"] in blank else x["tender_ref"],
                    qty_gross_t=round(net * rng.uniform(1.02, 1.04), 2),
                    qty_net_t=net,
                    invoice_no="" if x["id"] in uninvoiced else x["id"].replace("D", "INV")))
w("dispatch_register", reg)

# ============================================================ 4. production register
w("production_register", [dict(month=r["month"], grade_code="",
                               opening_stock_t=r["opening_stock_t"],
                               planned_qty_t=round(float(r["produced_t"]) * rng.uniform(.95, 1.06), 1),
                               actual_qty_t=r["produced_t"],
                               feedstock_consumed_t=r["feedstock_used_t"])
                          for r in production])

# ============================================================ 5. the tender folder
# Two kinds of contract live in this folder and they are not the same promise.
#
# A government tender is a cumulative quantity against a deadline. NTPC does not ask for
# 800 t in March. It asks for 8,000 t by the end of the window and leaves the scheduling to
# the supplier. So there is no monthly obligation to record, and inventing one by dividing
# the total by the number of months would put a promise on the books that nobody made.
#
# A private buyer is the opposite. Jaipur Bottling contracts a fixed monthly draw, and that
# schedule is written into the contract. It is a real monthly obligation and it is the only
# thing that can genuinely make a month oversold.
def kind_of(c):
    return "scheduled" if buyers[plants[c["plant_id"]]["buyer_id"]]["kind"] == "private"            else "cumulative"


w("tender_award", [dict(tender_ref=c["tender_ref"], plant=plants[c["plant_id"]]["name"],
                        grade_code=c["grade_code"], tonnes=c["tonnes"],
                        window_start=c["window_start"], window_end=c["window_end"],
                        rate_per_t=c["rate_per_t"], freight_per_t=c["freight_per_t"],
                        quoted_gcv=plants[c["plant_id"]]["quoted_gcv"],
                        option_pct=c["option_pct"], contract_type=kind_of(c),
                        loa_no=f"LOA/{c['tender_ref']}") for c in contracts])

sched = []
for c in contracts:
    if kind_of(c) != "scheduled":
        continue
    y0, m0 = int(c["window_start"][:4]), int(c["window_start"][5:7])
    y1, m1 = int(c["window_end"][:4]), int(c["window_end"][5:7])
    n = max(1, (y1 - y0) * 12 + (m1 - m0) + 1)
    per = float(c["tonnes"]) / n
    left = float(c["tonnes"])
    for i in range(n):
        y, m = divmod((m0 - 1) + i, 12)
        # a real contract rounds to a load size and puts the remainder in the last month
        q = round(per / 25) * 25 if i < n - 1 else round(left, 1)
        q = min(q, left)
        left = round(left - q, 1)
        sched.append(dict(tender_ref=c["tender_ref"], month=f"{y0 + y}-{m + 1:02d}", qty_t=q))
w("contract_schedule", sched)

# The plant's own working figures, carried through rather than hard coded downstream.
w("config", [dict(key=c["key"], value=c["value"], note=c.get("note", ""))
             for c in load(IN_SEED, "config")])

# Payment terms, keyed by the name that appears on the sales voucher, because that is the
# only handle the books give you.
w("buyer_terms", [dict(ledger_name=pl["name"], buyer=buyers[pl["buyer_id"]]["name"],
                       kind=buyers[pl["buyer_id"]]["kind"],
                       pay_days=buyers[pl["buyer_id"]].get("pay_days", 30))
                  for pl in plants.values()])

# ============================================================ 6. the email threads
# This is the important one. Vendor commitments are agreed in mail and recorded nowhere
# else, so here they stop being a table and become prose somebody has to read.
ASK = ["Please confirm availability of {q} MT {mat} for delivery by {dt}.",
       "We need {q} MT of {mat}. Can you commit by {dt}?",
       "Requirement {q} MT {mat}, delivery on or before {dt}. Kindly confirm rate."]
REPLY = ["Confirmed. We can supply {q} MT {mat} at Rs {r} per MT, delivery by {dt}.",
         "Yes sir, {q} MT available. Rate Rs {r}/MT. Will dispatch before {dt}.",
         "Accepted. {q} MT {mat} @ Rs {r} PMT. Delivery {dt} positive.",
         "Ok for {q} MT at Rs {r} per tonne. Loading will start before {dt}."]

emails, eid = [], 0
for c in commitments:
    v = V[c["vendor_id"]]
    mat = "rice husk" if v["supplies"] != "stalk" else "mustard stalk"
    tid = f"TH{int(c['id'][1:]):05d}"
    eid += 1
    emails.append(dict(msg_id=f"M{eid:05d}", thread_id=tid, sent_at=c["promised_date"],
                       from_addr="purchase@marudharbiofuels.in" if TENANT == "a"
                                 else "buying@saurashtragreen.in",
                       to_addr=f"{v['name'].split()[0].lower()}@example.in",
                       subject=f"Requirement {mat} {c['month']}",
                       body=rng.choice(ASK).format(q=c["qty_t"], mat=mat,
                                                   dt=tally_date(c["promised_date"]))))
    eid += 1
    emails.append(dict(msg_id=f"M{eid:05d}", thread_id=tid, sent_at=c["promised_date"],
                       from_addr=f"{v['name'].split()[0].lower()}@example.in",
                       to_addr="purchase@marudharbiofuels.in" if TENANT == "a"
                               else "buying@saurashtragreen.in",
                       subject=f"RE: Requirement {mat} {c['month']}",
                       body=rng.choice(REPLY).format(q=c["qty_t"], mat=mat,
                                                     r=c["rate_agreed"],
                                                     dt=tally_date(c["promised_date"]))))
w("emails", emails)

# ============================================================ 7. goods receipts
# What actually arrived. Comparing this against the emails is the whole of vendor reliability,
# and nobody has ever done it because one side is prose.
w("goods_receipt", [dict(grn_no=f"GRN{int(c['id'][1:]):05d}",
                         received_date=c["delivered_date"],
                         vendor_name=V[c["vendor_id"]]["name"],
                         qty_qtl=qtl(c["delivered_t"]),
                         rate=c["rate_agreed"]) for c in commitments])

print(f"sources for tenant {TENANT.upper()} written to {OUT}/")
print(f"  tally_voucher {len(vouchers)}   inventory entries {len(inv_entries)}")
print(f"  dispatch_register {len(reg)}   of which {len(blank)} have no contract reference, {len(late_ids)} of those delivered after the window closed")
print(f"  emails {len(emails)} across {len(commitments)} threads")
print(f"  goods_receipt {len(commitments)}   tender_award {len(contracts)}   contract_schedule {len(sched)}")
print(f"  purchases where nothing says husk or bought-in pellets: "
      f"{sum(1 for p in purchases if str(p.get('ambiguous','')).lower() in ('true','1'))}")
