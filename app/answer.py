"""
Turning a metric result into something we are willing to send, or a refusal that is worth
reading.

The path is always the same:

    metric name + typed parameters
        -> definitions loaded for this tenant   (missing one? refuse)
        -> SQL built from a template in metrics.py
        -> checks run against the result        (any fail? refuse, and say which)
        -> a sentence rendered by filling named slots
        -> the egress gate                      (a numeral with no source? refuse to send)

The gate at the end is the structural version of "the model never produces a number". Every
figure that appears in the text has to be traceable to a value the query returned. Today the
wording is written by hand, so the gate never fires. It exists because the day someone wires
a language model into the wording, it will.
"""

import re

from . import db, definitions, metrics


# ---------------------------------------------------------------- formatting
def indian(x, dp=0):
    """1,63,82,446, not 163,824,466. Digits group in twos after the first three."""
    neg = float(x) < 0
    whole, _, frac = f"{abs(float(x)):.{dp}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    out = whole + (("." + frac) if frac else "")
    return ("-" + out) if neg else out


def crore(x):
    """A nine figure number is not something anybody can say out loud. Say it in crores."""
    v, a = float(x), abs(float(x))
    if a >= 1e7:
        return f"{indian(v / 1e7, 2).rstrip('0').rstrip('.')} Cr"
    if a >= 1e5:
        return f"{indian(v / 1e5, 2).rstrip('0').rstrip('.')} L"
    return indian(v, 0)


def rs(x):
    """The short form first, because that is the figure somebody repeats down the phone,
    and the exact rupees after it, because that is the figure that has to tie out."""
    a = abs(float(x))
    if a >= 1e5:
        return f"Rs {crore(x)} ({indian(x, 0)})"
    return f"Rs {indian(x, 0)}"


def t(x):
    """Tonnes, grouped the Indian way. 1,63,824 t reads correctly to the person here."""
    return indian(x, 1) + " t"


def rs2(x):
    return f"Rs {float(x):,.3f}"


def n(x):
    return indian(x, 0)


def plural(count, one, many=None):
    """One load, two loads. Getting this wrong on a screen a customer reads is small and it
    is the kind of small that makes somebody doubt the big numbers too."""
    return f"{count} {one if count == 1 else (many or one + 's')}"


class Answer(dict):
    """verdict is 'answered' or 'withheld'. Both carry text and the numbers behind it."""


def step(label, value, unit="", how=""):
    """One line of the arithmetic: what it is, what it came to, and where it came from."""
    return {"step": label, "value": value, "unit": unit, "detail": how}


def answered(text, numbers, detail=None, rows=None, head=None, sub=None, working=None):
    """head is the one figure the eye should land on first. text supports it.

    working is the derivation: how the rows the query returned became the figure on screen.
    The SQL panel proves what ran. This shows what was then done with it."""
    return Answer(verdict="answered", text=text, numbers=numbers, head=head, sub=sub,
                  detail=detail or [], rows=rows or [], working=working or [])


def withheld(text, reason, numbers=None, detail=None, rows=None, fix=None,
             head=None, sub=None, working=None):
    return Answer(verdict="withheld", text=text, reason=reason, numbers=numbers or {},
                  head=head, sub=sub, detail=detail or [], rows=rows or [], fix=fix,
                  working=working or [])


# ---------------------------------------------------------------- the gate
# A numeral only counts if it stands alone. Without the boundaries this matches the "25"
# inside FY24-25 and the "08" inside T-23-08, and the gate fires on every label in the
# product. Identifiers are not figures.
NUM = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w-])")

# A calendar label is not a measurement. "March 2027" names a month the same way T-23-08
# names a contract, and the year in it is not a figure anybody could get wrong by a tonne.
# The rule is deliberately narrow: a month name, a space, four digits. Nothing else is
# forgiven, and no other loophole exists.
DATE_LABEL = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\s+\d{4}\b")


def gate(ans):
    """Every numeral in the text must trace back to a value the query produced.

    Without this, wording is a place a number can appear from nowhere. With it, the worst a
    bad renderer can do is fail loudly."""
    allowed = set()
    for v in (ans.get("numbers") or {}).values():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        allowed |= {f"{f:,.0f}", f"{f:,.1f}", f"{f:,.2f}", f"{f:,.3f}",
                    f"{f:.0f}", f"{f:.1f}", f"{f:.2f}", f"{f:.3f}",
                    str(int(f)) if f == int(f) else ""}
        # and the Indian forms, because those are what actually get printed
        allowed |= {indian(f, 0), indian(f, 1), indian(f, 2), indian(f, 3)}
        for div in (1e5, 1e7):
            if abs(f) >= div:
                allowed |= {indian(f / div, 2).rstrip("0").rstrip("."),
                            indian(f / div, 1).rstrip("0").rstrip("."),
                            indian(f / div, 2)}
    for found in NUM.findall(DATE_LABEL.sub("", ans.get("text", ""))):
        clean = found.strip()
        if clean in allowed or clean.replace(",", "") in {a.replace(",", "") for a in allowed}:
            continue
        if len(clean.replace(",", "").replace(".", "")) <= 2:      # small counts, dates
            continue
        ans["gate_failed"] = (f"the figure {clean} in the reply does not trace to any query "
                              f"result, so this was not sent")
        ans["verdict"] = "withheld"
        ans["text"] = ("I produced a figure I cannot account for, so I have not sent the "
                       "answer. This is a bug in the wording, not in your data.")
    return ans


# ---------------------------------------------------------------- renderers
def r_open_commitment(r, p):
    if "error" in r:
        # a refusal with no headline is a blank card. Even "there is no such contract" is
        # something the eye has to land on.
        return withheld(
            f"{r['error']}. Nothing in this company's award file carries that reference, so "
            f"there is nothing to work out.",
            reason="no such contract",
            head="No such contract",
            sub="that reference is not in the award file",
            fix="Pick a contract from the list. Every one there came out of the awards.")
    nums = {k: v for k, v in r.items() if isinstance(v, (int, float))}
    # The percentage comes off the contract. Typing 25 into a sentence is how a figure
    # nobody checked ends up on a customer's screen, and these private contracts carry no
    # option clause at all.
    opt = (f" (including the {r['option_pct'] * 100:.0f} percent the buyer may add, which is "
           f"{t(r['option_t'])})" if r["option_applied"] and r["option_pct"] else "")
    if r["unattributed_loads"]:
        return withheld(
            f"I can tell you {t(r['dispatched_t'])} has gone out against {r['contract']} "
            f"across {r['loads']} loads, out of {t(r['contracted_t'])} contracted{opt}.\n\n"
            f"What I cannot tell you is the exact remainder. "
            f"{plural(r['unattributed_loads'], 'load')} totalling "
            f"{t(r['unattributed_t'])} went to "
            f"{r['plant']} inside this window with no contract written against them. "
            f"So what is left is somewhere between {t(r['remaining_min_t'])} and "
            f"{t(r['remaining_max_t'])}.",
            reason="loads with no contract written against them",
            numbers=nums, rows=r["blocked_rows"],
            head=f"{r['remaining_min_t']:,.0f} to {r['remaining_max_t']:,.0f} t",
            sub=f"still to deliver to {r['plant']}, and I cannot narrow it further",
            fix=f"Confirm which contract "
                f"{'that load belongs' if r['unattributed_loads'] == 1 else 'those loads belong'}"
                f" to and I will give you the exact figure.")
    body = (f"{t(r['remaining_max_t'])} still to deliver on {r['contract']}. "
            f"{t(r['dispatched_t'])} has gone out across {plural(r['loads'], 'load')} "
            f"against {t(r['awarded_t'])} awarded"
            + (f", plus {t(r['option_t'])} the buyer may still call for."
               if r["option_pct"] else "."))
    if r.get("only_option_left"):
        body += ("\n\nWorth noticing: everything awarded has already gone out. What is left "
                 "is the option clause and nothing else, so unless this buyer actually "
                 "calls for it, this contract is finished.")
    return answered(
        body, nums,
        working=[
            step("Contracted", r["contracted_t"], "tonnes",
                 "the tonnage on the award" + (", plus the option clause"
                                               if r["option_applied"]
                                               else ", option clause not counted")),
            step("Loads counted against it", r["loads"], "loads",
                 "rows carrying this contract reference"
                 + (f", of which {plural(r['placed_by_hand'], 'load')} carrying "
                    f"{indian(r['placed_by_hand_t'], 1)} t was placed here by a person "
                    f"rather than by the register" if r["placed_by_hand"] else "")),
            step("Dispatched", r["dispatched_t"], "tonnes", "sum of those loads"),
            step("Loads that could belong here and are unplaced", r["unattributed_loads"],
                 "loads", "none, so the subtraction is exact"),
            step("Still to deliver", r["remaining_max_t"], "tonnes",
                 f"{indian(r['contracted_t'], 1)} less {indian(r['dispatched_t'], 1)}"),
        ],
        head=t(r["remaining_max_t"]), sub=f"still to deliver to {r['plant']}")


