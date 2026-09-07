# Part 1: The Thinking

**The business.** Biomass pellet manufacturers in North India. They turn crop waste, mostly rice
husk and mustard stalk, into fuel pellets. They sell to NTPC and state power plants on tender,
plus some industrial boilers.

**How I know it.** I traded pellets and dealt with about ten producers and vendors across
Rajasthan and Gujarat. Then from March to June 2025 I consulted for Green Pellet Energy in
Bikaner, ₹150 to ₹180 Cr turnover, books on Tally. Most of what follows came out of
conversations with Kapil Agarwal, who owns it.

---

## 1. What actually goes wrong

I sorted everything I saw by one question:

> **Can a system fix this, and can it prove it got the answer right?**

That gives three groups. The sorting is the actual answer.

### Tier A. Fixable now, and provable
*The fact is already in their records. We can check it a second way.*

**1. He bids on a tender without knowing what he has already promised.** *(money)*
Fifty to sixty contracts a year. Awards sit in files. Dispatches sit in a register. Nothing joins
the two. At that count it is not inconvenient to do by hand. It is impossible.

**2. Cash is tightest in the month when buying is cheapest.** *(money)*
Material must be bought at harvest, over two or three months. The money from sales comes back
over twelve. Both halves are already sitting in Tally.

**3. He knows what he invoiced. He does not know what he earned per tonne.** *(money)*
NTPC pays on delivered GCV, and the penalty is a cliff, not a slope:

| Delivered GCV | What he gets paid |
|---|---|
| Above 2,800 kcal | Full rate |
| 2,000 to 2,800 | **A quarter is cut** |
| Below 2,000 | Nothing. Load rejected |

So the price looks fine, fine, fine, and then one load loses 25% of its value. Those cuts land in
credit notes, and nobody adds them up per buyer or per contract.

**4. Bought-in pellets look exactly like raw material in the books.** *(money)*
When the plant cannot make enough, he buys finished pellets from another producer. Tally cannot
tell the two apart. So his capacity looks bigger than it is, and the margin on those tonnes is
wrong.

**5. Nobody has checked how much material he could actually buy in past months.** *(material)*
Ten years of purchase records. Next year still gets planned from memory.

**6. Every vendor's promise is treated as equally good.** *(material)*
Some vendors hold to a promise when prices move against them. Some sell to whoever pays more that
week. Some deliver in full, three weeks late. Knowing which is which decides how much he can
safely commit to each of them next season.

The promises do exist, but only in the owner's inbox, because POs go out by email. What actually
arrived is in the books. So the comparison can be made, but only once somebody turns those email
threads into rows. More on that in section 2, because it is the clearest case in the product for
retrieval.

**7. The tender reference is often missing from the dispatch.** *(material)*
The men loading the truck know perfectly well which contract it is for. The register does not say.
The figure can be rebuilt, but only by going back and asking, and nobody does that. This is what
makes problem 1 possible.

**8. Procurement, production and sales each keep their own sheet.** *(people)*
He reconciles them by phone and gets three different answers.

**9. Entries are made weeks late and back-dated.** *(people)*
Last month's figures keep changing after month end.

### Tier B. Real, but nobody records it yet
*Someone has to start writing this down before any system can help.*

**10. Pellet quality, batch by batch.** *(material)*
This is the most expensive problem on the list, and it is in this tier on purpose. Dropping below
2,800 GCV costs a quarter of the invoice. So the single measurement that decides whether a load
loses a quarter of its value is the one nobody records. Until someone does, any number a system
produced here would be a guess in a suit.

**11. What a vendor *could* supply, not what we bought from him.** *(material)*
This decides how much he can commit to that vendor next season. But the books only record what
was purchased, and that is a floor, never a ceiling. If we took 200 t last October, nothing says
whether that was everything he had or a fifth of it. And when a vendor delivers short, the data
cannot separate "he could not" from "he sold it to someone paying more".

*The fix here is cheap: ask the vendor his capacity for the season and record it against the PO.
One field, and a whole class of question goes from unanswerable to arithmetic.*

### Tier C. Not a data problem at all
*We can measure these. We cannot fix them.* I want to be straight about both, because they sound
like exactly the kind of thing you would promise a customer.

**12. Pellets soaking up moisture in monsoon storage and transport.** *(material)*
This is physics, and the whole trade already knows it happens. Measuring it more precisely does
not stop it. Covered trucks and less time in storage stop it.

**13. The price and availability of husk itself.** *(material)*
That is a market. I can tell him exactly what he paid last October. I cannot make it cheaper this
October. What I *can* improve is the buying decision taken in April, and that is problem 5, which
is Tier A.

### Why problem 1 goes first

