"""
Per-tenant definitions.

Two producers use the same word to mean different things and both are right. So the words
live in a table as typed settings, not in the code and not as stored SQL.

Parameters rather than SQL for a reason a finance controller would recognise: she can
review "do we count the option clause or not". She cannot review a SQL string. Anything
outside the parameter schema below is a code change, and that is the point.

Versioned, never updated in place. Changing a definition closes the current row and opens a
new one, so an answer given in June is still reproducible in December and "why did this
number change" has a name and a date attached to it.
"""

from datetime import date

from . import db

# The shape each word is allowed to take. A value outside this is rejected, which is what
# keeps "changing a value" (a row) apart from "changing the shape" (a migration).
SCHEMA = {
    "order_book": {
        "apply_option_clause": (bool, "count the buyer's right to increase the order"),
        "option_pct": (float, "how much they can increase it by"),
    },
    # A government tender is a total against a deadline. It carries no monthly promise, so
    # laying it across months is a planning choice, and the tenant has to own that choice.
    "capacity": {
        "tender_planning": (["even", "deadline"],
                            "run at a steady pace to the deadline, or leave it until the "
                            "deadline is close"),
        "basis": (["average", "best"],
                  "what the plant can do in a month: its average, or its best ever"),
    },
    "procurable": {
        "basis": (["best", "median"], "best month ever, or the middle of the range"),
        "lookback_years": (int, "how far back to look"),
    },
    "realised_price": {
        "net_of_recoveries": (bool, "after quality deductions, or as invoiced"),
        "over": (["accepted", "dispatched"], "per tonne accepted, or per tonne shipped"),
    },
    "overdue": {
        "clock_starts": (["crac", "invoice"], "from acceptance, or from the invoice date"),
        "days": (int, "how many days"),
    },
    "outstanding": {
        "net_advances": (bool, "net advances off, or keep them separate"),
        # Receipts arrive as "against bill" with no bill number, so something has to decide
        # which invoice a payment cleared. Whichever rule you pick changes who looks late.
        "apply_receipts": (["fifo", "lifo"], "a receipt clears the oldest bill, or the newest"),
    },
    "vendor_reliability": {
        "min_observations": (int, "fewer than this and no rate is quoted"),
        "partial_counts_as": (["miss", "pro_rata"], "how a short delivery is scored"),
    },
}

# What each tenant actually uses. These are the four words the write-up talks about, plus
# two more that fall out of the same machinery.
SEED = {
    "a": {
        "order_book":        {"apply_option_clause": False, "option_pct": 0.25},
        "capacity":          {"tender_planning": "even", "basis": "average"},
        "procurable":        {"basis": "best", "lookback_years": 3},
        "realised_price":    {"net_of_recoveries": True, "over": "accepted"},
        "overdue":           {"clock_starts": "crac", "days": 30},
        "outstanding":       {"net_advances": False, "apply_receipts": "fifo"},
        "vendor_reliability": {"min_observations": 5, "partial_counts_as": "miss"},
    },
    "b": {
        # B counts the option clause, because in their experience the buyer always uses it
        "order_book":        {"apply_option_clause": True, "option_pct": 0.25},
        # B plans tender volume evenly and quotes its best month, so every month looks
        # busier and every month looks bigger. Both at once.
        "capacity":          {"tender_planning": "deadline", "basis": "best"},
        "procurable":        {"basis": "median", "lookback_years": 3},
        "realised_price":    {"net_of_recoveries": False, "over": "dispatched"},
        "overdue":           {"clock_starts": "invoice", "days": 45},
        "outstanding":       {"net_advances": True, "apply_receipts": "lifo"},
        "vendor_reliability": {"min_observations": 5, "partial_counts_as": "pro_rata"},
    },
}


