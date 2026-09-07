"""
Builds the truth, then computes the correct answer to all 20 questions from it.

    seed_inputs/*.csv   what the company IS      (hand-edited, see make_seed_inputs.py)
    truth/*.csv         what HAPPENED to it      (generated here)
    questions.md        the correct answers      (generated here)

Nothing in this file is product code. The product never reads truth/. This exists only so we
know what the right answers are before the engine is written. If you build the engine first,
you end up checking it against itself.

Order of work, and why it runs this way:
    1. read the company description from seed_inputs/
    2. spread each contract across the months it is live       -> the delivery plan
    3. turn that plan into dispatches                          -> what left the yard
    4. price each dispatch on DELIVERED GCV, not quoted        -> the invoice
    5. settle invoices: PSUs in 30 days, private buyers slowly -> payments
    6. work backwards to production, then to purchases         -> so the tonnage balances
    7. invent the vendor commitments that live in email        -> what was promised
    8. break specific rows on purpose                          -> the damage
    9. write everything out, then compute the answer key

Run:  python make_seed_inputs.py   (once)
      python truth_gen.py
"""

import csv, io, os, random, sys
from datetime import date, timedelta

TENANT = (sys.argv[1] if len(sys.argv) > 1 else "a").lower()

SEED = 20260904
rng = random.Random(SEED)
IN = "seed_inputs" if TENANT == "a" else f"seed_inputs_{TENANT}"
OUT = "truth" if TENANT == "a" else f"truth_{TENANT}"
TODAY = date(2026, 9, 1)                 # matches the live tender document