def r_order_book(r, p):
    """The order book: what we have contracted to deliver, and how much is left.

    Contracted, not promised. A promise is something a vendor makes to us on the buying
    side. What a buyer has is a contract, and mixing the two words is how somebody reads
    an order book as though a supplier had already agreed to fill it.

    The option clause is the definition that moves this number, and it moves it a long
    way, so the answer says which way it was counted rather than leaving it to be guessed."""
    nums = {k: v for k, v in r.items() if isinstance(v, (int, float))}
    opt = ("counting the 25 percent the buyer may still add" if r["option_applied"]
           else "not counting the buyer's right to increase the order")
    # per month, with the products already added together. Sorting the product level rows
    # and taking the first gave one product's slice and called it the month.
    walls = r["walls"]
    soonest = walls[0] if walls else None
    if soonest:
        nums["soon_t"] = soonest["remaining"]

    working = [
        step("Live contracts", r["contracts"], "contracts",
             "award window has not closed yet"),
        step("Awarded", r["awarded_t"], "tonnes",
             "tonnage on the awards" + (", plus the option clause" if r["option_applied"]
                                        else ", option clause not counted")),
        step("Dispatched against them", r["delivered_t"], "tonnes",
             "loads in the register carrying one of those contract references"),
        step("Still owed", r["owed_t"], "tonnes",
             f"{indian(r['awarded_t'], 1)} less {indian(r['delivered_t'], 1)}"),
    ]
    if soonest:
        working.append(step(f"Of that, due by {_mon(soonest['month'])}",
                            soonest["remaining"], "tonnes",
                            f"{plural(soonest['contracts'], 'contract')} close that month, "
                            f"across {', '.join(soonest['grades'])}"))

    if r["unattributed_loads"]:
        nums["floor_t"] = max(0.0, r["owed_t"] - r["unattributed_t"])
        working.append(step("Tonnage on loads nobody has placed", r["unattributed_t"],
                            "tonnes",
                            f"{plural(r['unattributed_loads'], 'load')} left the yard with "
                            f"no contract written against "
                            f"{'it' if r['unattributed_loads'] == 1 else 'them'}, so it may "
                            f"already be inside the delivered figure or may not"))
        return withheld(
            f"Across {r['contracts']} live contracts the order book comes to "
            f"{t(r['owed_t'])} still owed, {opt}. "
            f"{t(r['delivered_t'])} of {t(r['awarded_t'])} awarded has already gone out.\n\n"
            f"What stops that being a fact is {plural(r['unattributed_loads'], 'load')} "
            f"totalling "
            f"{t(r['unattributed_t'])} that left the yard with no contract written against "
            f"them. Until somebody says which contract they were for, the true figure is "
            f"somewhere between {t(max(0, r['owed_t'] - r['unattributed_t']))} and "
            f"{t(r['owed_t'])}, so I am giving you the ceiling and telling you it is "
            f"a ceiling.",
            reason="loads with no contract written against them",
            numbers=nums, working=working, rows=r["book"][:20],
            head="up to " + t(r["owed_t"]),
            sub=f"still owed across {r['contracts']} live contracts, and that is a ceiling",
            fix=("Place that load and this becomes exact."
                 if r["unattributed_loads"] == 1
                 else f"Place those {r['unattributed_loads']} loads and this becomes exact."))

    return answered(
        f"{t(r['owed_t'])} still owed across {r['contracts']} live contracts, {opt}. "
        f"{t(r['delivered_t'])} of {t(r['awarded_t'])} awarded has already gone out.\n\n"
        + (f"The nearest wall is {_mon(soonest['month'])}, when "
           f"{plural(soonest['contracts'], 'contract')} close with "
           f"{t(soonest['remaining'])} still to deliver against "
           f"{'it' if soonest['contracts'] == 1 else 'them'}."
           if soonest else ""),
        nums, working=working, rows=r["book"][:20],
        head=t(r["owed_t"]),
        sub=f"still owed across {r['contracts']} live contracts")


def _mon(m):
    MON = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
    return f"{MON[int(m[5:7])]} {m[:4]}"


def r_capacity_free(r, p):
    """The question is when, so the answer is a month.

    Three states, not two. A month is oversold when what has to go out is more than the
    plant can make. It is full when the arithmetic leaves a positive number too small to
    sell. Only the rest is room."""
    months, free, tight, over = (r["months"], r["free_months"],
                                 r["tight_months"], r["oversold_months"])
    nums = {"total_free_t": r["total_free_t"], "pool": r["tender_pool_t"],
            "n_free": len(free), "n_tight": len(tight), "n_over": len(over),
            "n_months": len(months), "oversold_total": r["total_oversold_t"]}
    for m in months:
        nums["h_" + m["month"]] = abs(m["free_t"])
        nums["c_" + m["month"]] = m["scheduled_t"]
        nums["q_" + m["month"]] = m["required_t"]
        nums["k_" + m["month"]] = m["capacity_t"]
        nums["u_" + m["month"]] = m["used_pct"]

    # the headline is the answer to "when"
    if not free:
        head = "Nowhere"
        sub = (f"not one of the next {len(months)} months has room worth selling, once the "
               f"contracted draws and the pace the deadlines need are taken out")
    elif r["span"] == "every month":
        head = "Every month"
        sub = f"has room across the next {len(months)} months"
    elif r["span"]:
        head = _mon(free[0]["month"]) + (" onward" if r["span"].endswith("onward") else
                                         " to " + _mon(free[-1]["month"]))
        sub = f"is when you have room. {len(months) - len(free)} months before that are spoken for"
    else:
        # still a month, even when the free ones are not contiguous. A count answers a
        # different question from the one that was asked.
        head = _mon(free[0]["month"]) + " onward"
        sub = (f"is when the room starts, but {_mon(over[0]['month'])} is oversold and sits "
               f"in the middle of it" if over
               else f"is when the room starts, across {len(free)} of {len(months)} months")

    lines = []
    if over:
        w = max(over, key=lambda m: m["oversold_t"])
        lines.append(f"{_mon(w['month'])} is oversold by {t(w['oversold_t'])}. The plant has "
                     f"managed {t(w['capacity_t'])} in that month, and {t(w['scheduled_t'])} "
                     f"is contracted to private buyers while the tender deadlines need "
                     f"{t(w['required_t'])} to stay on pace.")
    if tight:
        lines.append(f"{len(tight)} more months are technically positive but full: "
                     f"{_mon(tight[0]['month'])} to {_mon(tight[-1]['month'])} run at "
                     f"{tight[0]['used_pct']:.0f} percent or more. There is a number in "
                     f"there but it is not tonnage anybody would sell.")
    if free:
        lines.append(f"Real room starts in {_mon(free[0]['month'])} and comes to "
                     f"{t(r['total_free_t'])} across {len(free)} months. That is what a new "
                     f"order could actually go into.")

    lines.append(f"The pace comes from {t(r['tender_pool_t'])} still owed on government "
                 f"tenders. Nobody promised any particular month, so it can be moved inside "
                 f"the window. What cannot move is the contracted monthly draw.")

    risk = r["at_risk"]
    if risk:
        nums["n_risk"] = len(risk)
        nums["risk_t"] = sum(x["shortfall_t"] for x in risk)
        who = ", ".join(x["plant"] for x in risk[:3])
        lines.append(f"{len(risk)} tenders do not close on the plant's own output: {who}"
                     f"{' and others' if len(risk) > 3 else ''}. Together they are "
                     f"{t(sum(x['shortfall_t'] for x in risk))} short of the room before "
                     f"their deadlines, which is tonnage that has to be bought in or given "
                     f"up.")

    working = [
        step("Months looked at", len(months), "months",
             f"from {_mon(months[0]['month'])}"),
        step("What the plant has managed, on average",
             sum(m["capacity_t"] for m in months) / max(1, len(months)), "tonnes a month",
             "from the production register, this tenant's basis"),
        step("Contracted to private buyers", sum(m["scheduled_t"] for m in months), "tonnes",
             "monthly draws written into those contracts. These cannot move"),
        step("Still owed on tenders", r["tender_pool_t"], "tonnes",
             "awarded less dispatched, on live contracts"),
        step("Which needs a pace of",
             max((m["required_t"] for m in months), default=0), "tonnes a month",
             "what has to go out every month to clear those deadlines on time"),
        step("Months with no room", len(over) + len(tight), "months",
             f"{len(over)} oversold, {len(tight)} full"),
        step("Room actually left", r["total_free_t"], "tonnes",
             f"across {len(free)} months, starting "
             f"{_mon(free[0]['month']) if free else 'nowhere'}"),
    ]
    return answered("\n\n".join(lines), nums, rows=months, working=working,
                    head=head, sub=sub)


def r_month_pressure(r, p):
    """One month, split into what is contracted for that month and what is only a pace.

    The distinction is the whole answer. A contracted draw cannot be moved without the
    buyer's agreement. A tender's pace can be moved freely as long as its deadline still
    holds. Reporting them as one number is what makes a month look unfixable when it is
    not, or fixable when it is not."""
    if r.get("unknown_month"):
        return withheld("That month is not in the planning window.", "month out of range")
    nums = {"cap": r["capacity_t"], "sched": r["scheduled_t"], "req": r["required_t"],
            "free": abs(r["free_t"]), "over": r["over_t"], "used": r["used_pct"],
            "movable": r["movable_t"], "pinned": r["pinned_t"]}

    lines = [f"{_mon(r['month'])} is running at {r['used_pct']:.0f} percent of what the "
             f"plant has managed in that month. {t(r['capacity_t'])} of capacity, "
             f"{t(r['scheduled_t'])} contracted to private buyers for this month, and "
             f"{t(r['required_t'])} of pace to keep the tender deadlines."]
    if r["over_t"] > 0:
        lines.append(f"That is {t(r['over_t'])} more than the plant can make.")

    if r["movable_t"] > 0:
        lines.append(f"{t(r['movable_t'])} of it can move. Those are tenders whose deadline "
                     f"is later than this month, so slowing them down costs nothing except "
                     f"a tighter month further out.")
    if r["pinned_t"] > 0:
        lines.append(f"{t(r['pinned_t'])} cannot. Those tenders are due this month or "
                     f"earlier, so the tonnage has to go out now or the deadline is missed.")
    if r["scheduled_t"] > 0:
        lines.append(f"The {t(r['scheduled_t'])} contracted to private buyers is owed for "
                     f"this month specifically, and missing it is a breach rather than a "
                     f"late delivery.")

    lines.append("What this cannot tell you is whether a private buyer would agree to a "
                 "changed schedule. No contract in these books records that, so the answer "
                 "stops here and the call is yours.")

    working = [
        step("What the plant has managed in this month", r["capacity_t"], "tonnes",
             "from the production register, on this tenant's basis"),
        step("Contracted to private buyers", r["scheduled_t"], "tonnes",
             "monthly draws written into those contracts"),
        step("Pace the tender deadlines need", r["required_t"], "tonnes",
             "what is still owed, spread over the months left in each window"),
        step("Spoken for in total", r["scheduled_t"] + r["required_t"], "tonnes",
             f"{indian(r['scheduled_t'], 1)} plus {indian(r['required_t'], 1)}"),
        step("Left over", r["free_t"], "tonnes",
             f"{indian(r['capacity_t'], 1)} less "
             f"{indian(r['scheduled_t'] + r['required_t'], 1)}"),
        step("Of that, movable", r["movable_t"], "tonnes",
             "tender pace whose deadline falls after this month"),
    ]
    over = r["over_t"] > 0
    return answered("\n\n".join(lines), nums,
                    rows=r["fixed_rows"] + r["movable"], working=working,
                    head=(t(r["movable_t"]) + " could move") if r["movable_t"] > 0
                         else (t(r["over_t"]) + " over") if over else t(r["free_t"]) + " free",
                    sub=(f"out of {t(r['scheduled_t'] + r['required_t'])} spoken for in "
                         f"{_mon(r['month'])}, which is oversold" if over
                         else f"in {_mon(r['month'])}, which is running at "
                              f"{r['used_pct']:.0f} percent of what the plant can make"))


