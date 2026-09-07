# The 23 questions

Written the way the owner would type them. Fourteen are answered, nine are refused, and
which is which was decided **before** the query engine existed.

The expectations live in `app/questions.py`, one line per question, next to a `why`. The test
runner compares every answer against them on both companies and treats **refusing something
answerable as failure just as loudly as answering something unanswerable**:

```bash
python -m app.run_questions
  23 questions  |  14 answered  |  9 withheld  |  0 wrong
```

Nothing here is hardcoded to one company. Contract references, plant names, product codes and
financial years are all resolved per tenant, so the same 23 questions run against both books
and land on the right cases in each.

---

## The five the story asks

These are the tab the console opens on, in order. The rest of the list is the same machinery.

| | Question | Marudhar | Saurashtra |
|---|---|---|---|
| A3 | What have I already agreed to deliver? | **refuses** · up to 1,17,724 t | **refuses** · up to 44,168 t |
| A4 | When have I got room? | April 2027 onward | September 2026 onward |
| A9b | The tender is 3,000 t. By when could I have it made? | April 2027 | September 2026 |
| R4 | What can I count on from vendors? | **refuses** · nothing confirmed | **refuses** · nothing confirmed |
| A9 | So what do I quote? | ₹7,013 a tonne | ₹6,888 a tonne |

---

## Answered

**A1 · How much is left on this contract?** *(refuses, see the R-list note below)*
The contract chosen is one an open review item still points at, so the remainder is a range.

**A2 · How much is left on a contract nobody has left loose ends on?**
Every load to that plant is accounted for, so the subtraction is exact.
**A: 14,807.8 t · B: 5,700.0 t.** Single step.

**A4 · When have I got production capacity free over the next year?**
What the plant has managed each month, less the draws private buyers contracted for that
month, less the pace the tender deadlines need. Three states, not two: a month with 488 t
spare out of 17,318 is full, not free.
**A: April 2027 onward.** September is oversold, the six months after it run at 97%+.
**B: September 2026 onward**, but March 2027 is oversold by 20,395 t. Multi-step.
**Tenant-dependent:** B leaves tender volume until the deadline is close.

**A5 · Which raw material is cheaper per unit of energy?**
**A: ₹0.710/GCV** (Rice Husk) · **B: ₹0.731/GCV** (Groundnut Shell). The cheaper material per
*tonne* and the cheaper material per *unit of energy* are not always the same one, and energy
is what you get paid on.

**A6 · What does a tonne cost me to make, month by month?**
Feedstock at each calendar month's own rate, times the conversion ratio, plus conversion cost.
Both constants come from the plant's config, not from a number in the code.
**A: ₹1.839/GCV** cheapest · **B: ₹1.823/GCV.** Multi-step.

**A6b · And what does it cost to buy the same thing in ready made?**
Priced per unit of energy, because a bought-in pellet does not carry the same GCV as ours.
**A: ₹69.34 L lost** by buying in rather than making · **B: ₹15.47 L lost.** Multi-step.

**A7 · And for the other product line?**
**A: ₹1.784/GCV · B: ₹1.982/GCV.**

**A8 · What should I quote, delivering over the next year?**
**A: ₹7,067 a tonne · B: ₹7,055.** Eleven steps, all shown.

**A9 · And delivering in the cheap half of the year?**
**A: ₹7,013 · B: ₹6,888.** Shift the window and the quote moves. That is the point of the
question: a quote is a property of the months you produce in, not of the product.

**A9b · The tender on my desk is 3,000 t. By when could I have it made?**
No deadline required: the date is the answer. Room added up month by month until the total
covers the order. **A: April 2027, eight months out · B: September 2026.** Multi-step.

**A10 · What did we actually get per tonne on our biggest buyer in FY24-25?**
**A: ₹8,631 · B: ₹8,157.** **Tenant-dependent:** A counts after quality deductions over tonnes
accepted; B counts as invoiced over tonnes dispatched, and the answer says which.

**A11 · And on a second buyer, same year?**
**A: ₹7,610 · B: ₹7,542.**

**A12 · Who owes us money, and how much?**
**A: ₹16.38 Cr across 7 customers · B: ₹16.1 Cr across 4.** **Tenant-dependent:** a receipt
names no bill, so A clears the oldest first and B the newest. Same total owed, very different
ageing.

**A13 · What did we dispatch to that buyer in FY24-25?**
**A: 25,800.0 t · B: 17,300.4 t.** Both systems agree on the count and every load has an
invoice, so the figure is exact.

