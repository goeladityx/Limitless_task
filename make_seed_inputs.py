"""
Writes seed_inputs/*.csv: the hand-editable description of the fictional company.

Run this once. After that, edit the CSVs directly. truth_gen.py reads them and generates
the transactions. Nothing about the company is hardcoded in the generator any more.
"""

import csv, os, random
from datetime import date

rng = random.Random(7)
os.makedirs("seed_inputs", exist_ok=True)


def w(name, cols, rows):
    with open(f"seed_inputs/{name}.csv", "w", newline="", encoding="utf-8") as f:
        cw = csv.writer(f)
        cw.writerow(cols)
        cw.writerows(rows)


# --------------------------------------------------------------- vendors
# 55 of them: 41 in Rajasthan, 14 in Gujarat, matching "50+ in Rajasthan, 100+ across India".
# These are aggregators, not farmers, so all GST registered.
PRE = ["Shri", "Shree", "Jai", "Maa", "Om", "New", "Sanwariya", "Salasar", "Khatu", "Nakoda"]
MID = ["Balaji", "Ganesh", "Krishna", "Marudhar", "Rathore", "Chaudhary", "Bhagwati", "Suraj",
       "Deepak", "Mahaveer", "Ramdev", "Bhairav", "Jagdamba", "Narayan", "Govind", "Shyam",
       "Laxmi", "Vijay", "Rajputana", "Thar", "Aravali", "Banas", "Luni", "Chambal",
       "Saurashtra", "Kathiawad", "Sardar"]
SUF = ["Agro Traders", "Krishi Udyog", "Biomass Suppliers", "Agri Residue Pvt Ltd",
       "Trading Co", "Enterprises", "Agro Industries", "Krishi Bhandar", "Biomass Co",
       "Fuels", "Agro Company"]
RJ = ["Bikaner", "Sikar", "Nagaur", "Ganganagar", "Churu", "Jhunjhunu", "Alwar", "Bhilwara",
      "Pali", "Jodhpur", "Barmer", "Hanumangarh", "Kota", "Bundi", "Jaipur", "Sirohi", "Tonk"]
GJ = ["Rajkot", "Junagadh", "Amreli", "Bhavnagar", "Morbi", "Surendranagar", "Gondal"]

vend, seen = [], set()
for i in range(55):
    while True:
        nm = f"{rng.choice(PRE)} {rng.choice(MID)} {rng.choice(SUF)}"
        if nm not in seen:
            seen.add(nm)
            break
    region = "Rajasthan" if i < 41 else "Gujarat"
    town = rng.choice(RJ if region == "Rajasthan" else GJ)

    # what they sell. "both" matters: vendor identity alone never tells you the channel.
    r = rng.random()
    supplies = "husk" if r < .50 else "stalk" if r < .78 else "finished" if r < .93 else "both"

    # behaviour shows up only through their delivery history, never as a label in the product
    b = rng.random()
    beh = "reliable" if b < .58 else "erratic" if b < .76 else "late" if b < .88 else "diverter"

    state = "08" if region == "Rajasthan" else "24"       # Rajasthan / Gujarat GST codes
    vend.append([f"V{i + 1:02d}", nm, town, region, supplies, beh,
                 f"{state}{chr(65 + i % 26)}{chr(65 + (i * 7) % 26)}AAA{2000 + i}A1Z{i % 10}"])

# the cases specific questions depend on
vend[3][5] = "diverter"      # V04, caught by A5
vend[6][5] = "diverter"      # V07, caught by A5
vend[8][5] = "late"          # V09, delivers in full but weeks late
vend[14][5] = "thin"         # V15, only two commitments ever. R4 refuses on him
vend[17][4] = "both"         # V18, sells husk and finished pellets. Blocks the easy shortcut
w("vendors", ["vendor_id", "name", "town", "region", "supplies", "behaviour", "gstin"], vend)