def r_delivery_runway(r, p):
    """By when, not whether. The deadline is an output here, not an input."""
    if r.get("no_quantity"):
        return withheld("Tell me how many tonnes and I will tell you by when.",
                        "no quantity given", head="How many tonnes?",
                        sub="the quantity is the question, so I will not assume one")
    rows, want = r["rows"], r["tonnes"]
    nums = {"want": want, "room": r["total_room_t"], "dead": r["dead_months"],
            "short": max(0.0, want - r["total_room_t"])}
    for m in r["marks"]:
        nums["m_" + m["month"]] = m["tonnes"]

    if r["never"]:
        return answered(
            f"Not out of your own plant. Across the next {plural(len(rows), 'month')} the "
            f"room adds up to {t(r['total_room_t'])}, against the {t(want)} you are asking "
            f"about, so {t(nums['short'])} of it would have to be bought in "
            f"whatever date you promise.",
            nums, rows=rows, working=_runway_working(r),
            head="Not from the plant alone",
            sub=f"{t(r['total_room_t'])} of room in two years against an order of {t(want)}")

    ready = r["ready"]
    nums |= {"ready_t": ready["cumulative_t"], "part": ready["part_of_month"]}
    lines = [f"{t(want)} would be made by the end of {_mon(ready['month'])}, "
             f"{plural(ready['months_out'], 'month')} from now, if you start filling the "
             f"room as it comes."]
    if r["dead_months"]:
        lines.append(f"The first {plural(r['dead_months'], 'month')} "
                     f"{'contributes' if r['dead_months'] == 1 else 'contribute'} nothing "
                     f"at all, being oversold already, so the clock does not really start "
                     f"until {_mon(r['first_month_with_room'])}.")
    if r["marks"]:
        bits = [f"{t(m['tonnes'])} by {_mon(m['month'])}" for m in r["marks"]]
        lines.append("Read off the curve for any other date: " + ", ".join(bits) + ".")
    lines.append(f"That is the date to quote against, and it is the plant on its own. "
                 f"Anything you buy in moves it earlier.")

    return answered("\n\n".join(lines), nums, rows=rows, working=_runway_working(r),
                    head=_mon(ready["month"]),
                    sub=f"is when {t(want)} would be ready, {plural(ready['months_out'], 'month')} "
                        f"from now, out of the plant alone")


def _runway_working(r):
    rows = r["rows"]
    w = [step("The order", r["tonnes"], "tonnes", "what you are asking about"),
         step("Months with no room at all", r["dead_months"], "months",
              "already oversold once contracted draws and the tender pace are counted")]
    for m in r["marks"]:
        w.append(step(f"Made by {_mon(m['month'])}", m["tonnes"], "tonnes",
                      f"the room in the first {plural(m['months'], 'month')}, added up"))
    if r["ready"]:
        w.append(step("First month the total covers the order", r["ready"]["cumulative_t"],
                      "tonnes",
                      f"which happens during {_mon(r['ready']['month'])}, needing "
                      f"{indian(r['ready']['part_of_month'], 1)} t of that month's room"))
    else:
        w.append(step("Room in the whole window", r["total_room_t"], "tonnes",
                      "still short of the order, so no date works on the plant alone"))
    return w


def r_capacity_compare(r, p):
    if r.get("bad_params"):
        same = r.get("month_a") and r.get("month_a") == r.get("month_b")
        return withheld(
            ("Those are the same month, so there is nothing to compare. Pick the month that "
             "worries you and a month that does not."
             if same else "Pick two months and I will put them side by side."),
            reason="the same month twice" if same else "two months needed",
            head="Same month twice" if same else "Two months needed",
            sub=("comparing a month with itself has no answer" if same
                 else "this question needs two months to compare"),
            fix="Change one of the two months and ask again.")
    if r.get("no_history"):
        return withheld(
            "The production register has no history for one of those months, so there is "
            "nothing to compare it against.",
            reason="no production history for that month",
            head="No history", sub="the register has never recorded one of those months",
            fix="Pick a month the plant has actually run in.")
    A, B, a, b = r["a"], r["b"], _mon(r["month_a"]), _mon(r["month_b"])
    nums = {"a_avg": A["avg_t"], "b_avg": B["avg_t"], "gap": abs(r["gap_t"]),
            "a_best": A["best_t"], "a_worst": A["worst_t"],
            "b_best": B["best_t"], "b_worst": B["worst_t"],
            "a_years": A["years"], "b_years": B["years"],
            "a_plan": A["hit_plan_pct"], "b_plan": B["hit_plan_pct"],
            "a_feed": A["feed_per_t"], "b_feed": B["feed_per_t"],
            "gap_pct": abs(r["gap_pct"]) if r["gap_pct"] is not None else 0}
    lower, higher = (a, b) if A["avg_t"] < B["avg_t"] else (b, a)
    lo, hi = (A, B) if A["avg_t"] < B["avg_t"] else (B, A)
    txt = (f"Across {lo['years']} years the plant has averaged {t(lo['avg_t'])} in "
           f"{lower.split()[0]} and {t(hi['avg_t'])} in {higher.split()[0]}. That is "
           f"{t(abs(r['gap_t']))} less, or {abs(r['gap_pct']):.1f} percent.\n\n"
           f"It is not one bad year. {lower.split()[0]} has run between {t(lo['worst_t'])} "
           f"and {t(lo['best_t'])}, against {t(hi['worst_t'])} to {t(hi['best_t'])} in "
           f"{higher.split()[0]}, so the gap holds every year the register covers.\n\n"
           f"Against its own plan, {lower.split()[0]} came in at {lo['hit_plan_pct']:.0f} "
           f"percent and {higher.split()[0]} at {hi['hit_plan_pct']:.0f} percent. The plan "
           f"was already lower and the plant still fell further behind it.\n\n"
           f"What I cannot tell you is why. Nothing in these books records a breakdown, a "
           f"shift that did not turn up, or a wet fortnight. The pattern is real and it is "
           f"repeatable. The cause is in somebody's head, not in the data, and I am not "
           f"going to guess at it for you.")
    return answered(txt, nums, rows=A["rows"] + B["rows"],
                    working=[
                        step(f"Years the register holds for {lower.split()[0]}",
                             lo["years"], "years", "one row per year in the register"),
                        step(f"Average {lower.split()[0]}", lo["avg_t"], "tonnes",
                             f"between {indian(lo['worst_t'], 1)} and "
                             f"{indian(lo['best_t'], 1)}"),
                        step(f"Average {higher.split()[0]}", hi["avg_t"], "tonnes",
                             f"between {indian(hi['worst_t'], 1)} and "
                             f"{indian(hi['best_t'], 1)}"),
                        step("The gap", abs(r["gap_t"]), "tonnes",
                             f"{indian(hi['avg_t'], 1)} less {indian(lo['avg_t'], 1)}"),
                        step("The gap as a share of the bigger month", r["gap_pct"],
                             "percent",
                             f"{indian(abs(r['gap_t']), 1)} against "
                             f"{indian(r['gap_base_t'], 1)}. Measured against the larger "
                             f"month either way round, so the order you name them in does "
                             f"not change the answer"),
                        step(f"{lower.split()[0]} against its own plan",
                             lo["hit_plan_pct"], "percent",
                             "under plan as well as under the other month"
                             if lo["hit_plan_pct"] < 100 else
                             "it beat its own plan, so the plan was the pessimistic part"),
                        step("Why", 0, "",
                             "nothing in these books records a breakdown, a short shift or "
                             "a wet fortnight, so the cause is not derivable"),
                    ],
                    head=t(abs(r["gap_t"])) + " less",
                    sub=f"in {lower.split()[0]} than {higher.split()[0]}, every year the "
                        f"register covers")


def r_fit_new_tender(r, p):
    if r.get("unknown_month"):
        return withheld("That delivery month is not in the planning window.",
                        "month out of range")
    if not r.get("tonnes"):
        return withheld("Tell me how many tonnes and I will run it against the room in "
                        "every month up to the deadline.", "no quantity given",
                        head="How many tonnes?",
                        sub="the quantity is the question, so I will not assume one")
    if "free_t" not in r:
        return withheld("That did not run.", "incomplete result")

    nums = {"want": r["tonnes"], "free": r["free_t"], "short": r["shortfall_t"],
            "months": r["months_available"], "used": r["months_used"],
            "dry": r["months_dry"], "spare": r["spare_after_t"],
            "worst": r["worst_eats_pct"], "tight": r["tight_months"]}
    used = [f for f in r["fill"] if f["take_t"] > 0]
    for f in used:
        nums["f_" + f["month"]] = f["take_t"]
        nums["m_" + f["month"]] = f["room_t"]

    if not r["fits"]:
        # This is a complete answer to "how much can I take on". The plant can do 487.7 t
        # of the 3,000 and you are 2,512.3 short. Filing that as a refusal hides a usable
        # answer behind a data quality frame, and refusals are for numbers we cannot verify.
        return answered(
            f"{t(r['tonnes'])} does not fit. The "
            f"{plural(r['months_available'], 'month')} to "
            f"{_mon(r['by_month'])} have {t(r['free_t'])} of room left in total, once the "
            f"contracted draws and the pace your existing tenders need are taken out. That "
            f"leaves {t(r['shortfall_t'])} you would have to buy in or not bid for."
            + ("\n\n%d of those months %s no room at all."
               % (r["months_dry"], "has" if r["months_dry"] == 1 else "have")
               if r["months_dry"] else ""),
            nums, rows=used, working=_fit_working(r),
            head=(t(r["free_t"]) + " of it") if r["free_t"] > 0 else "None of it",
            sub=(f"is all the plant can take by {_mon(r['by_month'])}. You would be "
                 f"{t(r['shortfall_t'])} short of {t(r['tonnes'])}"))

    nums["x"] = r["headroom_x"]
    lines = [f"{t(r['tonnes'])} fits. Across the "
             f"{plural(r['months_available'], 'month')} to {_mon(r['by_month'])} there is "
             f"{t(r['free_t'])} of room, after everything already contracted and the pace "
             f"your existing tenders need. That is {r['headroom_x']:.1f} times what this "
             f"order asks for."]
    if r["comfortable"]:
        lines.append(f"There is no scheduling problem here. Even after taking it, "
                     f"{t(r['spare_after_t'])} is still free, so you can put the tonnage in "
                     f"whichever months suit you rather than the ones that happen to be "
                     f"next.")
    elif r["only_just"]:
        lines.append(f"But only just. {t(r['spare_after_t'])} would be left across the whole "
                     f"window, and {plural(r['tight_months'], 'month')} of the ones it comes "
                     f"out of would hand over everything they had. It fits on paper. One wet "
                     f"fortnight or one short shift and it does not.")
        if used:
            lines.append(f"Filled earliest first, {_mon(used[0]['month'])} gives up "
                         f"{t(used[0]['take_t'])} of its {t(used[0]['room_t'])}.")
    else:
        lines.append(f"It is not a squeeze, but it is not free either. "
                     f"{t(r['spare_after_t'])} would be left across the whole window.")
    if r["covered_by"]:
        nums["cov"] = 1
        lines.append(f"Delivering as early as you can, you would be clear of it by "
                     f"{_mon(r['covered_by'])}."
                     + (" The early months are the tight ones, so there is no need to."
                        if r["tight_months"] else ""))
    return answered("\n\n".join(lines), nums, rows=used, working=_fit_working(r),
                    head=("Fits comfortably" if r["comfortable"]
                          else "Fits, barely" if r["only_just"] else "Fits"),
                    sub=f"{t(r['tonnes'])} against {t(r['free_t'])} of room by "
                        f"{_mon(r['by_month'])}, which is {r['headroom_x']:.1f} times over")


