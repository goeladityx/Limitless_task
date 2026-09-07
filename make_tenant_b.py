"""
Builds seed_inputs_b/ : the second company.

The brief needs two tenants for two reasons. They define the same words differently, and
their data must never mix. So tenant B is a genuinely different business, not a copy:

  - different vendors, different names, based in Gujarat rather than Rajasthan
  - buys in far more finished pellets than it makes (35% of tonnage against A's 12%)
  - different contracts, mostly private buyers rather than PSU tenders
  - THE DEFECTS SIT ON DIFFERENT ROWS. Anything hardcoded to fix A has to fail on B.

Run:  python make_tenant_b.py
Then: python truth_gen.py b
"""

import csv, os, random, shutil
from datetime import date

rng = random.Random(31)
SRC, DST = "seed_inputs", "seed_inputs_b"
os.makedirs(DST, exist_ok=True)


def read(name):
    with open(f"{SRC}/{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(name, rows):
    with open(f"{DST}/{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- vendors
# A Gujarat trader base. Fewer vendors, more of them selling finished pellets, because
# tenant B is a trader-heavy operation that buys more than it makes.
PRE = ["Shree", "Jay", "Maa", "Om", "New", "Sardar", "Somnath", "Dwarka"]
MID = ["Ambaji", "Girnar", "Saurashtra", "Kathiawad", "Narmada", "Tapi", "Sabar", "Bhadar",
       "Vallabh", "Patel", "Desai", "Solanki", "Jadeja", "Chudasama", "Vaghela", "Gohil",
       "Rann", "Kutch", "Bhal", "Charotar"]
SUF = ["Agro Traders", "Biofuels", "Krishi Udyog", "Agri Residue LLP", "Trading Company",
       "Bioenergy", "Agro Exports", "Pellet Works", "Biomass LLP"]
TOWN = ["Rajkot", "Junagadh", "Amreli", "Bhavnagar", "Morbi", "Surendranagar", "Gondal",
        "Jamnagar", "Botad", "Porbandar", "Anand", "Nadiad"]

vend, seen = [], set()
for i in range(38):
    while True:
        nm = f"{rng.choice(PRE)} {rng.choice(MID)} {rng.choice(SUF)}"
        if nm not in seen:
            seen.add(nm)
            break
    r = rng.random()
    # trader-heavy: far more finished-pellet suppliers than tenant A has
    supplies = "husk" if r < .34 else "stalk" if r < .52 else "finished" if r < .86 else "both"
    b = rng.random()
    beh = "reliable" if b < .50 else "erratic" if b < .72 else "late" if b < .86 else "diverter"
    vend.append(dict(vendor_id=f"W{i + 1:02d}", name=nm, town=rng.choice(TOWN),
                     region="Gujarat", supplies=supplies, behaviour=beh,
                     gstin=f"24{chr(65 + i % 26)}{chr(65 + (i * 5) % 26)}BBB{3000 + i}B1Z{i % 10}"))

# the fixed cases, on DIFFERENT ids than tenant A. A fix hardcoded to V04 does nothing here.
vend[10]["behaviour"] = "diverter"       # W11
vend[21]["behaviour"] = "diverter"       # W22
vend[16]["behaviour"] = "late"           # W17
vend[29]["behaviour"] = "thin"           # W30, the too-few-commitments case (A uses V15)
vend[7]["supplies"] = "both"             # W08 sells husk and finished pellets
write("vendors", vend)

# ---------------------------------------------------------------- buyers and plants
# Mostly private industry. Only one PSU, and it isn't NTPC.
write("buyers", [
    dict(buyer_id="K01", name="Gujarat State Electricity Corporation", kind="psu"),
    dict(buyer_id="K02", name="Morbi Ceramic Cluster", kind="private"),
    dict(buyer_id="K03", name="Ankleshwar Chemicals", kind="private"),
    dict(buyer_id="K04", name="Vapi Textile Park", kind="private"),
    dict(buyer_id="K05", name="Kutch Salt Works", kind="private"),
])
write("plants", [
    dict(plant_id="Q1", buyer_id="K01", name="Ukai TPS", state="Gujarat", quoted_gcv=3100),
    dict(plant_id="Q2", buyer_id="K01", name="Sikka TPS", state="Gujarat", quoted_gcv=3100),
    dict(plant_id="Q3", buyer_id="K02", name="Morbi Cluster", state="Gujarat", quoted_gcv=3400),
    dict(plant_id="Q4", buyer_id="K03", name="Ankleshwar", state="Gujarat", quoted_gcv=3300),
    dict(plant_id="Q5", buyer_id="K04", name="Vapi", state="Gujarat", quoted_gcv=3200),
    dict(plant_id="Q6", buyer_id="K05", name="Kutch", state="Gujarat", quoted_gcv=3000),
])

# ---------------------------------------------------------------- grades
# THE REUSED CODE IS A DIFFERENT ONE. Tenant A reuses PLT-A1 on 1 Apr 2024.
# Tenant B reuses PLT-C3, and on a different date. Nothing about A's fix transfers.
write("grades", [
    dict(grade_id="H1", code="PLT-C3", valid_from="2023-04-01", valid_to="2025-03-31",
         kcal=3300, description="cotton stalk pellet"),
    dict(grade_id="H2", code="PLT-C3", valid_from="2025-04-01", valid_to="2028-03-31",
         kcal=3750, description="groundnut shell blend"),
    dict(grade_id="H3", code="PLT-D4", valid_from="2023-04-01", valid_to="2028-03-31",
         kcal=3450, description="mixed Gujarat residue"),
])

# ---------------------------------------------------------------- contracts
# Smaller, shorter, more of them. A trader takes many small contracts rather than a few
# large tenders, so "what have I promised" is arguably worse here than at tenant A.
NT, PV = ["Q1", "Q2"], ["Q3", "Q4", "Q5", "Q6"]
RATE = {"Q1": 6800, "Q2": 6700, "Q3": 7200, "Q4": 7050, "Q5": 6900, "Q6": 6400}
FRT = {"Q1": 690, "Q2": 720, "Q3": 380, "Q4": 520, "Q5": 610, "Q6": 840}

cons, n = [], 0
for yr in (2023, 2024, 2025, 2026):
    for mo in range(1, 13):
        if not (date(2023, 4, 1) <= date(yr, mo, 1) <= date(2026, 8, 1)):
            continue
        for _ in range(rng.randint(1, 3)):
            n += 1
            psu = rng.random() < .28                    # mostly private, unlike tenant A
            pl = rng.choice(NT if psu else PV)
            months = rng.choice([6, 9, 12, 12, 18])     # shorter than A's contracts
            ey, em = yr + (mo - 1 + months) // 12, (mo - 1 + months) % 12 + 1
            cons.append(dict(tender_ref=f"{'G' if psu else 'M'}-{yr % 100:02d}-{n:02d}",
                             plant_id=pl, grade_code="PLT-C3" if psu else "PLT-D4",
                             tonnes=rng.choice([600, 900, 1200, 1800, 2400, 3000]),
                             window_start=f"{yr}-{mo:02d}-01", window_end=f"{ey}-{em:02d}-28",
                             rate_per_t=RATE[pl], freight_per_t=FRT[pl],
                             option_pct=0.25 if psu else 0))
write("contracts", cons)

# ---------------------------------------------------------------- prices
# Gujarat runs on cotton stalk and groundnut shell, so the season peaks in a different
# month. Cheapest in December after the cotton picking, dearest in July.
write("price_curve", [
    dict(month=12, index=1.000, note="cheapest, cotton stalk after picking"),
    dict(month=1, index=1.020, note=""), dict(month=2, index=1.045, note=""),
    dict(month=3, index=1.075, note=""), dict(month=4, index=1.100, note=""),
    dict(month=5, index=1.125, note=""),
    dict(month=6, index=1.150, note="pre-monsoon, stocks low"),
    dict(month=7, index=1.170, note="dearest"),
    dict(month=8, index=1.140, note=""), dict(month=9, index=1.095, note=""),
    dict(month=10, index=1.055, note="groundnut harvest"), dict(month=11, index=1.020, note=""),
])
write("price_base", [dict(financial_year="FY23-24", april_husk_rate=2140),
                     dict(financial_year="FY24-25", april_husk_rate=2260),
                     dict(financial_year="FY25-26", april_husk_rate=2350),
                     dict(financial_year="FY26-27", april_husk_rate=2470)])

# ---------------------------------------------------------------- feedstock
write("feedstock", [
    dict(item="husk", kcal_per_kg=3150, note="cotton stalk, as received"),
    dict(item="stalk", kcal_per_kg=3550, note="groundnut shell"),
    dict(item="pellets", kcal_per_kg=3750, note="bought-in finished pellets"),
])

# ---------------------------------------------------------------- config
# Different plant, different economics. Buys in far more than tenant A does.
cfg = {r["key"]: r for r in read("config")}
cfg["feed_per_pellet"]["value"] = 1.28
cfg["conversion_cost"]["value"] = 3320
cfg["stalk_discount"]["value"] = 1.08
cfg["finished_pellet_base"]["value"] = 7180
cfg["private_unpaid_share"]["value"] = 0.24         # worse payers than tenant A
cfg["private_part_pay_share"]["value"] = 0.42
cfg["consignment_min_t"]["value"] = 120             # smaller loads, road not rail
cfg["consignment_max_t"]["value"] = 240
write("config", list(cfg.values()))

# ---------------------------------------------------------------- damage
# Same kinds of damage, different months and different sizes.
write("damage", [
    dict(code="D1", what="purchases that cannot be classified as feedstock or finished pellets",
         where="2025-07,2025-08,2026-03..05", size=19,
         note="different months from tenant A"),
    dict(code="D2", what="tonnage out exceeds opening plus produced plus purchased",
         where="2025-07=140;2026-04=210", size=350, note="caused by D1"),
    dict(code="D3", what="item code PLT-C3 reused for a different product",
         where="2025-04-01", size=1, note="a different code and a different date from tenant A"),
    dict(code="D4", what="purchase vouchers back-dated three weeks",
         where="June 2024 and June 2025", size=3, note="three of them here, not two"),
    dict(code="D5", what="dispatches with no sales voucher", where="FY24-25", size=4, note=""),
    dict(code="D6", what="advances not linked to any invoice", where="spread", size=7, note=""),
    dict(code="D7", what="invoices settled in two or three parts", where="private buyers",
         size=0.42, note="worse than tenant A"),
    dict(code="D8", what="dispatch rows with no tender reference", where="spread", size=95,
         note="worse record keeping than tenant A"),
    dict(code="D9", what="vendor with too few commitments to judge", where="W30", size=2,
         note="a different vendor id from tenant A"),
    dict(code="D10", what="vendor capacity never recorded anywhere", where="all vendors",
         size=0, note="same everywhere"),
])

print("seed_inputs_b written:", len(sorted(os.listdir(DST))), "files")
print("  38 vendors, all Gujarat, ids W01..W38")
print("  ", len(cons), "contracts, mostly private, shorter windows")
print("   reused item code is PLT-C3 on 2025-04-01, not PLT-A1 on 2024-04-01")
print("   thin-evidence vendor is W30, not V15")