# --------------------------------------------------------------- buyers and plants
# The seven NTPC plant names are the real ones from GEM/2026/B/7652841.
w("buyers", ["buyer_id", "name", "kind"], [
    ["B01", "NTPC Limited", "psu"],
    ["B02", "Rajasthan Rajya Vidyut Utpadan Nigam", "psu"],
    ["B03", "Nagaur Cement Works", "private"],
    ["B04", "Jaipur Bottling Plant", "private"],
    ["B05", "Bhilwara Paper Mills", "private"],
    ["B06", "Kota Textile Processors", "private"],
])

# quoted_gcv sets the rate per kcal: rate_per_t / quoted_gcv
w("plants", ["plant_id", "buyer_id", "name", "state", "quoted_gcv"], [
    ["P1", "B01", "NTPC Sipat", "Chhattisgarh", 3200],
    ["P2", "B01", "NTPC Korba", "Chhattisgarh", 3200],
    ["P3", "B01", "NTPC Mouda", "Maharashtra", 3200],
    ["P4", "B01", "NTPC North Karanpura", "Jharkhand", 3200],
    ["P5", "B01", "NTPC Darlipali", "Odisha", 3200],
    ["P6", "B01", "NTPC Lara", "Chhattisgarh", 3200],
    ["P7", "B01", "NTPC Gadarwara", "Madhya Pradesh", 3200],
    ["P8", "B02", "Suratgarh STPS", "Rajasthan", 3100],
    ["P9", "B03", "Nagaur Cement", "Rajasthan", 3100],
    ["P10", "B04", "Jaipur Bottling", "Rajasthan", 3300],
    ["P11", "B05", "Bhilwara Paper", "Rajasthan", 3000],
    ["P12", "B06", "Kota Textile", "Rajasthan", 3000],
])

# --------------------------------------------------------------- grades
# PLT-A1 is reused for a different product from 1 Apr 2024. The boundary sits on a
# financial year end so FY23-24 is cleanly one product and FY24-25 cleanly the other.
w("grades", ["grade_id", "code", "valid_from", "valid_to", "kcal", "description"], [
    ["G1", "PLT-A1", "2023-04-01", "2024-03-31", 3200, "rice husk pellet"],
    ["G2", "PLT-A1", "2024-04-01", "2028-03-31", 3600, "mixed residue pellet"],
    ["G3", "PLT-B2", "2023-04-01", "2028-03-31", 3400, "mustard stalk pellet"],
    ["G4", "PLT-T1", "2025-04-01", "2028-03-31", 4100, "torrefied pellet"],
])

# --------------------------------------------------------------- contracts
# GPE runs 50 to 60 contracts in a financial year. About 50 here across three years,
# staggered so roughly 20 are live at any moment. That is the whole point of problem 1:
# nobody can add up what has already been promised.
NT = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
PV = ["P9", "P10", "P11", "P12"]
RATE = {"P1": 7100, "P2": 6950, "P3": 6800, "P4": 6750, "P5": 6900, "P6": 7050, "P7": 6700,
        "P8": 6600, "P9": 6400, "P10": 6900, "P11": 6100, "P12": 6250}
FRT = {"P1": 1880, "P2": 1640, "P3": 1450, "P4": 1720, "P5": 1810, "P6": 1690, "P7": 1380,
       "P8": 740, "P9": 620, "P10": 780, "P11": 540, "P12": 600}

cons, n = [], 0
for yr in (2023, 2024, 2025, 2026):
    for mo in range(1, 13):
        if not (date(2023, 4, 1) <= date(yr, mo, 1) <= date(2026, 8, 1)):
            continue
        for _ in range(rng.randint(1, 2)):
            n += 1
            psu = rng.random() < .62
            pl = rng.choice(NT if psu else PV)
            months = rng.choice([12, 18, 24, 24, 30])
            ey, em = yr + (mo - 1 + months) // 12, (mo - 1 + months) % 12 + 1
            cons.append([f"{'T' if psu else 'C'}-{yr % 100:02d}-{n:02d}", pl,
                         "PLT-A1" if psu else "PLT-B2",
                         rng.choice([1800, 2400, 3000, 3600, 4200, 4800, 6000, 8000]),
                         f"{yr}-{mo:02d}-01", f"{ey}-{em:02d}-28",
                         RATE[pl], FRT[pl], 0.25 if psu else 0])