def _fit_working(r):
    used = [f for f in r["fill"] if f["take_t"] > 0]
    w = [
        step("Months to the deadline", r["months_available"], "months",
             f"up to and including {_mon(r['by_month'])}"),
        step("Months with no room at all", r["months_dry"], "months",
             "already oversold once the contracted draws and the tender pace are counted"),
        step("Room left across the rest", r["free_t"], "tonnes",
             "what the plant can make, less everything already spoken for"),
        step("This order", r["tonnes"], "tonnes", "your input"),
    ]
    w.append(step("Shortfall", r["shortfall_t"], "tonnes",
                  f"{indian(r['tonnes'], 1)} wanted, {indian(r['free_t'], 1)} of room"))
    w.append(step("Room against the order", r["room_covers_pct"], "percent of the order",
                  f"{indian(r['free_t'], 1)} of room for an order of "
                  f"{indian(r['tonnes'], 1)}"))
    if used:
        w.append(step("Months it would be taken from", len(used), "months",
                      f"filled earliest first from {_mon(used[0]['month'])}, which is one "
                      f"way to place it and not the only one"))
    # What is left is the room less what was actually taken, and where the order did not
    # fit, what was taken is not what was asked for. Printing the asked for figure beside
    # a result it does not produce is how a derivation stops being one.
    taken = min(r["tonnes"], r["free_t"])
    w.append(step("Taken from that room", taken, "tonnes",
                  "all of it" if taken >= r["free_t"] else "as much as the order needed"))
    w.append(step("Left over afterwards", r["spare_after_t"], "tonnes",
                  f"{indian(r['free_t'], 1)} less {indian(taken, 1)}"))
    return w


def r_material_by_month(r, p):
    if not r["months"]:
        return withheld("No feedstock purchases with a known GCV.", "no data")
    c, d = r["cheapest_month"], r["dearest_month"]
    nums = {"cheap": c["best_cost_per_gcv"], "dear": d["best_cost_per_gcv"],
            "spread": r["spread_pct"], "energy": c["energy_gcal"], "tonnes": c["tonnes"],
            "best_t": c["best_tonnes"], "best_e": c["best_energy_gcal"],
            "mats": c["materials"]}
    for m in r["months"]:
        nums[f"c_{m['mm']}"] = m["best_cost_per_gcv"]
        nums[f"e_{m['mm']}"] = m["energy_gcal"]
    txt = (f"The cheapest energy of the year is {c['best_material']} in {c['month']}, at "
           f"{rs2(c['best_cost_per_gcv'])} per unit of GCV. The dearest is "
           f"{d['best_material']} in {d['month']} at {rs2(d['best_cost_per_gcv'])}, "
           f"{r['spread_pct']} percent higher for the same heat.\n\n"
           f"In {c['month']} the market put {t(c['best_tonnes'])} of "
           f"{c['best_material']} in front of us, which is {n(c['best_energy_gcal'])} Gcal "
           f"at that rate. The whole month brought {t(c['tonnes'])} across "
           f"{c['materials']} materials, but the rest of it did not come at this price.")
    working = [
        step("Months with feedstock purchases on record", len(r["months"]), "months",
             "grouped by the calendar month the material arrived in"),
        step("Materials priced", len(r["materials"]), "materials",
             "only those with a GCV recorded, because a rate alone is half a number"),
        step(f"Cheapest heat: {c['best_material']} in {c['month']}",
             c["best_cost_per_gcv"], "rupees per unit of GCV",
             "the lowest rate per unit of energy of any material in any month"),
        step(f"Dearest: {d['best_material']} in {d['month']}",
             d["best_cost_per_gcv"], "rupees per unit of GCV",
             "even the best material that month costs this much"),
        step("The spread between them", r["spread_pct"], "percent",
             "the dearest month costs that much more for the same heat"),
        step(f"{c['best_material']} that arrived in {c['month']}", c["best_tonnes"],
             "tonnes", "that material alone, in a normal year, not the whole month"),
        step("Energy in it", c["best_energy_gcal"], "Gcal",
             f"{indian(c['best_tonnes'], 1)} tonnes of {c['best_material']}"),
        step(f"Everything that arrived in {c['month']}", c["tonnes"], "tonnes",
             f"across {c['materials']} materials, which is a different and larger figure"),
    ]
    return answered(txt, nums, rows=r["cells"], working=working,
                    head=rs2(c["best_cost_per_gcv"]) + " / GCV",
                    sub=f"{c['best_material']}, {c['month']}. Your cheapest heat of the year")


def r_supply_outlook(r, p):
    """Three different situations, and only one of them is about trust.

    Nobody has promised anything. Somebody has promised and nobody has checked it. Somebody
    has promised and it is confirmed. Telling a man to go and confirm promises when there
    are no promises sends him to an empty screen and makes the product look broken."""
    own = sum(m["own_t"] for m in r["months"])
    if r.get("nothing_promised"):
        return answered(
            f"Nothing at all. Not one vendor has promised us anything over the next "
            f"{len(r['months'])} months, confirmed or otherwise, so the only material you "
            f"can count on is what the plant makes itself: {t(own)}.\n\n"
            f"That is a real answer rather than a missing one, and it is worth sitting "
            f"with. Every tonne you have contracted to a buyer over that period has to "
            f"come out "
            f"of your own production, because as things stand nothing is coming in.",
            {"own": own, "months": len(r["months"])},
            working=[
                step("Months looked at", len(r["months"]), "months",
                     "from this month forward"),
                step("Vendor promises falling in that window", 0, "promises",
                     "no email in the book promises anything for these months"),
                step("What the plant makes itself", own, "tonnes",
                     "the production register, on this tenant's basis"),
                step("Plus anything vendors have promised", 0, "tonnes",
                     "nothing, which is why the floor is your own output"),
            ],
            head=t(own), sub=f"all of it your own production. No vendor has promised "
                             f"anything for the next {len(r['months'])} months")
    if not r["any_confirmed"]:
        return withheld(
            f"{t(r['unconfirmed_t'])} has been promised by vendors over this window, and "
            f"every bit of it was read out of an email that nobody has since agreed was "
            f"read correctly. Planning a tender against that is planning against somebody "
            f"else's typing.",
            "no vendor promise has been confirmed by a person",
            numbers={"ceiling": r["ceiling_t"], "unconfirmed": r["unconfirmed_t"],
                     "own": own},
            working=[
                step("What the plant makes itself", own, "tonnes",
                     "this much is certain, whatever the vendors do"),
                step("Promised in emails", r["unconfirmed_t"], "tonnes",
                     "read out of vendor replies, none of it agreed by a person"),
                step("Confirmed by somebody", 0, "tonnes",
                     "which is why there is no floor to give you"),
            ],
            fix="Open the review queue and tick off the promises you recognise. The floor "
                "appears as soon as there is one you stand behind.",
            head="Not answerable yet",
            sub=f"{t(r['unconfirmed_t'])} is promised and none of it is confirmed")
    nums = {"floor": r["floor_t"], "ceiling": r["ceiling_t"], "firm": r["firm_t"],
            "unconfirmed": r["unconfirmed_t"], "expected": r["expected_t"]}
    txt = (f"Over the next {len(r['months'])} months the floor is {t(r['floor_t'])}: what "
           f"the plant makes itself plus {t(r['firm_t'])} a person has confirmed in "
           f"writing.\n\n"
           f"The ceiling is {t(r['ceiling_t'])}, which assumes every one of the "
           f"{t(r['unconfirmed_t'])} sitting in unconfirmed emails also lands. Discounted "
           f"by what each of those vendors has actually kept in the past, the middle case "
           f"is {t(r['expected_t'])}.\n\n"
           f"Plan against the floor. Quote against the middle. Never against the ceiling.")
    return answered(txt, nums, rows=r["months"],
                    head=t(r["floor_t"]) + " firm",
                    sub=f"with a ceiling of {t(r['ceiling_t'])} if every unconfirmed "
                        f"promise lands")


def _day(iso):
    MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
           "Nov", "Dec"]
    return f"{int(iso[8:10])} {MON[int(iso[5:7])]}"


