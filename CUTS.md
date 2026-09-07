# What I cut, and why

Ten days, one person, and a brief that says one wrong number kills the product. Everything
below was cut deliberately. Where a cut costs something, that is written down too.

## Cut because it would not have made the answers safer

**A vector database.** The brief rules one out and I would not have reached for one anyway.
The hard problem here is not finding text, it is deciding whether a number is safe to send.
An embedding cannot tell you that a load has two possible contracts, and a similarity score
between two vendor names is a guess with a decimal point on it. Where retrieval genuinely
earns its place, in the vendor emails, a regex over a known sentence shape does the job and
is auditable line by line.

**Natural language to SQL.** It demos beautifully and fails the first time it invents a join,
with no way to know that it has. The interface takes a calculation name and typed parameters
instead, and every value it offers came out of the customer's own tables.

**Forecasting.** Every figure in here already happened or is already written in a contract.
The moment a forecast appears, the honest refusals become much harder to justify, because
"I cannot verify that" sits badly next to "here is my estimate for March".

**A general reporting layer.** Twenty calculations somebody thought about beats a query
builder that can produce anything, including nonsense, at three in the morning.

## Cut for time, and it costs something

**A model for the email extraction.** It is a regex over the reply patterns in these
threads. On real mail, with Hindi and English mixed and quantities written six ways, it
would miss a good share. The structure around it is the part that matters and would not
change: extraction proposes, with the sentence it came from, and a person confirms.

**Authentication.** Row level security is real and enforced in Postgres, and the tenant is
set per transaction. But the console picks the company from a dropdown. In a product that
comes from a session, and the gap between the two is a login screen and nothing conceptual.

**Incremental re-sync.** Loading is a full reload. Human decisions survive it, because they
are keyed on the source system's own reference rather than on a row id we generated, which
is the part that is hard to retrofit. Doing it incrementally is engineering, not design.

**A proper GCV model.** Calorific value here is a typical figure per material with a range
around it. Real GCV moves with moisture, with the season, with how long a bale sat in the
rain. The product is honest about this: it quotes the range where it matters and refuses to
narrow it.

**Freight.** Quoted as a separate line by the bidder in this trade, and left out entirely.
A real quoting tool has to carry it, and it changes which plant is worth bidding for.

## Cut on purpose, and I would cut it again

**Confidence scores.** There is no `confidence` column anywhere. A load is placed by a rule,
placed by a person, or waiting for a person. A number like 0.83 invites somebody to accept
it on a Friday afternoon, and the whole argument of this repo is that a range you cannot
narrow should be shown as a range.

**Automatic party matching on name similarity.** `party_link.method` has four values:
`gstin`, `pan`, `exact_name`, `human`. There is deliberately no `similarity`. The system
offers a shortlist and a person chooses. Putting a shortlist in front of somebody and letting
code pick from it are different things.

**Filling in the missing tender references.** Sixty two loads left the yard with nothing
written against them. Under the rule that one buyer runs one contract at a time, the date and
destination place most of them exactly, and the handful that went out after a window closed go
to a person. Guessing the last few would have made the demo tidier and the product worse.

## Where the write up was harder than it looked

Part 1 argues that retrieval may propose and may never decide. Vendor commitments are the
uncomfortable case, because they exist only in email, so everything downstream of them rests
on extraction. The line I settled on is that extraction produces proposals with their source
sentence, a person confirms, and until somebody does, no floor is built on them.
`supply_outlook` refuses on both companies today for exactly that reason. It is the most
arguable decision in here and I would rather defend it than hide it.
