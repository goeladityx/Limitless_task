# Part 2: what I built, and how to read it

## Where to see it

Running at **https://pellet-console.onrender.com**, or clone the repo and double click
`run.bat`. Both give the same thing.

## The company

- **Marudhar Biofuels**, Bikaner. Crop residue in, fuel pellets out, sold to NTPC power
  stations and to private buyers nearby. Around 165 crore a year.
- Modelled on a producer I consulted for between March and June 2025. The defects in the
  data are the ones I found in their books, not ones invented to be solvable.
- A second company, **Saurashtra Green Pellets**, runs on the same code with different
  buyers, different crops and different definitions. Nothing is hardcoded to the first.

## Two words that are not the same word

- A **vendor promises**. We buy from him. Until somebody confirms it, a commitment is a
  sentence in an email.
- A **buyer contracts**. A private buyer contracts a quantity per month, which cannot move.
  A public buyer contracts a total for the year against a deadline, with **no monthly
  obligation at all**.
- So a tender's monthly figure is a **pace**, not a promise, and it can be moved inside its
  window. A private buyer's monthly draw cannot. Report them as one number and a month looks
  unfixable when it is mostly a scheduling choice.

## The story the product opens with

Open the site and you are not shown a dashboard. You are put in the owner's chair.

- **A tender lands on his desk.** 3,000 tonnes. He has ten days to decide whether he can fill
  it and what to bid.
- **He is paid on energy, not weight.** Above 2,800 GCV he is paid on the heat that actually
  arrives. Between 2,000 and 2,800 a quarter comes off. Below 2,000 the load is rejected. The
  GCV he quotes decides his margin before he has made a tonne.
- **He is already carrying more than he can see.** Live contracts, some nearly finished, some
  barely started.
- **He knows roughly what his plant can make**, and nothing about what he cannot control:
  labour, weather, moisture, a vendor who promised in April and sold elsewhere in October.
- **The problem is not that he wants more work.** It is that he cannot see what he is already
  carrying, and he is bidding anyway.

## Then the console picks the story up

**Finish the story** is the first tab and the fastest way to understand the product. Five
questions in the order he would actually ask them, each one run live, each sentence editable:

1. *What have I already agreed to deliver?* **It refuses.** Five loads left with nothing
   written against them, so the honest answer is a ceiling.
2. *When have I actually got room?* **April 2027 onward.** September is oversold; the six
   months after it are full to within three percent.
3. *The tender is 3,000 t. By when could I have it made?* **April 2027.** A cumulative
   curve with the order drawn across it. Where they cross is the date worth quoting.
4. *What can I buy in to cover it?* **Nothing.** Not one vendor has promised anything for a
   year. The promises exist, in 1,500 emails nobody has read back to him.
5. *So what do I quote?* **₹7,013 a tonne**, with all eleven steps of the arithmetic shown.
   Change the margin and watch it move.

## The rest of it

- **Ask.** 23 questions. Each is a sentence with the choices inside it, and every choice
  comes out of that company's own data. There is no path from typed text to SQL.
- **Review queue.** Where the product asks *you* things. Answer one and the number it was
  blocking recomputes in front of you.
- **The data.** The raw Tally tables, unedited, so you can check anything yourself.
- **Definitions.** Seven words the two companies define differently. Each is a choice
  between full sentences, because a controller signs off on "a payment clears the oldest bill
  first", not on `fifo`.

## What to look for while you are in there

- **Switch companies** with the selector at the top. A bar names the definitions that
  changed. Ask the capacity question again: Saurashtra leaves tender volume until the
  deadline is close, so its March runs at **454 percent** while every other month sits idle.
  Same code, same question, one setting.
- **Every answer shows its working**, not the SQL, which is on the right for you, but the
  arithmetic: what each figure came from and which two numbers made it.
- **Read the refusals.** Nine of the 23 refuse. Each names the obstacle, gives a range where a
  range is honest, and says what would make it answerable.

## Three things worth testing rather than taking on trust

- **Change a definition**, confirm the numbers move, change it back, confirm they return
  exactly. `python -m app.test_wiring` asserts this against the live database, because a
  metric can declare a definition and never read it.
- **Answer a review item** and watch a refusal become an answer.
- **Write a query with no company filter** and get nothing back rather than both companies.
  `python tests/test_tenant_isolation.py`.

## What I would rather you pushed back on

- Vendor commitments exist only in email, so everything downstream rests on extraction.
- My answer: extraction only ever **proposes**, carrying the sentence it came from, and a
  person confirms. Until somebody does, the product will not build a floor on it, which is
  why question four refuses on both companies today.
- That is the most arguable decision in here, and I would rather defend it than hide it.