def r_cash_calendar(r, p):
    nums = {"overdue": r["overdue_amount"], "window": r["in_window"],
            "total": r["total_open"], "later": r["later_amount"],
            "n_overdue": r["overdue_bills"]}
    soon = r["soonest"]
    lines = []
    if soon:
        nums["soon"] = soon["amount"]
        lines.append(f"The next money in is {rs(soon['amount'])}, due in the week of "
                     f"{_day(soon['from'])}.")
    lines.append(f"{rs(r['in_window'])} is due across the next {len(r['weeks'])} weeks, "
                 f"against {rs(r['total_open'])} open in total.")
    if r["overdue_amount"] > 1:
        lines.append(f"{rs(r['overdue_amount'])} across {r['overdue_bills']} bills is "
                     f"already past its due date and is not in any week below.")
    lines.append("Due dates come from each buyer's own terms, not from one house rule. "
                 "A bottling plant pays in fifteen days and a PSU in thirty, so the same "
                 "rupee of sales lands in different weeks.")
    working = [
        step("Bills still open", len(r["weeks"]) and r["overdue_bills"] +
             sum(w["bills"] for w in r["weeks"]), "bills",
             "sales vouchers with money still against them, after receipts are applied"),
        step("Receipts that matched no bill", r["unapplied_receipts"], "rupees",
             f"a receipt names no bill, so this tenant clears the "
             f"{'oldest' if r['apply_receipts'] == 'fifo' else 'newest'} first, and this "
             f"is what was left over after doing so"),
        step("Total still owed", r["total_open"], "rupees",
             "billed less credited less received, across every buyer"),
        step("Already past its due date", r["overdue_amount"], "rupees",
             f"{r['overdue_bills']} bills, each judged on its own buyer's terms"),
        step(f"Due in the next {len(r['weeks'])} weeks", r["in_window"], "rupees",
             "bill date plus that buyer's payment days, bucketed by week"),
        step("Due after that", r["later_amount"], "rupees",
             "falls outside the window you asked about"),
    ]
    return answered("\n\n".join(lines), nums, rows=r["weeks"], working=working,
                    head="Rs " + crore(r["in_window"]),
                    sub=f"due over the next {len(r['weeks'])} weeks, by each buyer's own "
                        f"payment terms")


def r_material_cost(r, p):
    if not r["rows"]:
        return withheld("No feedstock purchases found.", "no data")
    nums = {}
    lines = []
    for m in r["rows"]:
        nums[f"t_{m['material']}"] = m["rate_per_t"]
        nums[f"g_{m['material']}"] = m["cost_per_gcv"]
        lines.append(f"{m['material']}: {rs(m['rate_per_t'])} a tonne, "
                     f"{rs2(m['cost_per_gcv'])} per GCV")
    note = ""
    if r["cheapest_energy"] != r["cheapest_per_tonne"]:
        note = (f"\n\nWorth noticing: {r['cheapest_per_tonne']} is cheaper per tonne, but "
                f"{r['cheapest_energy']} is cheaper per unit of energy, and energy is what "
                f"you get paid on.")
    best = r["rows"][0]
    working = [
        step("Materials bought", len(r["rows"]), "materials",
             "feedstock purchases grouped by what the item master calls them"),
        step("Cheapest per tonne", 0, "",
             f"{r['cheapest_per_tonne']}"
             + (", which is a different material from the cheapest per unit of energy"
                if r["cheapest_per_tonne"] != r["cheapest_energy"]
                else ", the same material, so both measures agree here")),
        step("Rate for the cheapest energy", best["rate_per_t"], "rupees a tonne",
             f"{best['material']}, averaged over {best['n']} purchases"),
        step("Its calorific value", best["gcv"], "GCV",
             "from the item master, not from the product code"),
        step("Cost of one unit of energy", best["cost_per_gcv"], "rupees per GCV",
             f"{indian(best['rate_per_t'], 0)} divided by {indian(best['gcv'], 0)}"),
    ]
    return answered("\n  ".join([""] + lines).strip() + note, nums, rows=r["rows"],
                    working=working,
                    head=f"Rs {best['cost_per_gcv']:.3f}",
                    sub=f"per GCV buying {best['material']}, the cheapest energy on the list")


def r_production_cost(r, p):
    nums = {"cheap": r["cheapest"]["cost_per_gcv"], "dear": r["dearest"]["cost_per_gcv"],
            "cheap_t": r["cheapest"]["cost_per_t"], "dear_t": r["dearest"]["cost_per_t"],
            "gcv": r["gcv_typical"], "worst": r["cheapest"]["cost_per_gcv_worst"]}
    return answered(
        f"Making {r['grade']} at {n(r['gcv_typical'])} GCV:\n\n"
        f"  cheapest month is {r['cheapest']['month']}, "
        f"{rs(r['cheapest']['cost_per_t'])} a tonne, {rs2(r['cheapest']['cost_per_gcv'])} per GCV\n"
        f"  dearest is {r['dearest']['month']}, "
        f"{rs(r['dearest']['cost_per_t'])} a tonne, {rs2(r['dearest']['cost_per_gcv'])} per GCV\n\n"
        f"If the material comes in at the bottom of its range instead, the cheapest month "
        f"costs {rs2(r['cheapest']['cost_per_gcv_worst'])} per GCV.", nums, rows=r["rows"],
        working=[
            step("Cheapest month for feedstock", r["cheapest"]["feed_rate_per_t"],
                 "rupees a tonne of residue", f"{r['cheapest']['month']}, averaged over "
                 f"{r['cheapest']['n']} purchases in that calendar month"),
            step("Residue needed for a tonne of pellets", r["feed_per_pellet"], "tonnes",
                 "from the plant's own config, not from a constant in the code"),
            step("Feedstock in a tonne of product",
                 r["cheapest"]["feed_cost_per_t"], "rupees",
                 f"{indian(r['cheapest']['feed_rate_per_t'], 0)} times "
                 f"{r['feed_per_pellet']}"),
            step("Conversion and overhead", r["conversion_cost"], "rupees a tonne",
                 "from the plant's own config"),
            step("Cost to make a tonne", r["cheapest"]["cost_per_t"], "rupees",
                 f"{indian(r['cheapest']['feed_cost_per_t'], 0)} plus "
                 f"{indian(r['conversion_cost'], 0)}"),
            step("What that tonne is worth in energy", r["gcv_typical"], "GCV",
                 f"{r['grade']} on this recipe"),
            step("Cost of one unit of energy", r["cheapest"]["cost_per_gcv"],
                 "rupees per GCV",
                 f"{indian(r['cheapest']['cost_per_t'], 0)} divided by "
                 f"{indian(r['gcv_typical'], 0)}"),
        ],
        head=f"Rs {r['cheapest']['cost_per_gcv']:.3f}",
        sub=f"per GCV if you run in {r['cheapest']['month']}, the cheapest month")


def r_quote(r, p):
    if r.get("missing_config"):
        return withheld(
            "The plant's own working figures are not in the database, so I cannot build a "
            "cost from first principles. I am not going to substitute a plausible constant "
            "for them, because a quote built on a guessed conversion cost is exactly the "
            "kind of number that loses money quietly.",
            reason="missing config: " + ", ".join(r["missing_config"] or []),
            head="Cannot cost it", sub="the plant's own figures are not recorded",
            fix="Load config.csv for this tenant, then ask again.")
    if r.get("no_such_grade"):
        return withheld("No such product in the item master.", "unknown product")
    if r.get("quoted_above_product"):
        # The answer's own warning is that quoting high and delivering low is not a
        # rounding error. Quoting above what the product tests at is that, on purpose.
        return withheld(
            f"{r['grade']} runs at {n(r['product_gcv'])} GCV and you are asking me to quote "
            f"it at {n(r['quoted_gcv'])}. That is not a bid, it is a shortfall you are "
            f"planning in advance: every load would land under the figure on the contract "
            f"and the deduction would follow.\n\n"
            f"If the product really does test higher than the item master says, change the "
            f"master. If it does not, quote what it makes.",
            reason=f"quoted GCV is above what {r['grade']} tests at",
            numbers={"quoted": r["quoted_gcv"], "product": r["product_gcv"],
                     "over": r["quoted_gcv"] - r["product_gcv"]},
            head="Above what it tests at",
            sub=f"{r['grade']} runs at {n(r['product_gcv'])} GCV, and you asked for "
                f"{n(r['quoted_gcv'])}",
            fix=f"Quote at or below {n(r['product_gcv'])} GCV, or correct the item master.")
    if r.get("gcv_out_of_range"):
        return withheld(
            f"{n(r['quoted_gcv'])} GCV is not a number you can bid at. A load under "
            f"{n(r['floor'])} is rejected outright, and nothing in this trade runs above "
            f"{n(r['ceiling'])}. I would rather stop here than hand you a rate per tonne "
            f"built on a figure somebody mistyped.",
            reason="the quoted GCV is outside the range this trade works in",
            numbers={"gcv": r["quoted_gcv"], "floor": r["floor"], "ceiling": r["ceiling"]},
            head="Not a biddable GCV",
            sub=f"{n(r['quoted_gcv'])} is outside {n(r['floor'])} to {n(r['ceiling'])}",
            fix="Quote a GCV your product actually tests at and ask again.")
    if r.get("negative_margin"):
        return withheld("A negative margin is not a quote, it is a decision to lose money. "
                        "If that is deliberate, say so somewhere other than here.",
                        reason="negative margin",
                        head="Negative margin", sub="that is not a quote",
                        fix="Give a margin of zero or more.")
    if r.get("no_history_for_window"):
        return withheld("There are no purchases on record for any month in that delivery "
                        "window, so there is no rate to cost against.",
                        "no purchase history for those months",
                        head="No history", sub="for the months you would be producing in")

    nums = {"quote_per_t": r["quote_per_t"], "quote_per_gcv": r["quote_per_gcv"],
            "cost_per_gcv": r["cost_per_gcv"], "cost_per_t": r["cost_per_t"],
            "margin": r["margin_per_gcv"], "quoted_gcv": r["quoted_gcv"],
            "months": r["months"], "product_gcv": r["product_gcv"],
            "feed": r["feed_rate_per_t"], "ratio": r["feed_per_pellet"],
            "conv": r["conversion_cost"], "swing": r["swing_per_t"],
            "best": r["best_cost_per_t"], "worst": r["worst_cost_per_t"],
            "below": r["if_below_floor"], "test": r["gcv_test"],
            "per_step": r["per_step_gcv"], "step": r["gcv_step"],
            "floor": r["gcv_floor"],
            "reject": r["gcv_reject"],
            "best_feed": r["best_feed_rate"], "worst_feed": r["worst_feed_rate"],
            "feed_in_a_tonne": r["feed_in_a_tonne"]}
    for w in r["working"]:
        nums["w_" + w["step"][:24]] = w["value"]

    # The steps go in the audit trail and the picture. Repeating them here as eleven
    # numbered lines made the answer a wall of text and said nothing twice.
    nums |= {"feed_share": r["feed_share"], "conv_share": r["conv_share"],
             "margin_share": r["margin_share"]}
    txt = (f"{rs(r['quote_per_t'])} a tonne at {n(r['quoted_gcv'])} GCV, which is "
           f"{rs2(r['quote_per_gcv'])} per unit of energy. That is "
           f"{rs(r['cost_per_t'])} to make it, averaged over the "
           f"{plural(r['months'], 'month')} you would be producing in, plus the "
           f"{rs2(r['margin_per_gcv'])} of margin you asked for.\n\n"
           f"Shift the delivery window and this moves. Your cheapest month in it costs "
           f"{rs(r['best_cost_per_t'])} a tonne to make and your dearest "
           f"{rs(r['worst_cost_per_t'])}, a swing of {rs(r['swing_per_t'])}. A quote is a "
           f"property of the months you produce in, not of the product.\n\n"
           f"Two things to hold on to before you bid. Every {n(r['gcv_step'])} GCV you "
           f"quote is worth {rs(r['per_step_gcv'])} a tonne, so quoting high and delivering "
           f"low is not a rounding error. And if a load lands at {n(r['gcv_test'])} GCV, "
           f"under the {n(r['gcv_floor'])} floor, this same quote pays "
           f"{rs(r['if_below_floor'])} a tonne rather than {rs(r['quote_per_t'])}. Below "
           f"{n(r['gcv_reject'])} it pays nothing at all.")

    return answered(txt, nums, rows=r["window"], working=r["working"],
                    head="Rs " + indian(r["quote_per_t"], 0) + " a tonne",
                    sub=f"at {n(r['quoted_gcv'])} GCV, which is "
                        f"Rs {r['quote_per_gcv']:.3f} per unit of GCV, for delivery across "
                        f"{r['months']} months from {_mon(r['from'])}")