The evidence is public. GeM bid **GEM/2026/B/7652841** is one of **seven** issued the same day,
under the same lot, for Sipat, Korba, Mouda, North Karanpura, Darlipali, Lara and Gadarwara.

- A producer might bid on four of them.
- All four are supplied from **one factory**.
- NTPC can then increase or decrease each ordered quantity by **up to 25%** at contracted rates,
  at any point during the contract.

So the total tonnage he is on the hook for is neither fixed nor visible anywhere. That is how the
tender is built. It is not carelessness by the producer.

### Where this comes from

- **My own trading and consulting.** Informal. Ten or so companies is enough to say the problem
  is real, not enough to say how widespread it is.
- **Green Pellet Energy.** 50+ vendors in Rajasthan, 100+ across India, ten years of history, no
  analysis ever run on it. They are sitting on pending orders from Coca-Cola and HCL right now
  which they will not accept, because they cannot work out whether taking them would break their
  existing tender commitments.
- **The attached tender.** NTPC Limited, 17-06-2026. 265,720 MT to Sipat, 730 day delivery, GCV
  band 2,800 to 4,000 for non-torrefied, payment 30 days after the acceptance certificate, the
  25% option clause, and freight quoted by the bidder as a separate line.

**One limit worth stating.** Green Pellet Energy is just under the ₹200 Cr floor you mentioned. I
do not think that matters, because what changes above ₹200 Cr is which ERP they run, not what
goes wrong. But I have not worked inside a ₹2,000 Cr business on SAP, so I am not going to claim
I know how it looks there.

---

## 2. Where retrieval helps, and where it is dangerous

> **Retrieval should never make a decision. It can find things, and it can suggest.
> The decision comes from a fixed rule, or from a person.**

The product works the same way. We give the owner visibility. He makes the call. We do not make
it for him.

**You are right about the main thing.** Numbers cannot be approximately correct, and nothing in
my last four years of retrieval work changes that. In search, a close match is a good result.
Here, a close match is a wrong number.

### Where I would push back: the danger is not in the arithmetic

Adding up a column is not hard, and nobody ships a wrong total because the addition failed.

The risk sits one step earlier, in deciding **which rows get added up**:

- Which tender did that truck belong to?
- Are these two Tally ledgers the same vendor?
- Does this item code still mean the same product it meant in 2023?

Those three decisions produce the wrong totals. And those three are exactly what looks like a
retrieval problem.

### Banning the vector database is not the fix

I agree with the ban. But the tool was never really the problem. **Guessing is.**

Take away Pinecone and a developer will still write a `LIKE '%shri ram%'` query, or work out an
edit distance in Python, and use that to decide two vendors are the same firm. Same guess. Same
wrong total. It just looks safe now, because there is no vector database in the requirements
file. Postgres itself ships trigram matching and full text search, and those are retrieval too.

So the thing worth banning is not the library. It is letting any of it decide.

### Three places it genuinely helps

1. **Vendor promises exist only as email.** POs go out over mail. The quantity, the date and the
   rate get agreed in a thread, and nothing structured ever records any of it. Reading the
   correspondence is the only route, short of asking someone to re-key three years of mail by
   hand. Without retrieval, one of the most valuable questions in this product simply has no
   answer.
2. **The tender document.** Eleven pages of prose plus attachments, with the option clause, the
   payment trigger and the recovery methodology scattered through it. There is no schema and
   there never will be.
3. **Working out what the owner meant** when he typed something on WhatsApp, so we route it to
   the right calculation.

Points 2 and 3 produce a **pointer**, not a number, and a wrong pointer is cheap, because he just
says "no, I meant the other one".

Point 1 is different, and I want to be straight about it. Pulling a commitment out of an email
**writes a row into the data**, which is closer to deciding than I would normally allow.

**What makes it acceptable is that it stays checkable:**

- Every extracted commitment links back to the exact mail and the exact sentence it came from.
- The controller opens it and reads the line.
- Nothing counts until a person confirms it.
- Until then, the system treats that commitment as **absent**, not assumed.

Set that against a similarity score of 0.83, which she can only accept or reject blindly. Same
principle, opposite outcome. Retrieval is fine here precisely because its working can be
inspected by the person who owns the number.

### Where it would do real damage

**Deciding whether a purchase was raw material or a finished pellet.**

It looks like a text problem, because often all you have is a description somebody typed into
Tally. A model reads "PLT mix 3600" and makes a sensible guess. But that guess goes straight into
how much we think the plant can produce. If it is wrong, we tell the owner he has capacity he
does not have, and he takes a tender he cannot fill.

**The rate should settle it, not the words.** Husk runs around ₹2,000 a tonne, finished pellets
around ₹7,000. That gap is wide enough to classify most rows with no judgement at all. Anything
sitting in between goes to a person, and until they answer, we do not count it.