**A14 · How much did we produce ourselves in FY24-25?**
**A: 5,583.4 t bought in · B: 1,758.9 t.** Residue purchased is converted to pellets at the
plant's own ratio first, because 2.8 lakh tonnes of husk is not 2.8 lakh tonnes of product.

---

## Refused, and why each one is the right call

**A1 · How much is left on this contract?**
**A: 0 to 1,135 t · B: 0 to 534 t.** A load went out after the contract window closed, on an
extension nobody recorded, so it belongs either to the contract that just ended or to the one
that opened next. The date cannot settle it. → *Answer it in the review queue and the number
becomes exact.*

**A3 · What have we contracted to deliver in total?**
**A: up to 1,17,724 t · B: up to 44,168 t.** Loads left the yard with no contract written
against them, so the total is a ceiling. Given as a ceiling and labelled as one.

**R1 · How did this product compare between two years?**
The code meant two different recipes either side of the change, so putting the two years side
by side would be adding different things together and calling it a trend. The years are
resolved per tenant, because the two companies changed recipe in different years.

**R2 · How much of that year did we make ourselves, and how much did we buy in?**
**A: 6,491 to 7,029 t · B: 1,086 to 1,546 t.** Purchases where nothing says whether it was raw
material or a finished pellet: the item is a generic group, the narration says nothing, and the
rate falls between the two bands. → *Classify them in the review queue.*

**R3 · How much more could this vendor supply us next season?**
Never recorded anywhere. We know what we bought, which is a floor on his capacity and never a
ceiling. Different in kind from the others: no amount of cleaning fixes it, only a new field.

**R4 · Which vendors have kept their word?**
Every commitment was read out of an email and nobody has confirmed one. A reliability score
built on an unchecked extraction is a guess with a percentage sign on it.

**R5 · What did we dispatch in that year?**
**A: 10,861.6 to 12,092.2 t · B: 7,120.0 to 7,958.5 t.** The register and the books disagree on
the count, and a load carries tonnage the books have never seen. Answered in tonnes as a range,
because the question was asked in tonnes.

**R6 · What should I quote if I claim a GCV my product does not reach?**

The owner asks for a price at a quality his own product does not test at.

- **A:** PLT-A1 tests at **3,250 GCV**. He asked to quote **3,450**.
- **B:** PLT-C3 tests at **3,425 GCV**. He asked to quote **3,625**.

**Why it refuses.** The contract gets written at the figure he quotes, and he is paid on the GCV
that actually arrives. Quote 3,450 and ship 3,250 and every single load is short against its own
contract, so the deduction follows on all of them. That is not a bid, it is a shortfall planned
in advance, and the product will not be the thing that prices it.

**What would make it answerable.** One of two things, and the refusal says both. If the product
really does test higher than the item master claims, change the master. If it does not, quote
what the plant actually makes.

---

**R7 · What did we actually get per tonne on this buyer in FY25-26?**

**A: ₹7,949 to 9,539 on NTPC Lara · B: ₹8,239 to 8,994 on Morbi Cluster.**

This is the one I would point a sceptic at, because nothing here is missing. Both halves of the
sum exist:

| | Tenant A | Tenant B |
|---|---|---|
| Billed | ₹18.01 Cr | ₹5.23 Cr |
| Tonnes, per the dispatch register | 21,900.0 t | 6,349.6 t |

Divide one by the other and you get a confident, precise, wrong number.

**Why it refuses.** Realised price is money divided by tonnage. Ask the dispatch question about
this same buyer and this same year and it **also refuses**, because the register and the books
do not describe the same loads. R5 is that identical refusal on a different buyer.

So dividing by that tonnage would launder a figure the product has already declined to state,
and hand it back as a rate with two decimal places on it. A rule that holds on one screen and
quietly lapses on the next is not a rule, so the check runs in both places and R7 gives the
range instead.

---

## What the refusals are testing

- **Four kinds of not-knowing**, deliberately different: a load nobody placed (A1, A3), a
  purchase nobody classified (R2), a field that was never recorded at all (R3), an extraction
  nobody confirmed (R4).
- **Two systems that disagree** (R5), and the consequence of letting a second metric divide by
  the disputed figure anyway (R7).
- **A comparison that is not a comparison** (R1), where the arithmetic works fine and the
  meaning does not.
- **A number the owner asked for that would lose him money** (R6).

Five refusals give a range rather than nothing. That is the difference between "I cannot tell
you" and "here is what I can tell you, and here is the width of what I cannot".