def r_buy_in(r, p):
    """Make or buy, answered in rupees.

    Rates per unit of GCV are the only fair comparison, because a bought-in pellet does not
    carry the same energy as ours. But a rate is not a decision. What the decision was worth
    is the money, so the energy actually bought is priced both ways and the difference is
    the headline."""
    if r.get("no_such_grade"):
        return withheld("No such product in the item master.", "unknown product")
    if r.get("missing_config"):
        return withheld("The plant's own working figures are not recorded, so I cannot "
                        "compare buying against making.",
                        "missing config: " + ", ".join(r["missing_config"]),
                        head="Cannot cost it",
                        sub="the conversion ratio and cost are not in the config",
                        fix="Load config.csv for this tenant, then ask again.")
    if r.get("no_gcv"):
        return withheld("Bought-in pellets have no GCV recorded, so there is no rate per "
                        "unit of energy to compare. A price without a GCV is half a number.",
                        "no GCV on bought-in pellets",
                        head="Cannot compare", sub="a rate per tonne alone is not a price",
                        fix="Record the GCV on the bought-in pellet item and ask again.")
    if r.get("never_bought"):
        return withheld("We have never bought a finished pellet in these books, so there is "
                        "nothing to price against making it.", "no bought-in purchases",
                        head="Never bought in",
                        sub="every tonne here was made in the plant",
                        fix="This becomes answerable the first time a finished pellet is "
                            "purchased.")

    c, d = r["cheapest"], r["dearest"]
    extra = r["extra_spent"]
    per_t_made = r["make_cheapest_per_t"]
    nums = {"tonnes": r["tonnes"], "gcv": r["gcv"], "own_gcv": r["own_gcv"],
            "cheap": c["cost_per_gcv"], "cheap_t": c["rate_per_t"],
            "dear": d["cost_per_gcv"], "dear_t": d["rate_per_t"],
            "make_cheap_t": r["make_cheapest_per_t"],
            "make_dear_t": r["make_dearest_per_t"],
            "own_cheap": r["own_cheapest"]["cost_per_gcv"],
            "own_dear": r["own_dearest"]["cost_per_gcv"],
            "spent": r["spent"], "would": r["would_have_cost_to_make"],
            "extra": abs(extra), "energy": r["energy_gcal"],
            "wins": r["months_cheaper_to_buy"], "seen": r["months_seen"],
            "n_vendors": len(r["vendors"]), "ratio": r["feed_per_pellet"],
            "conv": r["conversion_cost"]}

    lines = [
        f"Buying: {r['tonnes']:,.1f} t came in across "
        f"{plural(r['months_seen'], 'month')} from "
        f"{plural(len(r['vendors']), 'vendor')}, between {rs(c['rate_per_t'])} and "
        f"{rs(d['rate_per_t'])} a tonne, at {n(r['gcv'])} GCV. That cost {rs(r['spent'])}.",

        f"Making: the same product costs between {rs(r['make_cheapest_per_t'])} and "
        f"{rs(r['make_dearest_per_t'])} a tonne to make, at {n(r['own_gcv'])} GCV. "
        f"Residue at the month's rate, times {r['feed_per_pellet']}, plus "
        f"{rs(r['conversion_cost'])} of conversion.",

        f"The two tonnes are not the same tonne, because theirs carries {n(r['gcv'])} GCV "
        f"and ours {n(r['own_gcv'])}. So the fair comparison is the energy. The "
        f"{n(r['energy_gcal'])} Gcal you bought would have cost "
        f"{rs(r['would_have_cost_to_make'])} to make here.",
    ]
    if extra > 0:
        lines.append(f"So buying it in cost {rs(extra)} more than making it would have. "
                     f"That is the answer, and it is the same conclusion in every one of "
                     f"the {plural(r['months_seen'], 'month')} you bought in.")
    else:
        b = r["best_buy"]
        nums["b_buy"] = b["buy_per_gcv"]
        nums["b_make"] = b["make_per_gcv"]
        nums["b_t"] = b["tonnes"]
        nums["b_gap"] = b["gap"]
        lines.append(f"So buying it in saved {rs(abs(extra))} against making it. "
                     f"The best month was {b['month']}, from {', '.join(b['vendors'])}, at "
                     f"{rs2(b['buy_per_gcv'])} per unit of GCV against "
                     f"{rs2(b['make_per_gcv'])} to make it, on {t(b['tonnes'])}.")

    lines.append("Two things this does not know. A bought-in pellet carries the producer's "
                 "GCV, not yours, and if the tested figure comes in under what you quoted "
                 "the penalty is yours. And nothing here records whether a vendor could "
                 "have supplied more than he did, so a cheap month is not a purchasing "
                 "plan.")

    working = [
        step("Tonnage bought in", r["tonnes"], "tonnes",
             f"{sum(b['lots'] for b in r['rows'])} lots from "
             f"{plural(len(r['vendors']), 'vendor')}"),
        step("What we paid for it", r["spent"], "rupees",
             f"between {indian(c['rate_per_t'], 0)} and {indian(d['rate_per_t'], 0)} "
             f"a tonne"),
        step("Energy that tonnage carries", r["energy_gcal"], "Gcal",
             f"{indian(r['tonnes'], 1)} tonnes at {indian(r['gcv'], 0)} GCV"),
        step("Cost to make a tonne here, cheapest month", r["make_cheapest_per_t"],
             "rupees a tonne",
             f"residue at that month's rate times {r['feed_per_pellet']}, plus "
             f"{indian(r['conversion_cost'], 0)} conversion"),
        step("Which is, per unit of energy", r["own_cheapest"]["cost_per_gcv"],
             "rupees per GCV",
             f"{indian(r['make_cheapest_per_t'], 0)} divided by {indian(r['own_gcv'], 0)} GCV"),
        step("Cost of that same energy, made here", r["would_have_cost_to_make"], "rupees",
             "each month's own make cost applied to the energy bought that month"),
        step("Difference", abs(extra), "rupees",
             f"{indian(r['spent'], 0)} paid against "
             f"{indian(r['would_have_cost_to_make'], 0)} to make. "
             + ("Buying cost more." if extra > 0 else "Buying cost less.")),
    ]

    if extra > 0:
        head = "Rs " + crore(extra) + " lost"
        sub = (f"by buying {t(r['tonnes'])} in rather than making it. Making wins in every "
               f"month you bought")
    else:
        head = "Rs " + crore(abs(extra)) + " saved"
        sub = f"by buying {t(r['tonnes'])} in rather than making it"
    return answered("\n\n".join(lines), nums, rows=r["rows"], working=working,
                    head=head, sub=sub)


def r_vendor_reliability(r, p):
    if r.get("not_extracted"):
        return withheld(
            "I cannot tell you that yet. What each vendor promised only exists in the email "
            "threads, and nothing has been extracted and confirmed from them.",
            reason="vendor commitments have not been read out of the mail",
            head="still in the mail",
            sub="what each vendor promised has not been extracted and confirmed yet",
            fix="Run the extraction, then confirm the proposals in the review queue.")
    if r.get("unconfirmed_only"):
        return withheld(
            f"{r['extracted']} promises have been read out of the vendor emails and "
            f"nobody has agreed that any of them were read correctly. A reliability score "
            f"built on that is a guess with a percentage sign on it, so I am not going to "
            f"give you one.",
            reason="no vendor promise has been confirmed by a person",
            numbers={"extracted": r["extracted"]},
            head="Nothing confirmed yet",
            sub=f"{r['extracted']} promises read out of the mail, none of them agreed",
            fix="Open the review queue and tick off the promises you recognise. A score "
                "appears for each vendor once there are enough of them to mean something.")
    nums = {"n": len(r["rows"]), "min": r["min_observations"]}
    return answered(f"{len(r['rows'])} vendors with a delivery record. Anyone with fewer than "
                    f"{r['min_observations']} commitments is left out, because a rate from two "
                    f"or three deliveries is an accident rather than a rate.",
                    nums, rows=r["rows"])


def r_vendor_capacity(r, p):
    nums = {"best": r["best_month_t"], "months": r["months_traded"]}
    if not r["months_traded"]:
        # A vendor we have never bought from is a different answer from a vendor whose
        # ceiling nobody wrote down. Telling the second story about the first one reads as
        # a bug, because it is one.
        return withheld(
            f"We have never bought anything from {r['vendor']}. There is no delivery "
            f"history to reason from, so I have nothing to tell you about what he could "
            f"supply. That is not a limit of the data, it is that there is no relationship "
            f"here to measure.",
            reason="no trading history with this vendor at all",
            numbers=nums, head="Never traded with him",
            sub=f"not one load from {r['vendor']} appears in the goods receipts",
            fix="If he has quoted you, record the quantity he offered against his name and "
                "the question becomes answerable from the first load.")
    return withheld(
        f"Nobody ever recorded it. We only know what we bought from {r['vendor']}, which is a "
        f"floor on what he could supply, never a ceiling. The most he has ever sent in a "
        f"month is {t(r['best_month_t'])}, across {r['months_traded']} months of trading, and "
        f"he may well have had more available every single time.\n\n"
        f"And when he has delivered short, nothing in the data separates \"he could not\" from "
        f"\"he sold it to someone paying more\".",
        reason="never recorded", numbers=nums,
        head="never recorded",
        sub=f"the most {r['vendor']} has ever sent in a month is "
            f"{t(r['best_month_t'])}, and that is a floor, not a ceiling",
        fix="Ask each vendor his capacity for the season and record it against the commitment. "
            "One field, and this becomes arithmetic.")


