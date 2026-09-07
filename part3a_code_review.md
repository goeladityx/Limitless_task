# Part 3A: the code review

## First, the thing that would not have happened

The scenario has a junior handing the customer his number on Thursday, Thursday being the
customer's own date. I do not give a junior the customer's date. I give him one two days
earlier and keep the real one, and those two days are mine to run the work myself. So his
date was Tuesday and I am reading this PR with room to move. Betting a customer delivery on a
junior's last commit is a credibility problem for the company, and it is avoidable by moving
one date.

## The comment I would leave

> Good work, and the SQL is right. Two changes before I run this, and neither moves your
> date.
>
> **1. The meaning has to come from the definitions table, not from this query.** As written,
> `purchase` means whatever this SQL says it means. Every other number we give this customer
> takes its meaning from a row in `definitions`, per customer. So the first time somebody
> changes what a purchase means, this metric quietly keeps the old meaning and disagrees with
> everything around it. Nothing fails, no test goes red, and we find out when he tells us two
> of our screens do not match. Move it into `app/metrics.py`, declare `needs=["purchase"]`,
> and read the settings off `defs["purchase"]` the way `open_commitment` reads `committed`.
>
> **2. We have no `purchase` definition yet, so write more than one.** Do not ask him what he
> meant and wait. Work them out from his data. There are at least four here: everything
> invoiced, everything received at the gate, only what came against a commitment, and net of
> returns. Put them in the parameter schema, pick the one his request most plausibly means,
> and say so in the answer:
>
> > Supplier-wise purchases, FY24-25. Counting goods received, before returns.
> > Rs 4.2 Cr across 38 suppliers.
>
> If that is not what he wanted, he tells us in one sentence instead of in March. And he can
> see we did the work before coming to him with a question.
>
> **3. Send me a checklist I can run.** Not a description. Executable commands, one per thing
> he asked for, that I paste in and watch pass or fail.
>
> Your tests are right and they check the arithmetic. Keep them. What they cannot check is
> whether the meaning matches what he asked for, because nothing breaks when a definition
> drifts. That is what the checklist is for.

## Do I block it, or let it ship?

Neither, as the question is usually meant. I do not block the PR, and I do not approve it with
comments and leave him to fix it. He fixes it, pushes again, I check it myself, then I
approve. The approval is the last step.

I would not give a junior a direct line to a customer out of the gate. That comes after ten or
twelve deliveries that went out clean. Right now I do not know what his work looks like when
nobody is watching, so I look.

The customer still gets his number. Moving one query behind the definitions layer is a small
refactor and his date was never the constrained one. If it genuinely were a rewrite I would
ship it as written with a deletion date and a failing test that turns green when it is fixed,
because deadlines are real and a partial answer beats nothing. That is not the trade here.

What I am blocking is not the answer. It is the pattern. The number is correct today, and it
is correct for a reason nobody can see or change.

**Privately, after standup:** how we deliver, and why the definition travels with the number.
And that passing tests is partial evidence, not the evidence. What has to be true is that
everything we already know about his requirement passes, and that we went looking for the
other plausible definitions before the first ship. That is for his next piece of work, not a
stick to hit this one with.

**And the check, so I am not leaving this comment every month.** He wrote SQL in a handler
because nothing stopped him. If the only thing between us and the next one is me noticing,
then one busy week and it reaches a customer. So the real output of this review is two checks
in CI: one that fails the build on SQL outside the metrics layer, and one that fails a metric
which declares it uses a definition and never reads it. Without the second, people satisfy the
rule by writing the line and ignoring it, and the layer looks protected when it is not.
