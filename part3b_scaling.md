# Part 3B: what stops a wrong number reaching a customer

Seven engineers, mostly junior, Claude Code everywhere. I am not slowing that down. I am
making sure the fast, convincing code cannot be wrong in the one way that ends the business.

Two halves. One tells me after something has gone wrong, and it is most of the daily work.
The other makes the common mistakes impossible to write, and that is the half that holds when
I am not reading every diff.

**It starts before any code, with a truth document.** For every customer, before we build, we
write down what he actually needs, the benchmark questions he will really ask, and the answer
to each one, worked out by hand in SQL against his own data. The developer may write it or I
may. I approve it, and I check it line by line against the BRD, because if those two drift
apart everything built on top is confidently wrong. If the truth document is satisfied, the
product is good. If the truth document itself is wrong, that is on me. It also carries
forward, because it is the list of things that must never break when the data is ten times
bigger.

**Where Claude Code actually goes wrong is definitions, not syntax.** Point it at a customer's
Tally database and ask what a purchase is, and it will read the tables and decide. Usually
something reasonable, often more complicated than he meant, and it will not tell you it
decided. The code compiles, the tests pass, and the number answers a question nobody asked. So
we never let one definition get picked quietly. We have Claude Code build the answer under
every definition the data plausibly supports, then choose deliberately: his definition if he
gave us one, the choice shipped to him on screen if we can manage it, otherwise the most
plausible reading with **the definition printed next to the number**. He is never left
assuming it means what he had in his head. That one line is the difference between a
correction and a lost customer.

**What I would slow the team down for is the audit trail, before the product.** I do not want
a finished product first. I want a version where, for every answer, I can see which of his
tables it read, where that data came from, which columns it leaned on, and where an assumption
could be wrong, for example treating a column as a primary key when nothing guarantees it is
one. If Claude Code built it and the developer cannot tell me which tables it touched, then
nobody in the building understands the product, and the first time it is wrong we will not
know why. Only once an answer holds for arguments other than the one in the demo do we go to
the truth checklist.

**After it ships, a checklist on a cron.** Every truth question re-run daily against its known
answer, the schema checked for movement, columns watched for values we have never seen. We
find out before the customer does. When it fails at six in the morning we do not stop the
product. It keeps running and the failure becomes the priority for the day. The question is
which kind it is: a one off or bad data, or an edge case we never thought about when the truth
questions were written. The second is urgent, because it means our truth document was
incomplete and he may already be holding a wrong answer. We fix it, re-ship, and add that case
to the truth layer and the cron so it cannot come back quietly. We also ask for error queries,
deliberate probes at shapes we have not handled, alerting to Slack so I see a failure before
he telephones, and we run the queries against heavy data before handover, because a query that
is correct and times out is a wrong number as far as he is concerned.

## The other half: what I make impossible, not discouraged

A rule an engineer can skip at eleven at night is a preference. Five things are built so the
wrong thing cannot be written.

**1. The product cannot turn a sentence into SQL.** The obvious build is to let the model
write the query. It demos well and fails the first time it invents a join, with no way to
tell. So the interface takes the name of a calculation and typed values, every value coming
out of the customer's own tables. There is nowhere for a free text endpoint to plug in.

**2. No number leaves without a second agent checking it against the audit trail.** The model
can state a number. What it cannot do is state one nobody has checked. Every figure it gives
comes with the trail behind it: the query that produced it, the rows, and the arithmetic that
turned those rows into the figure. A second agent then takes that trail and verifies the
number independently, and only a number that survives that goes out. The point is that the
check does not depend on the same reasoning that produced the answer. Building Part 2 this
caught three real bugs, all of them numbers typed into a sentence by hand, correct sounding
and not in the data. Every one would have shipped.

**3. One customer's data cannot reach another's answer.** Enforced inside Postgres, and the
account the application uses cannot switch it off. A junior who forgets the filter gets zero
rows on his own machine, not somebody else's data in front of a customer.

**4. An answer that cannot show where it came from is not sent.** Every answer carries the
queries that produced it and the definitions it used. There is no way to make one without its
lineage, because they are the same object. When a number is disputed six months later I open
it and read what it did.

**5. The build fails on a query written outside the layer**, and on a calculation that
declares it uses a definition and never reads it, because otherwise people satisfy the rule by
writing the line and ignoring it. I would land it as a warning first, clear the branches
already open, and make it a hard failure the same week.

Detection tells me something broke. These five mean the common breakages cannot be written.
With seven engineers and a lot of generated code that distinction is most of my answer,
because I will not always be in the room and the checklist only runs once a day.