def r_realised(r, p):
    nums = {"per_t": r["per_tonne"], "billed": r["billed"], "ded": r["deducted"],
            "t": r["tonnes"], "inv": r["invoices"]}
    if r["tonnes"] <= 0:
        traded = r.get("traded") or []
        if traded:
            best = max(traded, key=lambda x: x["tonnes"])
            years = ", ".join(x["fy"] for x in traded)
            return withheld(
                f"Nothing went to {r['plant']} in {r['fy']}, so there is no realised price "
                f"to give you. That is not a gap in the data. A buyer runs one contract at "
                f"a time and does not win every year.\n\n"
                f"{r['plant']} did trade in {years}. The biggest was {best['fy']} at "
                f"{t(best['tonnes'])}.",
                reason=f"{r['plant']} had no contract running in {r['fy']}",
                numbers={"n_years": len(traded), "best_t": best["tonnes"]},
                head="No contract that year",
                sub=f"{r['plant']} traded in {years}",
                fix=f"Ask the same question for {best['fy']}.")
        return withheld(
            f"Nothing has ever gone to {r['plant']} in these books, so there is no realised "
            f"price to give you for any year.",
            reason="no dispatches to that plant at all",
            head="Never traded", sub=f"no load in the register has ever gone to {r['plant']}")
    net = r["net_of_recoveries"]
    basis = ("after quality deductions, over tonnes accepted" if net
             else "as invoiced, before deductions, over tonnes dispatched")
    over = "accepted" if net else "dispatched"
    value = (float(r["billed"]) - float(r["deducted"])) if net else float(r["billed"])

    # The denominator is the same tonnage dispatch_total will not publish when the register
    # and the books disagree about it. Publishing a price built on it here, while the other
    # screen refuses the tonnage itself, is two answers to one question.
    if r["tonnage_disputed"]:
        confirmed = float(r["tonnes"]) - float(r["uninvoiced_t"])
        lo = value / float(r["tonnes"]) if r["tonnes"] else 0
        hi = value / confirmed if confirmed > 0 else lo
        lo, hi = min(lo, hi), max(lo, hi)
        why = []
        if r["reg_loads"] != r["book_vouchers"]:
            why.append(f"the register counts {plural(r['reg_loads'], 'load')} and the books "
                       f"hold {plural(r['book_vouchers'], 'sales voucher')}")
        if r["uninvoiced_loads"]:
            why.append(f"{plural(r['uninvoiced_loads'], 'load')} carrying "
                       f"{t(r['uninvoiced_t'])} left with no invoice raised against "
                       f"{'it' if r['uninvoiced_loads'] == 1 else 'them'}")
        return withheld(
            f"Somewhere between {rs(lo)} and {rs(hi)} a tonne on {r['plant']} in "
            f"{r['fy']}, and I will not narrow it further.\n\n"
            f"{rs(r['billed'])} was billed and {t(r['tonnes'])} is what the dispatch "
            f"register says went out. The trouble is the two do not describe the same "
            f"loads: {' and '.join(why)}. Divide one by the other and you get a rate per "
            f"tonne that is confident and wrong by whatever that gap is worth.\n\n"
            f"The same tonnage is refused on the dispatch question for the same reason. "
            f"It would not be much of a rule if it applied on one screen and not the next.",
            reason="the tonnage this would divide by is itself disputed",
            numbers={"lo": lo, "hi": hi, "billed": r["billed"], "ded": r["deducted"],
                     "t": r["tonnes"], "conf": confirmed, "inv": r["invoices"],
                     "reg": r["reg_loads"], "vou": r["book_vouchers"],
                     "unt": r["uninvoiced_t"]},
            working=[
                step("Billed", r["billed"], "rupees",
                     f"{plural(r['invoices'], 'sales voucher')} for this plant and year"),
                step("Quality deductions", r["deducted"], "rupees",
                     "credit notes raised for GCV shortfall"),
                step("Loads in the dispatch register", r["reg_loads"], "loads",
                     "what physically went out"),
                step("Sales vouchers in the books", r["book_vouchers"], "vouchers",
                     "which is a different count, and that is the problem"),
                step("Tonnage the register claims", r["tonnes"], "tonnes",
                     "all of it, invoiced or not"),
                step("Tonnage with an invoice behind it", confirmed, "tonnes",
                     f"{indian(r['tonnes'], 1)} less {indian(r['uninvoiced_t'], 1)}"),
                step("So the rate is somewhere between", lo, "rupees a tonne",
                     f"and {indian(hi, 0)}, depending which tonnage is the right one"),
            ],
            head=f"Rs {indian(lo, 0)} to {indian(hi, 0)}",
            sub=f"a tonne on {r['plant']} in {r['fy']}, and the tonnage underneath it is "
                f"disputed",
            fix="Reconcile the dispatch register against the sales vouchers for this buyer "
                "and year. One load either has an invoice or it does not.")
    return answered(
        f"{rs(r['per_tonne'])} a tonne on {r['plant']} in {r['fy']}, {basis}.\n\n"
        f"{rs(r['billed'])} billed across {r['invoices']} vouchers, "
        f"{rs(r['deducted'])} raised as quality deductions, on {t(r['tonnes'])} "
        f"{over}." + ("" if net else " This tenant's definition counts the invoice, so "
                      "those deductions are not taken off the figure above."), nums,
        # The SQL panel proves what ran. This is what was then done with the rows, which is
        # where the mistakes actually live.
        working=[
            step("Sales vouchers for this plant and year", r["invoices"], "vouchers",
                 "one row per bill raised"),
            step("Billed", r["billed"], "rupees", "sum of those vouchers"),
            step("Quality deductions", r["deducted"], "rupees",
                 "credit notes raised against them, for GCV shortfall"),
        ] + ([step("Money actually due", float(r["billed"]) - float(r["deducted"]),
                   "rupees",
                   f"{indian(r['billed'], 0)} less {indian(r['deducted'], 0)}")]
             if net else []) + [
            step("Tonnes " + over, r["tonnes"], "tonnes",
                 "from the dispatch register, on this tenant's definition"),
            step("What we got per tonne" if net else "What we invoiced per tonne",
                 r["per_tonne"], "rupees a tonne",
                 f"{indian(float(r['billed']) - float(r['deducted']) if r['net_of_recoveries'] else r['billed'], 0)}"
                 f" divided by {indian(r['tonnes'], 1)}"),
        ],
        head=rs(r["per_tonne"]),
        sub=(f"a tonne actually received on {r['plant']}, {r['fy']}" if net
             else f"a tonne invoiced on {r['plant']}, {r['fy']}, before quality deductions"))


def r_outstanding(r, p):
    nums = {"total": r["total"], "n": len(r["rows"])}
    top = r["rows"][:5]
    lines = [f"{x['party']}: {rs(x['outstanding'])}" for x in top]
    for x in top:
        nums[f"o_{x['party']}"] = x["outstanding"]
    adv = (" Advances received have been netted off." if r["net_advances"]
           else " Advances received are kept separate from this.")
    biggest = top[0] if top else None
    return answered(f"{rs(r['total'])} outstanding across {len(r['rows'])} customers.{adv}\n\n  "
                    + "\n  ".join(lines), nums, rows=r["rows"],
                    working=[
                        step("Billed", r["billed"], "rupees",
                             "every Sales voucher in the books"),
                        step("Credit notes raised", r["credited"], "rupees",
                             "quality deductions against those bills"),
                        step("Received", r["received"], "rupees",
                             "money that actually came in"),
                        step("Still owed", r["total"], "rupees",
                             f"{indian(r['billed'], 0)} less {indian(r['credited'], 0)} "
                             f"less {indian(r['received'], 0)}"),
                        step("Customers it is spread across", r["customers"], "customers",
                             "parties where more than a rupee is left"),
                        step("Largest single debt",
                             biggest["outstanding"] if biggest else 0, "rupees",
                             biggest["party"] if biggest else "nobody owes anything"),
                    ],
                    head="Rs " + crore(r["total"]), sub=f"owed to us across {len(r['rows'])} customers")


def r_channel_split(r, p):
    nums = {"feed": r["feedstock_t"], "fin": r["finished_t"],
            "unk": r["unknown_t"], "unk_n": r["unknown_n"]}
    if r["unknown_n"]:
        lo = r["finished_t"]
        hi = r["finished_t"] + r["unknown_t"]
        nums |= {"lo": lo, "hi": hi}
        return withheld(
            f"I cannot split that cleanly. {r['unknown_n']} purchases in {r['fy']}, "
            f"{t(r['unknown_t'])} in total, could be either raw material or bought-in "
            f"pellets. The stock item is a generic group, the narration says nothing useful, "
            f"and the rate falls between the two bands.\n\n"
            f"So bought-in tonnage is somewhere between {t(lo)} and {t(hi)}, and I would "
            f"rather not pick a point inside that.",
            reason="purchases that cannot be classified", numbers=nums,
            working=[
                step("Raw material bought", r["feedstock_t"], "tonnes",
                     "the item master names it, or the rate sits in the raw material band"),
                step("Finished pellets bought in", r["finished_t"], "tonnes",
                     "the item master names it, or the rate sits in the finished band"),
                step("Could not be told apart", r["unknown_t"], "tonnes",
                     f"{r['unknown_n']} purchases: generic stock item, narration says "
                     f"nothing, rate falls between the two bands"),
                step("So bought-in is at least", lo, "tonnes",
                     "counting only what is certainly a finished pellet"),
                step("And at most", hi, "tonnes",
                     "if every unclassified purchase turned out to be finished pellets"),
            ],
            head=f"{lo:,.0f} to {hi:,.0f} t",
            sub="bought in rather than made here, and I cannot narrow it",
            fix=f"Classify those {r['unknown_n']} purchases and both this and your production "
                f"figure become exact.")
    total = r["feedstock_t"] + r["finished_t"]
    nums["all"] = total
    return answered(f"In {r['fy']}: {t(r['feedstock_t'])} of raw material bought, and "
                    f"{t(r['finished_t'])} of finished pellets bought in.", nums,
                    working=[
                        step("Purchases in the year", total, "tonnes",
                             "every purchase voucher with a quantity against it"),
                        step("Raw material", r["feedstock_t"], "tonnes",
                             "the item master says raw material, or the rate is below the "
                             "finished pellet band"),
                        step("Finished pellets bought in", r["finished_t"], "tonnes",
                             "the item master says finished goods, or the rate is above "
                             "the raw material band"),
                        step("Could not be told apart", r["unknown_t"], "tonnes",
                             "none, so the split is exact"),
                    ],
                    head=t(r["finished_t"]), sub=f"bought in as finished pellets in {r['fy']}")


