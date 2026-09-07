"""
Pulling vendor commitments out of the mail.

This is the one place in the product where something has to read prose and write a row. What
a vendor promised was agreed in an email thread and recorded nowhere else, so there is no
alternative to reading it.

Three rules keep it honest:

  1. It proposes, it never decides. Every extraction lands with status 'proposed' and does
     not count towards any answer until a person confirms it.
  2. Every row keeps the sentence it came from, so a controller can check it in two seconds
     rather than taking the extractor's word for it.
  3. It only writes what it actually found. A thread it cannot parse produces no row, not a
     guessed one.

The parser here is deterministic, because these are templated confirmations and a regex reads
them perfectly. A model would be needed for real mail, and it would sit in exactly this slot
with exactly the same rules around it: propose, quote the source, wait for a person.

    python -m app.extract [a|b]
"""

import re
import sys
from datetime import datetime

from . import db

# "Accepted. 418.8 MT rice husk @ Rs 1908 PMT. Delivery 24-Apr-2023 positive."
QTY = re.compile(r"(\d[\d,]*\.?\d*)\s*MT", re.I)
RATE = re.compile(r"Rs\.?\s*(\d[\d,]*\.?\d*)\s*(?:per\s*(?:MT|tonne)|PMT|/MT)", re.I)
DATE = re.compile(r"(\d{1,2}-[A-Za-z]{3}-\d{4})")
MAT = re.compile(r"(rice husk|mustard stalk|cotton stalk|groundnut shell|husk|stalk)", re.I)
# only a reply counts as a commitment. Our own request is a requirement, not a promise.
REPLY = re.compile(r"\b(accepted|confirmed|yes sir|ok for|will dispatch|we can supply)\b", re.I)


def num(s):
    return float(s.replace(",", ""))


def parse(body):
    """Return what the sentence actually promises, or None. Never a partial guess."""
    if not body or not REPLY.search(body):
        return None
    q, r, d = QTY.search(body), RATE.search(body), DATE.search(body)
    if not (q and r and d):
        return None
    try:
        when = datetime.strptime(d.group(1), "%d-%b-%Y").date()
    except ValueError:
        return None
    m = MAT.search(body)
    return {"qty_t": num(q.group(1)), "rate": num(r.group(1)), "promised": when,
            "material": (m.group(1).lower() if m else "feedstock"),
            "quote": body.strip()}


def run(tid, auto_confirm=False):
    """auto_confirm exists so the demo can show the finished state. In the product a person
    confirms these, which is why it is off by default."""
    emails = db.fetch(tid, """
        SELECT msg_id, thread_id, from_addr, sent_at, body FROM src_email ORDER BY msg_id""")
    ledgers = db.fetch(tid, """
        SELECT ledger_name FROM src_tally_ledger WHERE parent_group = 'Sundry Creditors'""")
    # the sender's local part is the first word of the trading name, which is how we tie a
    # message back to a party without guessing
    by_first = {}
    for lg in ledgers:
        by_first.setdefault(lg["ledger_name"].split()[0].lower(), lg["ledger_name"])

    parties = {p["name"]: p["party_id"] for p in db.fetch(tid, "SELECT party_id, name FROM party")}

    found = skipped = unmatched = 0
    with db.tenant_cursor(tid) as cur:
        cur.execute("DELETE FROM vendor_commitment")
        for e in emails:
            got = parse(e["body"])
            if not got:
                skipped += 1
                continue
            local = (e["from_addr"] or "").split("@")[0].lower()
            name = by_first.get(local)
            pid = parties.get(name) if name else None
            if not pid:
                unmatched += 1
                continue
            cur.execute("""
                INSERT INTO vendor_commitment
                  (tenant_id, party_id, qty_t, rate_agreed, promised_date,
                   source_msg_id, source_quote, status, confirmed_by, confirmed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (tid, pid, got["qty_t"], got["rate"], got["promised"],
                 e["msg_id"], got["quote"][:400],
                 "confirmed" if auto_confirm else "proposed",
                 "demo" if auto_confirm else None,
                 datetime.now() if auto_confirm else None))
            found += 1
    return {"found": found, "not_a_commitment": skipped, "vendor_unmatched": unmatched}


if __name__ == "__main__":
    ids = [a for a in sys.argv[1:] if not a.startswith("-")] or \
          [t["tenant_id"] for t in db.tenants()]
    confirm = "--confirm" in sys.argv
    for t in ids:
        r = run(t, auto_confirm=confirm)
        print(f"tenant {t}: {r['found']} commitments extracted "
              f"({'confirmed' if confirm else 'awaiting confirmation'}), "
              f"{r['not_a_commitment']} messages were not commitments, "
              f"{r['vendor_unmatched']} could not be tied to a vendor")
