# Answering questions for a biomass pellet manufacturer, without ever guessing

Two companies making fuel pellets from crop residue, selling to NTPC power stations and to
private buyers. Their books are in Tally. The question this repo answers is not "can a model
read a database", it is: **when do you refuse?**

Every number here either traces back to a query somebody can read, or it does not go out.

---

## Open it

**Already running, nothing to install:** **https://pellet-console.onrender.com**

Same code as this repo, same two companies, a Postgres in Singapore. The review queue is
unanswered and the definitions are at their defaults, so it opens where the story starts.

## Or run it yourself

**Windows:** double click **`run.bat`**.

**Mac or Linux:** `bash run.sh`

That is the whole thing. It builds a virtual environment, installs three dependencies into
it, starts Postgres in Docker, builds the schema, loads both companies, runs every test,
then serves the site and opens your browser at **http://localhost:8000**.

Nothing lands on your machine outside the folder you cloned. It needs Python 3.11 or later,
and Docker running unless you already have a Postgres. Later runs skip the install.

If any test fails it stops without serving anything. A demo that opens on a wrong number is
worse than one that does not open.

<details>
<summary>If you would rather do it by hand, or already have a Postgres</summary>

```bash
docker compose up -d                 # or point at your own Postgres
pip install -r requirements.txt
python setup.py                      # schema, data, definitions, then every test
python -m uvicorn app.api:app --port 8000
```

To use a database you already have, set these before running anything:

```
DATABASE_URL=postgresql://pellet_app:pellet_app@HOST:PORT/pellet
ADMIN_DATABASE_URL=postgresql://postgres:PASSWORD@HOST:PORT/pellet
```

The application connects as `pellet_app`, a role that **cannot** bypass row level security.
Only migrations use the owner account, which is why `db/003_guard.sql` exists. Needs Python
3.11 or later.
</details>

---

## Where to start

The site opens on a story: a tender lands on an owner's desk, he is paid on energy rather
than weight, and he cannot see what he is already carrying. Scroll it, then click through to
the console.

**Finish the story** is the first tab and the fastest way to understand the product. Five
questions in the order that owner would ask them, each run live against his books, each
sentence editable:

1. **What have I already agreed to deliver?** It refuses. Five loads left with nothing
   written against them, so the honest answer is a ceiling and a range. Underneath the
   refusal are those loads with the possible contracts beside them. **Answer one and watch
   the number tighten in place.**
2. **When have I got room?** April 2027 onward. September is oversold and the six months
   after it come out positive but under three percent, which is full rather than free.
3. **The tender is 3,000 t. By when could I have it made?** A cumulative curve with the order
   drawn across it. Where they cross is the date worth quoting.
4. **What can I buy in?** Nothing. No vendor has promised anything for a year.
5. **So what do I quote?** ₹7,013 a tonne, built from the feedstock rate in each month of the
   delivery window. Change the margin and watch it move.

Then **switch to Saurashtra Green Pellets** with the selector at the top. A bar names the
definitions that changed. Ask the capacity question again: this company leaves tender volume
until the deadline is close, so its March runs at 454 percent while every other month sits
idle. Same code, same question, one setting.

---

## The shape of it

```
seed_inputs/            the company as editable CSVs: vendors, buyers, plants, grades,
seed_inputs_b/          materials, contracts, prices, config, and the damage list
   |
   |  seed_contracts.py     one buyer runs one contract at a time. Asserted, not hoped for
   |  truth_gen.py          what really happened. Complete, and never queried by the product
   |  make_sources.py       break it into what the company actually has
   v
sources/                Tally as it really looks: text dates, quintals, a generic item name
sources_b/              on the ambiguous purchases, blank tender references, and 1,500
                        emails where the vendor commitments live as prose
   |
   |  db/load.py            untouched into src_* tables. Nothing is cleaned on the way in
   |  app/canonical.py      resolve what a rule can. Queue what it cannot
   |  app/extract.py        read the commitments out of the emails, as proposals
   v
app/metrics.py          the calculations. The only place SQL exists
app/definitions.py      seven words, per company, versioned
app/answer.py           renders a sentence, then refuses to send it if a figure has no source
app/web/index.html      the console
```