# the live tender the demo is about, taken from the real bid
cons.append(["T-26-07", "P1", "PLT-A1", 4200, "2026-04-01", "2028-03-31", 7640, 1950, 0.25])
w("contracts", ["tender_ref", "plant_id", "grade_code", "tonnes", "window_start",
                "window_end", "rate_per_t", "freight_per_t", "option_pct"], cons)

# --------------------------------------------------------------- prices
# Feedstock is cheapest in April and dearest in October. This curve is the single most
# important thing in the file: the whole seasonal argument rests on it.
w("price_curve", ["month", "index", "note"], [
    [4, 1.000, "cheapest, wheat and mustard residue flooding in"],
    [5, 1.030, ""], [6, 1.060, ""],
    [7, 1.100, "monsoon, harder to dry"], [8, 1.130, ""], [9, 1.160, ""],
    [10, 1.165, "dearest, the lean gap before paddy comes off"],
    [11, 1.090, "paddy arrives"], [12, 1.050, ""],
    [1, 1.040, ""], [2, 1.050, ""], [3, 1.010, ""],
])
w("price_base", ["financial_year", "april_husk_rate"], [
    ["FY23-24", 1950], ["FY24-25", 2060], ["FY25-26", 2180], ["FY26-27", 2290],
])

# --------------------------------------------------------------- config
w("config", ["key", "value", "note"], [
    ["feed_per_pellet", 1.35, "tonnes of residue per tonne of pellets. CHECK THIS"],
    ["conversion_cost", 3050, "rupees per tonne, conversion plus overhead. CHECK THIS"],
    ["stalk_discount", 0.92, "stalk runs about 8 percent below husk"],
    ["finished_pellet_base", 6950, "rupees per tonne for bought-in finished pellets"],
    ["gcv_floor_full", 2800, "below this a further 25 percent comes off"],
    ["gcv_reject", 2000, "below this the load is rejected outright"],
    ["gcv_penalty", 0.25, "the cut applied between 2000 and 2800"],
    ["psu_payment_days", 30, "NTPC settles within 30 days of the acceptance certificate"],
    ["private_payment_days_min", 48, ""],
    ["private_payment_days_max", 115, ""],
    ["private_unpaid_share", 0.18, "share of private invoices still open"],
    ["private_part_pay_share", 0.30, "share of private invoices settled in 2 or 3 parts"],
    ["wastage", 1.04, "feedstock bought over feedstock used"],
    ["consignment_min_t", 260, "smallest dispatch consignment"],
    ["consignment_max_t", 420, "largest dispatch consignment"],
])

# --------------------------------------------------------------- damage
# Every defect, where it lands, and how big. Editing this file changes what the system
# can and cannot answer, which is exactly what it should do.
w("damage", ["code", "what", "where", "size", "note"], [
    ["D1", "purchases that cannot be classified as feedstock or finished pellets",
     "2025-11,2026-02,2026-06..08", 28, "rate lands in the dead zone between husk and pellets"],
    ["D2", "tonnage out exceeds opening plus produced plus purchased",
     "2025-11=180;2026-02=95", 275, "caused by D1"],
    ["D3", "item code PLT-A1 reused for a different product", "2024-04-01", 1,
     "boundary sits on a financial year end"],
    ["D4", "purchase vouchers back-dated three weeks", "October 2024 and October 2025", 2,
     "entered mid November, so October moves after month end"],
    ["D5", "dispatches with no sales voucher", "FY25-26", 6,
     "plus 2 credit notes with no matching dispatch"],
    ["D6", "advances not linked to any invoice", "spread", 5,
     "4 paid to vendors, 1 received from a buyer"],
    ["D7", "invoices settled in two or three parts", "private buyers", 0.30, ""],
    ["D8", "dispatch rows with no tender reference", "spread", 60,
     "recoverable by asking the dispatch team, not ambiguous"],
    ["D9", "vendor with too few commitments to judge", "V15", 2, "thin evidence, R4 refuses"],
    ["D10", "vendor capacity never recorded anywhere", "all vendors", 0,
     "permanently unanswerable, R3 refuses"],
])

print("seed_inputs written:", sorted(os.listdir("seed_inputs")))