A guess feels more helpful in the moment. It is the one that ends up costing him a penalty.

### And a controller cannot review a score

There is a practical reason too, and it comes from your own requirement: you asked for something
a finance controller can review and correct. The two options are not alike.

| What the system tells her | What she can actually do |
|---|---|
| "These two vendors match, score 0.83" | Accept it or reverse it, blindly. She has no way of judging whether 0.83 was high enough, because that number tells her nothing about her business |
| "These two ledgers carry the same GSTIN" | Check it herself, and give a reason either way |

One of those she can review. The other she can only overrule.

---

## 3. What I would ship first

> **One thing: tell him what to quote, in rupees per GCV.**

That unit matters more than it looks. NTPC pays delivered GCV multiplied by the rate he quoted,
so a price without a GCV attached is half a number. Quote ₹6,400 at 3,200 and he has really
quoted ₹2.00 per GCV. Deliver 3,400 and he gets ₹6,800.

Everything in this business, cost included, only makes sense in that unit. And nobody tracks it.

He forwards a tender. He gets back the rate he should bid, and the working:

> **4,200 t to NTPC Sipat, delivery Apr 2026 to Mar 2028.**
>
> **You have no room until March.** September, October and November are already oversold against
> anything the plant has ever managed, September by 1,976 t. From March 2027 there is 15,991 t of
> spare capacity across the year.
>
> **Producing April to June costs you ₹1.727 per GCV.** September to November costs ₹1.779. March
> is your cheapest month at ₹1.669. That spread is nothing but timing.
>
> **At ₹0.30 per GCV of margin, quote ₹2.027 per GCV.** On the form that is **₹6,488 a tonne at a
> 3,200 bid**, or ₹6,893 at 3,400.
>
> Every 200 GCV either way is ₹413 a tonne. Under 2,800 a further quarter goes.

Every figure comes from his own books or the tender document. The margin per GCV is the only
thing he chooses. Nothing is predicted, and if a line cannot be checked a second way, it is not
sent.

**That unit keeps surfacing what the per-tonne view hides.** Mustard stalk costs ₹2,531 a tonne
against husk at ₹2,200, so on the purchase ledger it looks like the expensive option. Per GCV it
is ₹0.684 against ₹0.733, so it is the cheaper energy, and it lifts delivered GCV, which lifts
revenue on the same tonne. The two answers disagree, and only one of them is the one he gets paid
on.

- **Who it is for.** The owner. There is no CFO at this size, and he does not open dashboards.

- **What it replaces.** Today that answer takes days. He rings the plant, rings procurement,
  rings the accountant, and holds the tender commitments in his head. So when there is not time,
  he refuses the order. That is exactly what is happening at Green Pellet Energy right now with
  the Coca-Cola and HCL orders sitting pending.
  **We are not competing with a dashboard. We are competing with him saying no.**

- **Why it is hard to copy.** Not the code, the code is two weeks. What builds up is the
  decisions: which truck belonged to which tender, which ledgers are one vendor, each confirmed
  by a person and then applied automatically on every sync after that. Anyone can copy the
  screens. Nobody can copy six months of someone's judgement calls on their own books. And once
  the owner has stopped ringing his accountant, whoever holds that trust holds the account, until
  they get one number wrong.

- **What I am deliberately not building in version one.** Anything that decides for him.
  Searching for the best delivery plan, picking the best combination of tenders, predicting what
  quality will be on arrival. He has been making those calls for ten years and he is good at it.
  What he cannot do is the arithmetic across seven live tenders in his head. That is our job, and
  it is the part that can be proved correct.

### What we read, and what we create

Worth being exact about this, because two of the things this product needs do not exist anywhere
yet.

| | Exists today? | How we get it |
|---|---|---|
| Purchases, sales, payments | Yes, in Tally | We read it |
| Dispatches | Yes, in the register | We read it |
| Production | Yes, in the register | We read it |
| Tender awards | Yes, in a folder | We read it |
| What each vendor promised us | **No.** It is in email threads | We extract it, a person confirms each one |
| How we plan to deliver, month by month | **No.** It is in his head | He tells us when he wins a tender |

Six things we read, two we create, and we invent neither of the two. One comes out of their own
mail with a human confirming every row. One comes from the owner telling us his own plan. We are
writing down things the business already knows but has never recorded.

Those two are also the only places we ask anyone to change how they work, and in my experience
that is always the expensive part, so it is worth keeping that list short.

**Why this, and not receivables.** His accountant can already tell him who owes what by Friday.
Slowly, but correctly. Nobody in that company can answer the tender question at all, and getting
it wrong costs a penalty or a refused order.