# How each choice reads to the person who has to sign off on it. The schema above is what
# the compiler enforces; this is the same thing in the controller's language. She is not
# picking True. She is picking "count the buyer's right to increase the order".
PHRASING = {
    "order_book": {
        "apply_option_clause": {
            False: ("Only what was awarded",
                    "The order book is the tonnage on the letter of award. If the buyer "
                    "later exercises his option, it lands in the book on the day he does."),
            True:  ("Awarded, plus the option the buyer can still call",
                    "Assume every buyer uses his right to increase the order. Bigger book, "
                    "and the plan is built against tonnage nobody has ordered yet."),
        },
        "option_pct": {"_note": "How much the buyer may increase the order by."},
    },
    "capacity": {
        "tender_planning": {
            "even": ("Run at the pace the deadline needs",
                     "Divide what is still owed by the months left in the window. That is "
                     "the pace you have to keep, and a month is tight when that pace plus "
                     "your contracted draws is more than the plant can make."),
            "deadline": ("Leave it until the deadline is close",
                         "A government tender is a total against a deadline. Nothing is "
                         "owed in any particular month, so months stay clear until the "
                         "deadline is close. The months ahead look empty right up until "
                         "they are impossible, which is how a producer ends up bidding for "
                         "work he has no room for."),
        },
        "basis": {
            "average": ("What the plant usually does in that month",
                        "The average of what the production register recorded for that "
                        "calendar month. Conservative, and closer to a normal year."),
            "best":    ("What the plant did in its best ever month",
                        "The highest that calendar month has ever hit. Every month looks "
                        "bigger, and a plan built on it needs everything to go right."),
        },
    },
    "procurable": {
        "basis": {
            "best":   ("The best season we have ever had",
                       "Take the strongest month on record as what a vendor could repeat."),
            "median": ("The middle of what we normally see",
                       "Take the median month. Lower number, far harder to miss."),
        },
        "lookback_years": {"_note": "How many years of history count as evidence."},
    },
    "realised_price": {
        "net_of_recoveries": {
            True:  ("After the buyer's quality deductions",
                    "What actually reached the bank, once GCV shortfalls were taken off."),
            False: ("As invoiced, before deductions",
                    "The price on the bill. Flattering, and it is not the money you got."),
        },
        "over": {
            "accepted":   ("Per tonne the buyer accepted",
                           "Divide by the tonnage that passed at the gate. Rejected loads "
                           "make the realised price worse, which is the truth."),
            "dispatched": ("Per tonne we sent out",
                           "Divide by everything that left the yard, accepted or not."),
        },
    },
    "overdue": {
        "clock_starts": {
            "crac":    ("From the day the buyer accepted the load",
                        "The contractual clock. Nothing is late until acceptance is signed, "
                        "which is also how a PSU will argue it."),
            "invoice": ("From the day we raised the bill",
                        "Our clock. More bills look overdue, and the buyer will disagree."),
        },
        "days": {"_note": "How many days the buyer has before a bill is overdue."},
    },
    "outstanding": {
        "net_advances": {
            True:  ("Net advances off what a party owes",
                    "Money we are holding from a party reduces what that party owes us."),
            False: ("Keep advances separate",
                    "Show the debt gross. Advances sit in their own line."),
        },
        "apply_receipts": {
            "fifo": ("A payment clears the oldest bill first",
                     "The usual trade convention. Old bills close, and what is left open "
                     "is genuinely recent."),
            "lifo": ("A payment clears the newest bill first",
                     "Same total owed, but old bills stay open and the ageing looks far "
                     "worse. Some buyers really do pay this way, against a stated bill."),
        },
    },
    "vendor_reliability": {
        "min_observations": {"_note": "Below this many deliveries, no score is given at all."},
        "partial_counts_as": {
            "miss":     ("A short delivery is a miss",
                         "He promised 100 and sent 60, so he did not keep his word. Harsh, "
                         "and it is the rule that stops you planning on half a load."),
            "pro_rata": ("A short delivery counts for what arrived",
                         "60 of 100 scores 0.6. Kinder, and it hides a vendor who is "
                         "reliably half there."),
        },
    },
}