# ============================================================== helpers
def load(name):
    with open(f"{IN}/{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def d(s):
    return date(*map(int, s.split("-")))


def fy(y, m):
    """Indian financial year label. April to March."""
    return f"FY{y % 100:02d}-{(y + 1) % 100:02d}" if m >= 4 else f"FY{(y - 1) % 100:02d}-{y % 100:02d}"


def mkey(y, m):
    return f"{y}-{m:02d}"


# ============================================================== 1. the company
vendors = load("vendors")
buyers = {b["buyer_id"]: b for b in load("buyers")}
plants = {p["plant_id"]: p for p in load("plants")}
grades = load("grades")
FEED_KCAL = {}
for _m in load("materials"):          # GCV now lives in one place only
    FEED_KCAL.setdefault(_m["buys_as"], []).append(float(_m["gcv_typical"]))
FEED_KCAL = {k: sum(v) / len(v) for k, v in FEED_KCAL.items()}
# GCV of what we make, by grade code. A tonne of 3600 GCV pellets carries 3600 "GCV points",
# and NTPC pays rate_per_GCV x delivered GCV. So cost has to be expressed the same way.
GRADE_KCAL = {}
for g in sorted(load("grades"), key=lambda r: r["valid_from"]):
    GRADE_KCAL[g["code"]] = float(g["kcal"])      # latest definition wins
contracts = load("contracts")
CFG = {r["key"]: float(r["value"]) for r in load("config")}
SEASON = {int(r["month"]): float(r["index"]) for r in load("price_curve")}
BASE = {r["financial_year"]: float(r["april_husk_rate"]) for r in load("price_base")}

MONTHS = [(2023 + (3 + i) // 12, (3 + i) % 12 + 1) for i in range(41)]   # Apr 23 .. Aug 26
V = {v["vendor_id"]: v for v in vendors}
HUSK_V = [v["vendor_id"] for v in vendors if v["supplies"] in ("husk", "both")]
STALK_V = [v["vendor_id"] for v in vendors if v["supplies"] in ("stalk", "both")]
FIN_V = [v["vendor_id"] for v in vendors if v["supplies"] in ("finished", "both")]


def feed_rate(y, m, kind):
    """Seasonal feedstock rate. April cheapest, October dearest, plus a little noise."""
    r = BASE[fy(y, m)] * SEASON[m]
    if kind == "stalk":
        r *= CFG["stalk_discount"]
    return round(r * rng.uniform(0.97, 1.03))


def finished_rate(y, m):
    """Bought-in finished pellets. Always far above feedstock, which is what lets a rate band
    separate the two channels. The damaged rows sit deliberately in the gap between them."""
    drift = BASE[fy(y, m)] - BASE["FY23-24"]
    return round((CFG["finished_pellet_base"] + drift * 0.9)
                 * (1 + (SEASON[m] - 1) * 0.35) * rng.uniform(0.98, 1.02))


# ============================================================== 2. delivery plan
# Each contract spreads evenly across the months it is live. In reality the owner chooses
# this split himself, which is why delivery_plan is the one table the product writes to.
plan = {}
for c in contracts:
    ws, we = d(c["window_start"]), d(c["window_end"])
    live = [(y, m) for (y, m) in MONTHS if ws <= date(y, m, 15) <= we]
    if not live:
        continue
    total_months = max(1, (we.year - ws.year) * 12 + (we.month - ws.month) + 1)
    per = float(c["tonnes"]) / total_months
    for (y, m) in live:
        plan[(c["tender_ref"], mkey(y, m))] = per


# ============================================================== 3, 4. dispatches and invoices
dispatches, invoices, recoveries, payments = [], [], [], []
did = iid = 0
out_by_contract = {}

for (y, m) in MONTHS:
    for c in contracts:
        want = plan.get((c["tender_ref"], mkey(y, m)), 0)
        if want <= 0:
            continue
        pl = plants[c["plant_id"]]
        n = max(1, round(want / rng.uniform(CFG["consignment_min_t"], CFG["consignment_max_t"])))
        left = want
        for k in range(n):
            qty = round(left / (n - k) * rng.uniform(0.9, 1.1), 1) if k < n - 1 else round(left, 1)
            qty = max(20.0, qty)
            left = round(left - qty, 1)
            did += 1
            dd = date(y, m, rng.randint(2, 27))
            dispatches.append(dict(id=f"D{did:05d}", tender_ref=c["tender_ref"],
                                   plant=c["plant_id"], grade_code=c["grade_code"],
                                   dispatch_date=dd, qty_t=qty))
            out_by_contract[c["tender_ref"]] = out_by_contract.get(c["tender_ref"], 0) + qty

            # ---- the invoice. Paid on DELIVERED GCV, not on what was quoted.
            #      quote 3200 GCV at Rs 6400 -> Rs 2.00 per kcal.
            #      deliver 3400 -> Rs 6800.   deliver 2900 -> Rs 5800.
            #      below 2800 -> a further 25 percent off.  below 2000 -> rejected.
            iid += 1
            inv_d = dd + timedelta(days=rng.randint(1, 6))
            crac_d = inv_d + timedelta(days=rng.randint(6, 22))     # acceptance certificate
            accepted = round(qty * rng.choice([1.0, 1.0, 1.0, 0.995, 0.99]), 2)
            quoted_gcv = float(pl["quoted_gcv"])
            per_kcal = float(c["rate_per_t"]) / quoted_gcv
            quoted_amt = round(accepted * float(c["rate_per_t"]), 2)
            gcv = round(rng.gauss(quoted_gcv + 60, 240))            # what actually turned up
            if gcv < CFG["gcv_reject"]:
                got = 0.0
            elif gcv < CFG["gcv_floor_full"]:
                got = gcv * per_kcal * (1 - CFG["gcv_penalty"])
            else:
                got = gcv * per_kcal
            amount = round(accepted * got, 2)
            gap = round(quoted_amt - amount, 2)      # positive means we lost on GCV
            if gap > 1:            # only a shortfall raises a credit note
                recoveries.append(dict(invoice_id=f"I{iid:05d}", amount=gap, gcv=gcv,
                                       quoted_gcv=int(quoted_gcv),
                                       reason=("rejected below 2000" if gcv < CFG["gcv_reject"]
                                               else "below 2800, 25 percent off" if gcv < CFG["gcv_floor_full"]
                                               else "GCV under quote")))
            invoices.append(dict(id=f"I{iid:05d}", dispatch_id=f"D{did:05d}",
                                 tender_ref=c["tender_ref"], plant=c["plant_id"],
                                 invoice_date=inv_d, crac_date=crac_d,
                                 qty_accepted_t=accepted, quoted_amount=quoted_amt,
                                 amount=amount, recovery=max(0.0, gap), uplift=max(0.0, -gap),
                                 gcv=gcv))


# ============================================================== 5. payments
# PSUs settle inside 30 days of the acceptance certificate, as the contract requires.
# Private buyers run 48 to 115 days, pay in parts, and about a fifth are still open. So
# "who owes us money" is really a question about the small private buyers, not about NTPC.
for inv in invoices:
    due = inv["amount"]
    if due <= 1:
        continue                                   # rejected load, nothing to collect
    is_psu = buyers[plants[inv["plant"]]["buyer_id"]]["kind"] == "psu"
    if is_psu:
        pay_on = inv["crac_date"] + timedelta(days=rng.randint(11, int(CFG["psu_payment_days"]) - 1))
        if pay_on <= date(2026, 8, 31):
            payments.append(dict(invoice_id=inv["id"], paid_date=pay_on, amount=round(due, 2)))
        continue
    if inv["invoice_date"] > date(2026, 6, 20) or rng.random() < CFG["private_unpaid_share"]:
        continue                                   # still running, or disputed and never settled
    parts = rng.choice([2, 3]) if rng.random() < CFG["private_part_pay_share"] else 1
    got = 0.0
    for k in range(parts):
        amt = round(due - got, 2) if k == parts - 1 else round(due / parts * rng.uniform(.8, 1.2), 2)
        got += amt
        lag = rng.randint(int(CFG["private_payment_days_min"]), int(CFG["private_payment_days_max"]))
        payments.append(dict(invoice_id=inv["id"],
                             paid_date=inv["invoice_date"] + timedelta(days=lag + k * 34),
                             amount=amt))


# ============================================================== 6. production, then purchases
# Worked backwards from what went out, so the tonnage balances everywhere except the two
# months broken on purpose. That balance is the control total the product checks against.
demand = {}
for x in dispatches:
    k = mkey(x["dispatch_date"].year, x["dispatch_date"].month)
    demand[k] = demand.get(k, 0) + x["qty_t"]

production, stock = [], round(min(demand.values()) * 0.30, 1)
for (y, m) in MONTHS:
    k = mkey(y, m)
    need = demand.get(k, 0)
    cap_factor = 0.88 if m in (7, 8, 9) else 1.0        # monsoon slows drying
    made = round(max(0.0, (need - stock + rng.uniform(40, 220)) * cap_factor), 1)
    short = round(max(0.0, need - stock - made), 1)
    bought = round(short + rng.uniform(20, 90), 1) if short > 0 else 0.0
    production.append(dict(month=k, opening_stock_t=round(stock, 1), produced_t=made,
                           feedstock_used_t=round(made * CFG["feed_per_pellet"], 1),
                           bought_finished_t=bought))
    stock = round(stock + made + bought - need, 1)

purchases, pid = [], 0
for row in production:
    y, m = int(row["month"][:4]), int(row["month"][5:])
    need = round(row["feedstock_used_t"] * CFG["wastage"], 1)
    for kind, qty, poolv in (("husk", need * 0.72, HUSK_V), ("stalk", need * 0.28, STALK_V)):
        n = max(1, round(qty / rng.uniform(180, 380)))
        left = qty
        for k in range(n):
            q = round(left / (n - k) * rng.uniform(0.85, 1.15), 1) if k < n - 1 else round(left, 1)
            q = max(25.0, q)
            left = round(left - q, 1)
            pid += 1
            td = date(y, m, rng.randint(2, 27))
            purchases.append(dict(id=f"P{pid:05d}", vendor_id=rng.choice(poolv), item=kind,
                                  channel="feedstock", qty_t=q, rate=feed_rate(y, m, kind),
                                  txn_date=td, entered_at=td))
    if row["bought_finished_t"] > 0:                    # bought-in finished pellets
        left = row["bought_finished_t"]
        n = rng.randint(1, 2)
        for k in range(n):
            q = round(left / (n - k), 1) if k < n - 1 else round(left, 1)
            left = round(left - q, 1)
            pid += 1
            td = date(y, m, rng.randint(2, 27))
            purchases.append(dict(id=f"P{pid:05d}", vendor_id=rng.choice(FIN_V), item="pellets",
                                  channel="finished", qty_t=q, rate=finished_rate(y, m),
                                  txn_date=td, entered_at=td))


# ============================================================== 7. vendor commitments
# These only ever existed in email. Quantity, rate and date agreed in a thread, nothing
# structured recording it. Behaviour shows up ONLY through the delivery history, never as a
# label the product can see:
#   diverter  short-delivers when the spot rate runs 8 percent above what he agreed
#   late      delivers in full, two to four weeks late
#   erratic   occasional small shortfall, no pattern
#   thin      only two commitments ever, so no rate can honestly be quoted
commitments, cid = [], 0
eligible = [v for v in vendors if v["behaviour"] != "thin" and v["supplies"] != "finished"]
for row in production:
    y, m = int(row["month"][:4]), int(row["month"][5:])
    for _ in range(rng.randint(15, 22)):
        v = rng.choice(eligible)
        cid += 1
        qty = round(rng.uniform(120, 420), 1)
        kind = "stalk" if v["supplies"] == "stalk" else "husk"
        agreed = feed_rate(y, m, kind)
        market = round(agreed * rng.uniform(0.94, 1.26))       # what everyone else was paying
        prom = date(y, m, rng.randint(10, 28))
        deliv, ddate = qty, prom
        if v["behaviour"] == "diverter" and market > agreed * 1.08:
            deliv = round(qty * rng.uniform(0.45, 0.8), 1)     # sold it to a better payer
        elif v["behaviour"] == "erratic" and rng.random() < 0.25:
            deliv = round(qty * rng.uniform(0.85, 0.97), 1)
        elif v["behaviour"] == "late":
            ddate = prom + timedelta(days=rng.randint(14, 28))
        commitments.append(dict(id=f"C{cid:05d}", vendor_id=v["vendor_id"], month=row["month"],
                                qty_t=qty, rate_agreed=agreed, market_rate=market,
                                promised_date=prom, delivered_t=deliv, delivered_date=ddate))

# The "thin" vendor: exactly two commitments, both met. Too few to state a rate.
THIN_V = next((v["vendor_id"] for v in vendors if v["behaviour"] == "thin"), vendors[0]["vendor_id"])
for (y, m) in [(2024, 5), (2025, 11)]:
    cid += 1
    q, r = round(rng.uniform(140, 260), 1), feed_rate(y, m, "husk")
    commitments.append(dict(id=f"C{cid:05d}", vendor_id=THIN_V, month=mkey(y, m), qty_t=q,
                            rate_agreed=r, market_rate=r, promised_date=date(y, m, 20),
                            delivered_t=q, delivered_date=date(y, m, 20)))


# ============================================================== 8. the damage
# FY23-24 and FY24-25 are left completely clean, so some questions can answer confidently
# and the refusals read as precise rather than as blanket caution.
DAMAGE = {}

# D1  purchases that cannot be told apart. Small, and the rate lands between the two bands.
pool = ([p for p in purchases if mkey(p["txn_date"].year, p["txn_date"].month) == "2025-11"][:8]
        + [p for p in purchases if mkey(p["txn_date"].year, p["txn_date"].month) == "2026-02"][:6]
        + [p for p in purchases if p["txn_date"] >= date(2026, 6, 1)][:14])
for p in pool:
    p["ambiguous"] = True
    p["rate"] = rng.randint(4200, 6400)
    p["qty_t"] = round(rng.uniform(18, 55), 1)
DAMAGE["D1_unclassified"] = [p["id"] for p in pool]

# D2  tonnage that does not balance, caused by D1
DAMAGE["D2_unbalanced"] = {"2025-11": 180.0, "2026-02": 95.0}

# D4  two vouchers dated late October, entered three weeks later in November
d4 = sorted([p for p in purchases if p["txn_date"].month == 10 and p["txn_date"].day >= 22],
            key=lambda r: r["txn_date"])[:2]
for p in d4:
    p["entered_at"] = p["txn_date"] + timedelta(days=21)
DAMAGE["D4_backdated"] = [p["id"] for p in d4]

# D5  loads that went out with no sales voucher, and credit notes with no load
DAMAGE["D5_uninvoiced"] = [x["id"] for x in dispatches if x["dispatch_date"] >= date(2025, 8, 1)][:6]
DAMAGE["D5_orphan_credit_notes"] = ["CN-9001", "CN-9002"]

# D6  advances sitting against nothing
advances = [dict(id="ADV1", party="V04", direction="paid", adv_date=date(2024, 4, 12), amount=850000),
            dict(id="ADV2", party="V09", direction="paid", adv_date=date(2025, 4, 9), amount=620000),
            dict(id="ADV3", party="V02", direction="paid", adv_date=date(2026, 4, 15), amount=740000),
            dict(id="ADV4", party="V18", direction="paid", adv_date=date(2025, 11, 6), amount=410000),
            dict(id="ADV5", party="B03", direction="received", adv_date=date(2025, 9, 3), amount=1500000)]

# D8  dispatch rows where nobody wrote the contract reference down. Recoverable by asking.
DAMAGE["D8_missing_ref"] = [x["id"] for x in rng.sample(dispatches, min(60, len(dispatches)))]


# ============================================================== 9. write truth/
os.makedirs(OUT, exist_ok=True)


def dump(name, rows):
    if not rows:
        return
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(f"{OUT}/{name}.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=cols, restval="")
        wr.writeheader()
        wr.writerows(rows)


dump("purchase", purchases)
dump("production", production)
dump("dispatch", dispatches)
dump("invoice", invoices)
dump("recovery", recoveries)
dump("payment", payments)
dump("commitment", commitments)
dump("advance", advances)
dump("delivery_plan", [dict(tender_ref=k[0], month=k[1], planned_qty_t=round(v, 1))
                       for k, v in sorted(plan.items())])
dump("damage", [dict(code=k, detail=str(v)) for k, v in DAMAGE.items()])



# ============================================================== cost_by_month
# What a tonne of each product costs to make, month by month, and what that works out to
# per kilocalorie. This is the table the owner actually needs before he quotes anything:
# a price without a GCV is half a number, so cost has to be expressed per kcal too.
#
#   acquisition   what the raw material cost, at 1.35 t of residue per tonne of pellets
#   conversion    power, labour, drying, die wear, overhead
#   freight       roughly fixed across the year, quoted separately on the bid
#   cost_per_kcal total cost divided by the GCV we actually achieve
#   gcv min/max   the range that material can produce, so we know the downside
MATS = {r["material"]: r for r in load("materials")}
GRADE_MIX = {}
for g in sorted(load("grades"), key=lambda r: r["valid_from"]):
    GRADE_MIX[g["code"]] = g["made_from"]


def mix_gcv(made_from):
    """A blend inherits the average of what went into it."""
    parts = [m.strip() for m in made_from.split("+")]
    lo = sum(float(MATS[m]["gcv_min"]) for m in parts if m in MATS) / len(parts)
    ty = sum(float(MATS[m]["gcv_typical"]) for m in parts if m in MATS) / len(parts)
    hi = sum(float(MATS[m]["gcv_max"]) for m in parts if m in MATS) / len(parts)
    return lo, ty, hi


avg_freight = {}
for c in contracts:
    avg_freight.setdefault(c["grade_code"], []).append(float(c["freight_per_t"]))
avg_freight = {k: sum(v) / len(v) for k, v in avg_freight.items()}

cost_rows = []
for (y, m) in MONTHS:
    rows_m = [p for p in purchases if p["item"] in ("husk", "stalk")
              and p["txn_date"].year == y and p["txn_date"].month == m
              and not p.get("ambiguous")]
    if not rows_m:
        continue
    feed_rate_m = sum(p["rate"] * p["qty_t"] for p in rows_m) / sum(p["qty_t"] for p in rows_m)
    for code, made in GRADE_MIX.items():
        lo, ty, hi = mix_gcv(made)
        acq = round(CFG["feed_per_pellet"] * feed_rate_m, 2)
        conv = round(CFG["conversion_cost"], 2)
        total = round(acq + conv, 2)
        cost_rows.append(dict(month=mkey(y, m), grade_code=code, made_from=made,
                              acquisition_per_t=acq, conversion_per_t=conv,
                              total_cost_per_t=total,
                              freight_per_t=round(avg_freight.get(code, 0), 2),
                              gcv_min=round(lo), gcv_typical=round(ty), gcv_max=round(hi),
                              cost_per_kcal=round(total / ty, 4),
                              cost_per_kcal_worst=round(total / lo, 4),
                              cost_per_kcal_best=round(total / hi, 4)))
dump("cost_by_month", cost_rows)

# ============================================================== 10. the answer key
def r0(x): return f"{x:,.0f}"


def r1(x): return f"{x:,.1f}"


K = {}
paid = {}
for pm in payments:
    paid[pm["invoice_id"]] = paid.get(pm["invoice_id"], 0) + pm["amount"]

liveC = [c for c in contracts if d(c["window_end"]) >= TODAY]
_pool = [c for c in liveC if c["tender_ref"] != "T-26-07"] or liveC
demo = max(_pool, key=lambda c: float(c["tonnes"]))
dsp = [x for x in dispatches if x["tender_ref"] == demo["tender_ref"]]
K["a1_ref"] = demo["tender_ref"]
K["a1_plant"] = plants[demo["plant_id"]]["name"]
K["a1_tot"] = r0(float(demo["tonnes"]))
K["a1_out"] = r0(sum(x["qty_t"] for x in dsp))
K["a1_loads"] = len(dsp)
K["a1_left"] = r0(float(demo["tonnes"]) - sum(x["qty_t"] for x in dsp))

a2 = sum(float(c["tonnes"]) - out_by_contract.get(c["tender_ref"], 0) for c in liveC)
K["a2_a"], K["a2_b"], K["a2_n"] = r0(a2), r0(a2 * 1.25), len(liveC)


def avg_rate(month, kind="husk"):
    rows = [p for p in purchases if p["item"] == kind and p["txn_date"].month == month
            and not p.get("ambiguous")]
    return sum(p["rate"] * p["qty_t"] for p in rows) / sum(p["qty_t"] for p in rows)


apr, oct_ = avg_rate(4), avg_rate(10)
K["a3_apr"], K["a3_oct"], K["a3_gap"] = r0(apr), r0(oct_), r0(oct_ - apr)

byv = {}
for c in commitments:
    st = byv.setdefault(c["vendor_id"], dict(n=0, short=0, late=0))
    st["n"] += 1
    if c["delivered_t"] < c["qty_t"] - 0.01:
        st["short"] += 1
    if c["delivered_date"] > c["promised_date"]:
        st["late"] += 1
perfect = sorted(v for v, st in byv.items() if st["n"] >= 5 and st["short"] == 0 and st["late"] == 0)
K["a4_n"] = len(perfect)
K["a4"] = ", ".join(perfect[:10]) + (f", and {len(perfect) - 10} more" if len(perfect) > 10 else "")

div = []
for v, st in byv.items():
    rows = [c for c in commitments if c["vendor_id"] == v]
    hi = [c for c in rows if c["market_rate"] > c["rate_agreed"] * 1.08]
    if len(hi) >= 3 and sum(1 for c in hi if c["delivered_t"] < c["qty_t"] - .01) / len(hi) > 0.6:
        div.append(v)
K["a5"] = ", ".join(sorted(div))
K["a5_names"] = "; ".join(f"{v} ({V[v]['name']})" for v in sorted(div))

nov = [c for c in commitments if c["month"].endswith("-11")]
K["a6_tot"] = r0(sum(c["qty_t"] for c in nov))
K["a6_safe"] = r0(sum(c["qty_t"] for c in nov if byv[c["vendor_id"]]["short"] == 0))
K["a6_risk"] = r0(sum(c["qty_t"] for c in nov if byv[c["vendor_id"]]["short"] > 0))
K["a6_past"] = ", ".join(r0(sum(c["delivered_t"] for c in commitments if c["month"] == f"{y}-11"))
                         for y in (2023, 2024, 2025))


def realised(plant_ids, period):
    inv = [i for i in invoices if i["plant"] in plant_ids
           and fy(i["invoice_date"].year, i["invoice_date"].month) == period]
    dt = sum(x["qty_t"] for x in dispatches if x["plant"] in plant_ids
             and fy(x["dispatch_date"].year, x["dispatch_date"].month) == period)
    if not inv or not dt:
        return 0.0, 0.0
    return (sum(i["amount"] for i in inv) / sum(i["qty_accepted_t"] for i in inv),
            sum(i["quoted_amount"] for i in inv) / dt)


sip_a, sip_b = realised({"P1"}, "FY24-25")
K["a7_a"], K["a7_b"] = r0(sip_a), r0(sip_b)
psu_ids = {p for p, v in plants.items() if buyers[v["buyer_id"]]["kind"] == "psu"}
prv_ids = set(plants) - psu_ids
K["a9_psu"], K["a9_prv"] = r0(realised(psu_ids, "FY24-25")[0]), r0(realised(prv_ids, "FY24-25")[0])

rows8 = []
for pid_, pl in plants.items():
    rr = [i for i in invoices if i["plant"] == pid_
          and fy(i["invoice_date"].year, i["invoice_date"].month) == "FY24-25"]
    if rr:
        q = sum(i["quoted_amount"] for i in rr)
        rows8.append(f"| {pl['name']} | {sum(i['recovery'] for i in rr) / q * 100:+.2f}% |")
K["a8"] = chr(10).join(rows8)

p2425 = [r for r in production if fy(int(r["month"][:4]), int(r["month"][5:])) == "FY24-25"]
K["a10_tot"] = r0(sum(r["produced_t"] for r in p2425))
K["a10_lo"] = r0(min(r["produced_t"] for r in p2425))
K["a10_hi"] = r0(max(r["produced_t"] for r in p2425))

t7 = ([c for c in contracts if c["tender_ref"] == "T-26-07"]
      or [max(liveC, key=lambda c: float(c["tonnes"]))])[0]


def plan_cost(ms):
    return sum(CFG["feed_per_pellet"] * BASE.get(fy(y, m), BASE["FY26-27"]) * SEASON[m]
               + CFG["conversion_cost"] for (y, m) in ms) / len(ms)


even = [(y, m) for y in (2026, 2027) for m in range(1, 13)][3:27]
front = [(2026, 4), (2026, 5), (2026, 6), (2027, 4), (2027, 5), (2027, 6)]
e, f_ = float(t7["rate_per_t"]) - plan_cost(even), float(t7["rate_per_t"]) - plan_cost(front)
K["a11_c"], K["a11_m"] = r0(e), r0(float(t7["tonnes"]) / 24)
K["a12_c"], K["a12_m"], K["a12_d"] = r0(f_), r0(float(t7["tonnes"]) / 6), r0(f_ - e)

op = [i for i in invoices if i["amount"] - paid.get(i["id"], 0) > 1]
out = sum(i["amount"] - paid.get(i["id"], 0) for i in op)
adv_r = sum(a["amount"] for a in advances if a["direction"] == "received")
K["a13_a"], K["a13_b"], K["a13_adv"] = r0(out), r0(out - adv_r), r0(adv_r)
K["a13_psu"] = r0(sum(i["amount"] - paid.get(i["id"], 0) for i in op if i["plant"] in psu_ids))
K["a14_a"] = r0(sum(i["amount"] - paid.get(i["id"], 0) for i in op if (TODAY - i["crac_date"]).days > 30))
K["a14_b"] = r0(sum(i["amount"] - paid.get(i["id"], 0) for i in op if (TODAY - i["invoice_date"]).days > 45))

for lab, lo, hi in (("r1_a", date(2023, 4, 1), date(2024, 3, 31)),
                    ("r1_b", date(2024, 4, 1), date(2025, 3, 31))):
    K[lab] = r0(sum(x["qty_t"] for x in dispatches
                    if x["grade_code"] == "PLT-A1" and lo <= x["dispatch_date"] <= hi))

amb = [p for p in purchases if p.get("ambiguous")]
K["r2_n"], K["r2_t"] = len(amb), r1(sum(p["qty_t"] for p in amb))
own2526 = sum(r["produced_t"] for r in production
              if fy(int(r["month"][:4]), int(r["month"][5:])) == "FY25-26")
K["r2_lo"], K["r2_hi"] = r0(own2526 - sum(p["qty_t"] for p in amb)), r0(own2526)

DIV = (sorted(div)[0] if div else vendors[0]["vendor_id"])          # a diverting vendor
THIN = next((v["vendor_id"] for v in vendors if v["behaviour"] == "thin"), vendors[0]["vendor_id"])
v04 = [p for p in purchases if p["vendor_id"] == DIV]
mk = {}
for p in v04:
    kk = mkey(p["txn_date"].year, p["txn_date"].month)
    mk[kk] = mk.get(kk, 0) + p["qty_t"]
K["r3_best"] = r0(max(mk.values())) if mk else "0"
K["r3_months"] = len(mk)
K["r3_id"] = DIV
K["r3_name"] = V[DIV]["name"]
K["r4_id"] = THIN
K["r4_n"] = byv.get(THIN, {}).get("n", 0)
K["r4_name"] = V[THIN]["name"]
K["r5_d"] = len(dispatches)
K["r5_i"] = len(invoices) - len(DAMAGE["D5_uninvoiced"])


# --- the quotation cluster: capacity, cost, then the rate he should quote -------------
# This is the sequence the owner actually runs before he bids.

# forward commitments, month by month, for the next 12 months from TODAY
fut = [(2026, 9 + i) if 9 + i <= 12 else (2027, 9 + i - 12) for i in range(12)]
fwd = {mkey(y, m): 0.0 for (y, m) in fut}
for c in contracts:
    ws, we = d(c["window_start"]), d(c["window_end"])
    span = max(1, (we.year - ws.year) * 12 + (we.month - ws.month) + 1)
    per = float(c["tonnes"]) / span
    for (y, m) in fut:
        if ws <= date(y, m, 15) <= we:
            fwd[mkey(y, m)] += per

# what the plant has typically managed in each calendar month, three year average
cap_by_month = {}
for mm in range(1, 13):
    got = [r["produced_t"] for r in production if int(r["month"][5:]) == mm]
    cap_by_month[mm] = sum(got) / len(got) if got else 0

free = {k: cap_by_month[int(k[5:])] - v for k, v in fwd.items()}
tight = sorted(free.items(), key=lambda kv: kv[1])[:3]
loose = sorted(free.items(), key=lambda kv: -kv[1])[:3]
K["a3_tight"] = "; ".join(f"{k} only {r0(v)} t spare" for k, v in tight)
K["a3_loose"] = "; ".join(f"{k} {r0(v)} t spare" for k, v in loose)
K["a3_total_free"] = r0(sum(max(0, v) for v in free.values()))

# what a tonne costs to make, by production window
def window_cost(months):
    """1.35 t of feedstock at that month's three year average rate, plus conversion."""
    tot = 0
    for mm in months:
        rows = [p for p in purchases if p["item"] in ("husk", "stalk")
                and p["txn_date"].month == mm and not p.get("ambiguous")]
        rate = sum(p["rate"] * p["qty_t"] for p in rows) / sum(p["qty_t"] for p in rows)
        tot += CFG["feed_per_pellet"] * rate + CFG["conversion_cost"]
    return tot / len(months)


cost_amj, cost_son = window_cost([4, 5, 6]), window_cost([9, 10, 11])
K["a5_amj"], K["a5_son"] = r0(cost_amj), r0(cost_son)
K["a5_gap"] = r0(cost_son - cost_amj)

# the quote itself. cost + the margin he wants = the rate. Then divide by GCV.
TARGET = 1000.0
K["a6_target"] = r0(TARGET)
K["a6_rate"] = r0(cost_amj + TARGET)
K["a6_perkcal"] = f"{(cost_amj + TARGET) / 3200:.2f}"
K["a6_cost"] = r0(cost_amj)
K["a7_gcv"] = "3,400"
K["a7_rate"] = r0((cost_amj + TARGET) / 3200 * 3400)
K["a7_extra"] = r0((cost_amj + TARGET) / 3200 * 200)
K["a7_risk"] = r0((cost_amj + TARGET) / 3200 * 400)

# which grade is the most profitable line
rows12 = []
for g in sorted({c["grade_code"] for c in contracts}):
    inv = [i for i in invoices if i["tender_ref"] in
           {c["tender_ref"] for c in contracts if c["grade_code"] == g}
           and fy(i["invoice_date"].year, i["invoice_date"].month) == "FY24-25"]
    if not inv:
        continue
    got = sum(i["amount"] for i in inv) / sum(i["qty_accepted_t"] for i in inv)
    rows12.append((g, got, got - window_cost(list(range(1, 13)))))
rows12.sort(key=lambda r: -r[2])
K["a12"] = chr(10).join(f"| {g} | Rs {r0(rev)}/t | Rs {r0(mar)}/t |" for g, rev, mar in rows12)
K["a12_best"] = rows12[0][0] if rows12 else "n/a"
K["a12_bestm"] = r0(rows12[0][2]) if rows12 else "0"


# --- everything below is priced PER GCV, because a price without a GCV is half a number ----

def feed_cost_per_gcv(month, item):
    """What a GCV point of this feedstock costs in this calendar month, three year average."""
    rows = [p for p in purchases if p["item"] == item and p["txn_date"].month == month
            and not p.get("ambiguous")]
    if not rows:
        return 0
    rate = sum(p["rate"] * p["qty_t"] for p in rows) / sum(p["qty_t"] for p in rows)
    return rate / FEED_KCAL[item]


K["a4_husk_t"] = r0(avg_rate(4, "husk"))
K["a4_stalk_t"] = r0(avg_rate(4, "stalk"))
K["a4_husk_g"] = f"{feed_cost_per_gcv(4, 'husk'):.3f}"
K["a4_stalk_g"] = f"{feed_cost_per_gcv(4, 'stalk'):.3f}"
K["a4_better"] = "stalk" if feed_cost_per_gcv(4, "stalk") < feed_cost_per_gcv(4, "husk") else "husk"

MAIN_GRADE = max(GRADE_KCAL, key=lambda g: sum(
    1 for c in contracts if c["grade_code"] == g))      # the grade we ship most


def window_cost_pergcv(months, grade=None):
    grade = grade or MAIN_GRADE
    """Cost per tonne, then per GCV point of the product we actually make."""
    tot = 0
    for mm in months:
        rows = [p for p in purchases if p["item"] in ("husk", "stalk")
                and p["txn_date"].month == mm and not p.get("ambiguous")]
        rate = sum(p["rate"] * p["qty_t"] for p in rows) / sum(p["qty_t"] for p in rows)
        tot += CFG["feed_per_pellet"] * rate + CFG["conversion_cost"]
    per_t = tot / len(months)
    return per_t, per_t / GRADE_KCAL[grade]


amj_t, amj_g = window_cost_pergcv([4, 5, 6])
son_t, son_g = window_cost_pergcv([9, 10, 11])
K["a5_amj"], K["a5_son"] = r0(amj_t), r0(son_t)
K["a5_amj_g"], K["a5_son_g"] = f"{amj_g:.3f}", f"{son_g:.3f}"
K["a5_gap"], K["a5_gap_g"] = r0(son_t - amj_t), f"{son_g - amj_g:.3f}"
K["a5_grade_kcal"] = r0(GRADE_KCAL[MAIN_GRADE])
K["a5_grade"] = MAIN_GRADE

# the cheapest month to run, per GCV
by_month = {mm: window_cost_pergcv([mm])[1] for mm in range(1, 13)}
best_m = min(by_month, key=by_month.get)
worst_m = max(by_month, key=by_month.get)
MN = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June", 7: "July",
      8: "August", 9: "September", 10: "October", 11: "November", 12: "December"}
K["a5_best_m"], K["a5_best_g"] = MN[best_m], f"{by_month[best_m]:.3f}"
K["a5_worst_m"], K["a5_worst_g"] = MN[worst_m], f"{by_month[worst_m]:.3f}"

# the quote, worked entirely in rupees per GCV
TARGET_G = 0.30                      # rupees of margin per GCV point
K["a6_cost_g"] = f"{amj_g:.3f}"
K["a6_target_g"] = f"{TARGET_G:.2f}"
K["a6_quote_g"] = f"{amj_g + TARGET_G:.3f}"
K["a6_cost"] = r0(amj_t)
K["a6_at3200"] = r0((amj_g + TARGET_G) * 3200)
K["a6_at3400"] = r0((amj_g + TARGET_G) * 3400)
K["a6_margin3200"] = r0((amj_g + TARGET_G) * 3200 - amj_t)
K["a7_per200"] = r0((amj_g + TARGET_G) * 200)
K["a7_below"] = r0((amj_g + TARGET_G) * 2700 * 0.75)

# most profitable line, ranked per GCV not per tonne
rows12 = []
for gc in sorted(GRADE_KCAL):
    refs = {c["tender_ref"] for c in contracts if c["grade_code"] == gc}
    inv = [i for i in invoices if i["tender_ref"] in refs
           and fy(i["invoice_date"].year, i["invoice_date"].month) == "FY24-25"]
    if not inv:
        continue
    rev_t = sum(i["amount"] for i in inv) / sum(i["qty_accepted_t"] for i in inv)
    cost_t = window_cost_pergcv(list(range(1, 13)), gc)[0]
    kc = GRADE_KCAL[gc]
    rows12.append((gc, kc, rev_t, cost_t, (rev_t - cost_t) / kc))
rows12.sort(key=lambda r: -r[4])
K["a12"] = chr(10).join(f"| {g} | {r0(kc)} | Rs {r0(rv)}/t | Rs {r0(ct)}/t | **Rs {mg:.3f}** |"
                        for g, kc, rv, ct, mg in rows12)
K["a12_best"] = rows12[0][0] if rows12 else "n/a"
K["a12_bestg"] = f"{rows12[0][4]:.3f}" if rows12 else "0"

if TENANT == "a":
    MD = io.open("questions_template.md", encoding="utf-8").read()
    # questions.md is written by hand now: it covers all 23 questions, both companies and
    # the reasoning behind each refusal, which a format string cannot carry. The figures in
    # it are checked by app/run_questions.py on every run, so it cannot drift silently.
    io.open("questions_generated.md", "w", encoding="utf-8").write(MD.format(**K))
else:
    lines = ["# Tenant " + TENANT.upper() + " answer key", ""]
    for k, v in sorted(K.items()):
        if isinstance(v, str) and chr(10) in v:
            continue
        lines.append("- **" + k + "** = " + str(v))
    io.open("answers_" + TENANT + ".md", "w", encoding="utf-8").write(chr(10).join(lines))

total = (len(purchases) + len(dispatches) + len(invoices) + len(payments)
         + len(commitments) + len(production) + len(recoveries) + len(advances))
print("seed_inputs read.  truth/ written.  questions_generated.md written.")
print(f"  vendors {len(vendors)}   contracts {len(contracts)}   live at {TODAY}: {len(liveC)}")
print(f"  purchases {len(purchases)}   dispatches {len(dispatches)}   invoices {len(invoices)}")
print(f"  payments {len(payments)}   commitments {len(commitments)}   production {len(production)}")
print(f"  total transaction rows {total}")
