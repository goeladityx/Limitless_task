"""
Step 0: the contract book, generated under the rule that actually governs this trade.

One buyer runs one contract at a time. NTPC floats a tender for a plant, it runs for twelve
months, and the next one is only signed after that one closes. You do not have three live
tenders against NTPC Darlipali at once, and a private buyer like Jaipur Bottling does not
run five contracts in parallel either. If you lose a year's bid you simply have no contract
with that plant that year.

That rule matters well beyond tidiness. If contracts for one destination can overlap, then a
load that arrives with no tender reference written on it is genuinely ambiguous and needs a
human. Under the real rule it is not ambiguous at all: the destination and the date pick out
exactly one contract, and the only loads a person has to look at are the ones that fall in a
gap between two contracts. That is a recording failure, not a judgement call, and the two
should never have been dressed up as the same thing.

    PSU tenders    run the financial year, 1 April to 31 March
    private        run twelve months from whenever the contract was signed
    gaps           are allowed and normal. Overlaps are not, and are asserted against below

Run:  python seed_contracts.py          (writes both tenants' contracts.csv)
"""

import csv
import random
from datetime import date, timedelta

# Tonnage per contract is set so the book adds up to the turnover the business actually
# does. Marudhar runs at 150 to 180 crore a year, which at seven and a half thousand a
# tonne is a little over two lakh tonnes a year across every buyer. Saurashtra is a
# smaller LLP and its book is built to say so.
TEN = {
    # tenant -> (seed folder, rng seed, first FY, years, tonnes per year per plant)
    "a": ("seed_inputs",   71, 2023, 4, {"psu": (20000, 27000), "private": (5500, 9000)}),
    "b": ("seed_inputs_b", 83, 2023, 4, {"psu": (17000, 23000), "private": (4500, 7500)}),
}


def load(folder, name):
    with open(f"{folder}/{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def add_months(d, n):
    y, m = divmod((d.month - 1) + n, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def build(tenant):
    folder, seed, fy0, years, SIZE = TEN[tenant]
    rng = random.Random(seed)
    buyers = {b["buyer_id"]: b for b in load(folder, "buyers")}
    plants = load(folder, "plants")
    grades = sorted({g["code"] for g in load(folder, "grades")})
    old = load(folder, "contracts")

    # freight is a function of distance, so it belongs to the plant and not to the year
    freight = {}
    for r in old:
        freight.setdefault(r["plant_id"], float(r["freight_per_t"]))

    rows = []
    for pl in plants:
        kind = buyers[pl["buyer_id"]]["kind"]
        lo, hi = SIZE[kind]
        # a private buyer signs whenever the last contract ran out, a PSU on 1 April
        start = date(fy0, 4, 1) if kind == "psu" else \
            date(fy0, rng.choice([4, 5, 6, 7]), 1)
        for i in range(years):
            # you do not win every year. A missed year leaves a real gap in the book.
            if i and rng.random() < (0.12 if kind == "psu" else 0.18):
                start = add_months(start, 12)
                continue
            end = add_months(start, 12) - timedelta(days=1)
            ref = ("T-%s-%02d" if kind == "psu" else "C-%s-%02d") % (
                str(start.year)[2:], len(rows) + 1)
            escal = 1 + 0.035 * i
            rows.append({
                "tender_ref": ref,
                "plant_id": pl["plant_id"],
                "grade_code": rng.choice(grades),
                "tonnes": int(round(rng.uniform(lo, hi) / 100.0) * 100),
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "rate_per_t": int(round(rng.uniform(6900, 8300) * escal / 10.0) * 10),
                "freight_per_t": int(freight.get(pl["plant_id"], 1750)),
                # the buyer's right to call for more. A PSU always has it, a private
                # buyer usually does not.
                "option_pct": 0.25 if kind == "psu" else 0.0,
            })
            start = add_months(start, 12)

    # ---- the rule, asserted rather than hoped for
    by_plant = {}
    for r in rows:
        by_plant.setdefault(r["plant_id"], []).append(r)
    for pid, rs in by_plant.items():
        rs.sort(key=lambda r: r["window_start"])
        for a, b in zip(rs, rs[1:]):
            assert b["window_start"] > a["window_end"], \
                f"{pid}: {a['tender_ref']} and {b['tender_ref']} overlap"

    rows.sort(key=lambda r: (r["window_start"], r["plant_id"]))
    cols = ["tender_ref", "plant_id", "grade_code", "tonnes", "window_start", "window_end",
            "rate_per_t", "freight_per_t", "option_pct"]
    with open(f"{folder}/contracts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    t = sum(r["tonnes"] for r in rows)
    v = sum(r["tonnes"] * r["rate_per_t"] for r in rows)
    live = [r for r in rows if r["window_end"] >= "2026-09-01"]
    print(f"{folder}/contracts.csv  {len(rows)} contracts  {t:,} t  "
          f"Rs {v / 1e7:,.1f} Cr over {years} years  ({len(live)} live today)  "
          f"no overlaps")


if __name__ == "__main__":
    for tenant in TEN:
        build(tenant)