About 11,500 and 5,400 rows. Small enough to read, structured enough to break in the ways
real books break.

---

## The four things this is actually about

**A number the model cannot invent.** Every metric returns rows and the checks that ran. The
wording is filled from named values, and before anything is sent, every numeral in the text is
matched against the figures the query returned. A numeral that does not match means the reply
is withheld, not softened. This caught three real bugs during the build, all of them figures a
person had typed into a sentence by hand.

**A refusal that is worth reading.** Twenty three questions, fourteen answered, nine refused.
Each refusal names the obstacle, gives the range where there is one, and says what would make
it answerable. `python -m app.run_questions` treats refusing an answerable question as failure
just as loudly as answering an unanswerable one.

**A canonical layer a controller can correct.** Decisions are keyed on the source system's own
reference, so a re-import replays them instead of asking again. `party_link.method` records
whether a link came from a GSTIN, an exact name, or a person, so six months later you can see
which numbers rest on somebody's judgement. There is no `similarity` method, because a
similarity score is a guess with a decimal point on it.

**Two companies that are genuinely separate.** Row level security, forced, with the
application role unable to switch it off. Forget a filter and you get zero rows on your own
machine, not somebody else's data in front of a customer. `db/003_guard.sql` fails the build
if any table lacks a tenant column, RLS, or a policy.

---

## Terminology, because the two sides of the business are not the same

A **vendor promises**. We buy from him, and until somebody confirms it a commitment is a
sentence in an email.

A **buyer contracts**. A private buyer contracts a quantity per month, which cannot move. A
public buyer contracts a total for the year, with a deadline and **no monthly obligation at
all**.

So a tender's monthly figure is a *pace*, not a promise, and can be moved inside its window. A
private buyer's monthly draw cannot. Report them as one number and a month looks unfixable
when it is mostly a scheduling choice.

---

## The tests, and what each one is for

```bash
python -m app.run_questions             # 23 questions against the answer key, both companies
python -m app.audit                     # 160 answers checked for what a verdict cannot catch
python -m app.test_wiring               # changing a definition really moves the numbers
python tests/test_tenant_isolation.py   # a careless query sees one company, not both
```

`run_questions` checks the verdict. That is necessary and nowhere near enough: it says nothing
about whether the headline answers the question asked, whether a refusal contradicts its own
reason, or whether the figure on screen traces to anything.

So **`app/audit.py`** walks every metric with every parameter the data offers and checks each
answer for a headline no query produced, a refusal whose headline is a zero, an answer with no
derivation, a metric with no chart, and whether the console and the metric registry still
agree with each other. It found 42 problems the first time it ran.

**`app/test_wiring.py`** is the one I would point a sceptic at. It flips a definition against
the live database and requires the answer to move, answers a review item and requires the
refusal to become an answer, then puts both back and requires the numbers to return exactly. A
metric can declare it needs a definition and never read it; a review decision can be written to
a table nothing queries. In both cases every screen still looks right.

---

## What I did not build

No vector database. The hard part here is not finding text, it is deciding whether a number is
safe to send, and an embedding cannot tell you that a load has two possible contracts.

No natural language to SQL. The interface takes a calculation name and typed parameters, and
every value it offers came out of the customer's own tables. There is nowhere for a free text
query endpoint to plug in, which is the point.

No forecasting. Every figure is something that already happened or something a contract
already says.

No authentication, and the email extractor is regex rather than a model. `CUTS.md` has the
full list and why.

---

## Where I would push back

Part 1 argues that retrieval belongs on the proposing side and never on the deciding side. The
uncomfortable case is vendor commitments: they exist only in email, so everything downstream
rests on extraction.

My answer is that extraction only ever **proposes**, carrying the sentence it came from, and a
person confirms. Until somebody does, the product will not build a floor on it. Question four in
the story refuses on both companies today for exactly that reason.

Whether that is the right line is the most interesting thing to argue about in here.