def phrasing(word: str, key: str, value):
    """The sentence for one setting, or None where the value is a plain number."""
    opts = PHRASING.get(word, {}).get(key)
    if not isinstance(opts, dict):
        return None
    return opts.get(value)


def choices(word: str, key: str):
    """Every option for one setting, as sentences. Empty where it is a free number."""
    opts = PHRASING.get(word, {}).get(key, {})
    out = []
    for val, txt in opts.items():
        if val == "_note" or not isinstance(txt, tuple):
            continue
        out.append({"value": val, "label": txt[0], "detail": txt[1]})
    return out


def note(word: str, key: str):
    opts = PHRASING.get(word, {}).get(key, {})
    return opts.get("_note") if isinstance(opts, dict) else None


def validate(word: str, params: dict):
    """Reject anything the schema does not describe. A value the schema allows is a config
    change. A value it does not is a code change, and it should feel like one."""
    if word not in SCHEMA:
        raise ValueError(f"no such definition: {word}")
    for key, val in params.items():
        if key not in SCHEMA[word]:
            raise ValueError(f"{word} has no setting called {key}")
        allowed = SCHEMA[word][key][0]
        if isinstance(allowed, list):
            if val not in allowed:
                raise ValueError(f"{word}.{key} must be one of {allowed}")
        elif allowed is bool:
            if not isinstance(val, bool):
                raise ValueError(f"{word}.{key} must be true or false")
        elif not isinstance(val, (int, float)):
            raise ValueError(f"{word}.{key} must be a number")
    return True


def load(tenant_id: str) -> dict:
    """Everything currently in force for this tenant.

    Fails closed. If a word has no row, it is absent from the dict, and any metric that
    needs it refuses rather than quietly falling back to a default. A default here would
    mean silently answering one customer's question with another customer's rules."""
    rows = db.fetch(tenant_id, """
        SELECT word, params, valid_from
        FROM definitions
        WHERE valid_to IS NULL OR valid_to > current_date
        ORDER BY word, valid_from DESC
    """)
    out = {}
    for r in rows:
        out.setdefault(r["word"], {"params": r["params"], "version": str(r["valid_from"])})
    return out


def require(defs: dict, *words):
    """Used by every metric that depends on a definition. Returns the missing ones so the
    refusal can name them instead of saying something vague."""
    return [w for w in words if w not in defs]


def set_definition(tenant_id: str, word: str, params: dict, who: str = "console"):
    """Change a value. Closes the current row, opens a new one. History is kept, so an
    answer can always be re-derived under the rules that were in force when it was given."""
    validate(word, params)
    with db.tenant_cursor(tenant_id) as cur:
        cur.execute("UPDATE definitions SET valid_to = current_date "
                    "WHERE word = %s AND valid_to IS NULL", (word,))
        cur.execute("INSERT INTO definitions (tenant_id, word, params, valid_from, set_by) "
                    "VALUES (%s, %s, %s, current_date, %s) "
                    "ON CONFLICT (tenant_id, word, valid_from) DO UPDATE "
                    "SET params = EXCLUDED.params, set_by = EXCLUDED.set_by, valid_to = NULL",
                    (tenant_id, word, __import__("json").dumps(params), who))


def seed():
    """Put the starting definitions in place for both tenants."""
    import json
    for tid, words in SEED.items():
        for word, params in words.items():
            validate(word, params)
            with db.tenant_cursor(tid) as cur:
                cur.execute("DELETE FROM definitions WHERE word = %s", (word,))
                cur.execute(
                    "INSERT INTO definitions (tenant_id, word, params, valid_from, set_by) "
                    "VALUES (%s, %s, %s, %s, 'seed')",
                    (tid, word, json.dumps(params), date(2023, 4, 1)))
        print(f"  tenant {tid}: {len(words)} definitions")


if __name__ == "__main__":
    print("seeding definitions")
    seed()