def r_item_comparison(r, p):
    nums = {"a": r["a"]["tonnes"], "b": r["b"]["tonnes"],
            "a_loads": r["a"]["loads"], "b_loads": r["b"]["loads"]}
    if r["changed_meaning"]:
        recipes = "; ".join(f"{x['made_from']} from {x['valid_from']}" for x in r["recipes"])
        return withheld(
            f"I will not compare those two. {r['grade']} did not mean the same product in "
            f"both periods: {recipes}. Putting them side by side would be adding two "
            f"different things together and calling it a trend.\n\n"
            f"Separately: {r['fy_a']}, {t(r['a']['tonnes'])}. "
            f"{r['fy_b']}, {t(r['b']['tonnes'])}.",
            reason="the code meant two different products", numbers=nums,
            head="Two different products",
            sub=f"{r['grade']} was not the same thing in both periods, so there is no "
                f"comparison to make",
            working=[
                step(f"{r['fy_a']}", r["a"]["tonnes"], "tonnes",
                     f"{r['a']['loads']} loads under the earlier recipe"),
                step(f"{r['fy_b']}", r["b"]["tonnes"], "tonnes",
                     f"{r['b']['loads']} loads under the later recipe"),
                step("Recipes the code has carried", len(r["recipes"]), "recipes",
                     recipes),
            ],
            fix="Give the new recipe its own product code, and the two years become "
                "comparable from that day forward. The years already recorded under one "
                "code stay uncomparable, and no amount of arithmetic fixes that.")
    change = r["b"]["tonnes"] - r["a"]["tonnes"]
    nums["change"] = abs(change)
    nums["pct"] = abs(change / r["a"]["tonnes"] * 100) if r["a"]["tonnes"] else 0
    return answered(f"{r['grade']}: {t(r['a']['tonnes'])} in {r['fy_a']}, "
                    f"{t(r['b']['tonnes'])} in {r['fy_b']}. "
                    f"{'Up' if change >= 0 else 'Down'} {t(abs(change))}"
                    + (f", or {nums['pct']:.1f} percent." if r["a"]["tonnes"] else "."),
                    nums,
                    working=[
                        step("Recipe check", len(r["recipes"]), "recipe",
                             "the code meant the same product in both years, so the two "
                             "figures are measuring the same thing"),
                        step(f"{r['fy_a']}", r["a"]["tonnes"], "tonnes",
                             f"{r['a']['loads']} loads"),
                        step(f"{r['fy_b']}", r["b"]["tonnes"], "tonnes",
                             f"{r['b']['loads']} loads"),
                        step("Change", change, "tonnes",
                             f"{indian(r['b']['tonnes'], 1)} less "
                             f"{indian(r['a']['tonnes'], 1)}"),
                    ],
                    head=t(r["b"]["tonnes"]), sub=f"of {r['grade']} in {r['fy_b']}, against "
                                                 f"{t(r['a']['tonnes'])} in {r['fy_a']}")


def r_dispatch_total(r, p):
    """The question is what we dispatched, so the answer is a tonnage.

    Two systems recorded these loads and they do not agree, which is a real reason to
    hedge. But the disagreement is the reason, not the answer. Leading with a count of
    loads answers a question nobody asked, so the headline stays in tonnes and becomes a
    range when the range is what is honestly known."""
    reg, bk, un = r["register_loads"], r["book_vouchers"], r["uninvoiced"]
    unt, total = r["uninvoiced_t"], r["tonnes"]
    confirmed = total - unt
    nums = {"loads": reg, "t": total, "vouchers": bk, "uninv": un,
            "uninv_t": unt, "confirmed_t": confirmed, "diff": abs(reg - bk)}
    working = [
        step("Loads in the dispatch register", reg, "loads",
             f"rows with {r['plant']} as the destination in {r['fy']}"),
        step("Tonnage on those loads", total, "tonnes", "sum of the net weights"),
        step("Sales vouchers in Tally", bk, "vouchers", "same party, same period"),
        step("Loads with no invoice number", un, "loads",
             "the register itself says nothing was raised against them"),
        step("Tonnage on those loads", unt, "tonnes",
             "this is the part the books cannot confirm"),
        step("Tonnage both systems agree on", confirmed, "tonnes",
             f"{indian(total, 1)} less {indian(unt, 1)}"),
    ]

    if reg == bk and not un:
        return answered(
            f"{t(total)} went to {r['plant']} in {r['fy']}, across {plural(reg, 'load')}. "
            f"The register and the books agree on the count and every load has an invoice "
            f"against it, so this figure is exact.",
            nums, working=working,
            head=t(total),
            sub=f"dispatched to {r['plant']} in {r['fy']}, across {plural(reg, 'load')}")

    lines = []
    if reg != bk:
        gap = abs(reg - bk)
        more = "register" if reg > bk else "books"
        lines.append(f"The register shows {plural(reg, 'load')} to {r['plant']} in "
                     f"{r['fy']}, totalling {t(total)}. Tally has "
                     f"{plural(bk, 'sales voucher')} for the same period. The {more} "
                     f"{'has' if gap == 1 else 'have'} {'one' if gap == 1 else gap} more.")
    else:
        lines.append(f"The register shows {t(total)} to {r['plant']} in {r['fy']}, across "
                     f"{plural(reg, 'load')}, and the books agree on the count.")

    if un:
        lines.append(f"{plural(un, 'of those loads', 'of those loads')} went out with no "
                     f"invoice number at all, carrying {t(unt)}. So {t(confirmed)} is "
                     f"confirmed on both sides and the rest is not.")
        head = f"{indian(confirmed, 1)} to {indian(total, 1)} t"
        sub = (f"dispatched to {r['plant']} in {r['fy']}. {t(unt)} of it is in the register "
               f"and nowhere in the books")
    else:
        lines.append(f"Every load has an invoice against it, so the tonnage is not in "
                     f"doubt. What is in doubt is whether the register or the books have "
                     f"the count right, and until that is settled I cannot tell you "
                     f"whether {t(total)} is the whole picture.")
        head = t(total) + ", unconfirmed"
        sub = f"the register's figure for {r['plant']} in {r['fy']}, which the books contradict"

    return withheld("\n\n".join(lines),
                    reason=("the register and the books disagree on the count" if reg != bk
                            else "loads left with nothing raised against them"),
                    numbers=nums, working=working, head=head, sub=sub,
                    fix=("Find the load the two systems disagree about, and raise the "
                         "missing invoices." if reg != bk and un else
                         "Find the load the two systems disagree about." if reg != bk else
                         "Raise the missing invoices and this becomes exact."))

RENDER = {
    "open_commitment": r_open_commitment,
    "order_book": r_order_book,
    "capacity_free": r_capacity_free,
    "month_pressure": r_month_pressure,
    "fit_new_tender": r_fit_new_tender,
    "capacity_compare": r_capacity_compare,
    "delivery_runway": r_delivery_runway,
    "material_by_month": r_material_by_month,
    "buy_in_cost": r_buy_in,
    "supply_outlook": r_supply_outlook,
    "cash_calendar": r_cash_calendar,
    "material_cost_per_gcv": r_material_cost,
    "production_cost": r_production_cost,
    "quote_for_tender": r_quote,
    "vendor_reliability": r_vendor_reliability,
    "vendor_capacity": r_vendor_capacity,
    "realised_price": r_realised,
    "outstanding": r_outstanding,
    "channel_split": r_channel_split,
    "item_period_comparison": r_item_comparison,
    "dispatch_total": r_dispatch_total,
}

FY = {"FY23-24": ("2023-04-01", "2024-03-31"), "FY24-25": ("2024-04-01", "2025-03-31"),
      "FY25-26": ("2025-04-01", "2026-03-31"), "FY26-27": ("2026-04-01", "2027-03-31")}


def expand_fy(params):
    """Financial years arrive as a label and become two dates. Doing it here means no metric
    has to know what an Indian financial year is."""
    out = dict(params)
    for key in ("fy", "fy_a", "fy_b"):
        if key in out and out[key] in FY:
            s, e = FY[out[key]]
            out[f"{key}_start"], out[f"{key}_end"] = s, e
    return out


def run(tenant_id, metric_name, params=None):
    spec = metrics.REGISTRY.get(metric_name)
    if not spec:
        return withheld(f"There is no metric called {metric_name}.", "unknown metric")

    defs = definitions.load(tenant_id)
    missing = definitions.require(defs, *spec.get("needs", []))
    if missing:
        # fails closed. no default, because a default would answer this customer's question
        # using another customer's rules.
        return withheld(
            f"This customer has no definition set for {', '.join(missing)}, so I do not know "
            f"which rule to apply. I have not guessed.",
            reason="missing definition", fix=f"Set {missing[0]} for this tenant.")

    try:
        with db.recording() as log:
            raw = spec["run"](db, tenant_id, defs, expand_fy(params or {}))
    except Exception as e:                              # noqa: BLE001
        return withheld(f"That query did not run: {e}", "query failed")

    ans = RENDER[metric_name](raw, params or {})
    ans["metric"] = metric_name
    # the console carries these into a follow-up, so what was chosen travels with the answer
    ans["params"] = dict(params or {})
    # Both halves of the console read off this. The left shows the answer, the right shows
    # the queries that produced it and the settings they were built with.
    ans["definitions_used"] = {w: {"since": defs[w]["version"], "params": defs[w]["params"]}
                               for w in spec.get("needs", []) if w in defs}
    ans["sql"] = log
    ans["raw"] = raw
    return gate(ans)
