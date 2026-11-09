# Hand-scoring rubric

This is the rubric for the hand-scored evaluation set. Two people score each
conversation independently. The ML team then compares those scores with what
the automated audit says, to see how often it agrees with a person.

The conversations to score, and the empty score sheet, are in
[`scoring_template.csv`](scoring_template.csv).

## How to score

1. **Pick a column.** Agree with your co-scorer who is `scorer1` and who is
   `scorer2`, and put your name in that column on every row you score.
2. **Read the whole conversation first.** Look it up by `curated_id` in
   `curated/CONVERSATIONS.md` in the
   [docs repo](https://github.com/marcomarchesanogenesys/uoft-ftli-2026-genesys-docs),
   or in `curated/conversations/<curated_id>.json`.
3. **Score all four categories.** Use exactly one of these values:

   | Value | Meaning |
   |---|---|
   | `pass` | The agent did what this category asks. Small slips that didn't affect the customer still pass. |
   | `needs_work` | There is a specific problem you can point to in the transcript. |
   | `cannot_assess` | The transcript doesn't give you enough to judge. This is **not** a failure. |

4. **Add notes for anything that isn't `pass`.** Write them in your notes
   column and cite line numbers (the `n` of each turn), e.g.
   `completeness: never confirmed the new address (n=14-16)`.
5. **Score on your own.** Don't look at the other scorer's columns or talk about
   a conversation until you've both finished it.
6. **Record disagreements.** Once both of you are done, go through every
   category where your values differ and write in `disagreement_notes` what
   the disagreement was about. If you talk it through and agree, write the
   agreed value there too. **Do not change your original scores**: the ML team
   needs the raw, independent scores to measure agreement.

When you're unsure between `needs_work` and `cannot_assess`, ask yourself: *is
there a line I can point to that shows the problem?* If yes, use `needs_work`.
If the problem would only show up in something the transcript doesn't
contain, use `cannot_assess`.

Judge only what's in the transcript. Don't guess at what happened off the
record, and don't penalise transcription noise (`[noise]`, `<unk>`, `uh`) or
typos.

## The two datasets

- **HarperValleyBank (`HVB-*`)** is short phone calls with a bank, transcribed
  from speech. Everything is lowercase with no punctuation, so don't mark
  communication down for that. `source_fields.task_assigned` says what the
  customer was there to do.
- **ABCD (`ABCD-*`)** is online chats with a retailer. `system_action` turns
  record what the agent did in their tools (e.g. *"Account has been pulled up
  for …"*), so you can see the order of steps. `source_fields.flow` and
  `subflow` say what the customer wanted.

## Categories

### 1. Procedure (`procedure_*`)

*Did the agent take the right steps, in a sensible order?*

- **pass**
  - The agent identifies the customer before acting on or sharing account
    details (asks for a name, username, email, order ID or similar). Then they
    do what the request needs and confirm it's done.
  - In ABCD, the `system_action` turns happen after the details they depend on
    are collected. For example, the account is pulled up after the name is
    given, and a refund is made after the order is validated.
- **needs_work**
  - The agent shares account details or makes a change before identifying the
    customer.
  - The agent skips a step the request clearly needs, e.g. a refund with no
    order lookup.
  - The agent does steps in an order that couldn't work.
  - The agent takes an action the customer didn't ask for or agree to.
- **cannot_assess**
  - The conversation ends before any procedure starts.
  - The request needs no procedure, e.g. a general question like branch hours
    or a return policy.

### 2. Answer support (`answer_support_*`)

*Is what the agent told the customer correct and supported?*

Look at every factual statement the agent makes: policies, times, fees,
balances, amounts, eligibility, next steps.

- **pass**
  - Each statement is consistent with the rest of the transcript. Amounts and
    details match what the customer gave and what the `system_action` turns
    show.
  - The agent avoids promising things they can't know.
- **needs_work**
  - The agent states something the transcript contradicts. For example, the
    agent says one amount and the system action shows another, or says
    "today" when an earlier turn said "5 to 7 days".
  - The agent gives two different answers to the same question.
  - The agent makes a guess sound like a fact ("it'll definitely arrive
    tomorrow").
- **cannot_assess**
  - The agent gives no factual answer.
  - Whether the answer is correct depends on a policy that neither the
    transcript nor the approved knowledge states. For example, a quoted
    shipping price you have no way to check.

### 3. Completeness (`completeness_*`)

*Was everything the customer asked for dealt with?*

- **pass**
  - Every request the customer raised is resolved, or the agent clearly says
    what will happen next.
  - The agent confirms the outcome before the call or chat ends.
  - In HVB, the task the customer came for (`task_assigned`) is the one that
    gets done.
- **needs_work**
  - A request is dropped or only partly handled.
  - The agent ends without confirming the outcome.
  - The agent handles a different task from the one the customer asked for.
  - The customer has to repeat a request the agent ignored.
- **cannot_assess**
  - The transcript is cut off.
  - So much of it is unintelligible that you can't tell whether the request
    was finished.

### 4. Communication (`communication_*`)

*Was the agent clear, polite and easy to follow?*

- **pass**
  - The agent greets the customer and stays polite and professional.
  - The agent explains things in plain language and acknowledges the customer's
    problem, especially if they're frustrated.
  - Questions are clear and asked one or two at a time.
- **needs_work**
  - The agent is rude, dismissive or blames the customer.
  - The agent uses confusing jargon without explaining it.
  - The agent asks for the same information more than once without reason.
  - The agent gives replies so curt or unclear that the customer is visibly
    confused.
- **cannot_assess**
  - There's too little agent speech to judge, e.g. a transcript that's mostly
    `[noise]`.

## Columns in `scoring_template.csv`

| Column | Filled by | Contents |
|---|---|---|
| `curated_id`, `source_dataset`, `topic`, `agent`, `turns` | already filled | Which conversation it is |
| `scorer1`, `scorer2` | each scorer | Your name |
| `procedure_scorer1` … `communication_scorer2` | each scorer | `pass`, `needs_work` or `cannot_assess` |
| `scorer1_notes`, `scorer2_notes` | each scorer | Reasons for anything not `pass`, with line numbers |
| `disagreement_notes` | both, after scoring | What you disagreed on and, if resolved, the agreed value |

The values match the audit's `FindingResult` (`pass`, `needs_work`,
`cannot_assess`), and the column prefixes match `FindingCategory`, so the ML
team can compare the two directly.
