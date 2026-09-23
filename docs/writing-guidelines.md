# Writing guidelines for generated bullets

Derived from a real failure: the tool's author rejected a generated resume as
"over-fit at the expense of sounding mechanical and fake," rewrote it by hand,
and the diff is the source of everything below.

Step 6 (telling generation) implements this. The eval harness should test it.

---

## The root error

**The coverage matrix decides WHAT goes on the resume. It must not decide HOW it
is written.**

The generator had a map of requirement → experience, and then kept going: it bent
each sentence until the requirement was textually visible in the bullet. Every
rejected phrase traces to that single mistake.

| Generated | Purpose it was actually serving | Verdict |
|---|---|---|
| "…where none existed" | make R12 (ambiguity) grep-able | cut by author |
| "…on a weekly cadence" | make R14 (operating cadence) grep-able | cut by author |
| "…rather than AI sophistication" | make R8 (first principles) grep-able | cut by author |
| "Identified the workflows costing the most time and producing the most data discrepancies, then built…" | front-load R8's reasoning | cut by author |

Once an experience covers a requirement, the requirement's job is done. The
sentence should then be written to communicate the work.

---

## Rules

### 1. Reasoning is interview material, not resume material

A bullet is **action + scope + outcome**. The judgment behind the action is the
best thing to say out loud when asked, and the worst thing to write on the page.

```
generated  Identified the workflows costing the most time and producing the most
           data discrepancies, then built 4+ AI tools to automate those
           specifically — removing an estimated 1,470+ hours…          (52 words)

author     Designed and launched 4+ AI tools to automate 1,470+ hours of manual
           data entry and content creation work across the Product Marketing
           org; won the company-wide All In (AI) award…                (38 words)
```

The selection logic is a strong interview answer. It is clutter in a bullet.

### 2. Never frame a bullet as an argument or a negative

```
generated  Argued against building features whose unit economics did not support
           them — including delivery — keeping the roadmap on features that could
           carry their own cost.
```

Cut by the author. Genuinely their strongest unit-economics story, and it reads
as strange on a page. Accomplishments are things done, not positions taken.

### 3. Watch for framings that misread against the employer

"…concluding the differentiator was speed and experience quality **rather than AI
sophistication**" was written to evidence first-principles thinking. To a company
whose JD mentions AI six times, it can read as *this candidate is sceptical of AI*
— a risk created for no gain. The author generalized it to "key differentiators".

Check generated framings against the employer's own stated values, not just
against the requirement being served.

### 4. Shorter. Then shorter again

Generated bullets averaged noticeably longer than the author's rewrite. Length
came from packing multiple requirements into one sentence. One bullet, one idea.

### 5. Do not cut bullets merely because they map to no requirement

A prior rule — "cut lowest tier first, unmapped first" — removed a win/loss
programme bullet (120+ customer interviews, 4 stakeholder groups) and an entire
job. The author restored both.

A resume is a career, not a requirement-coverage matrix. Unmapped bullets that
show scope, ownership, or range earn their place. Coverage is a floor, not a
filter.

### 6. Give the causal chain

```
generated  Rebuilt the Customer-Facing Product Roadmap program from 0 to 1,
           developing the SOPs and assets behind it; influenced $2.4M+ in closed
           opportunities.

author     Owned and operated the Customer-Facing Product Roadmap program 0->1 by
           developing SOPs and sales assets, providing collateral on upcoming
           feature releases that influenced $2.4M+ in closed opportunities.
```

The generated version asserts the number. The author's explains the mechanism by
which the work produced it — which is what makes it credible.

### 7. Preserve the user's own vocabulary

The author's rewrite restored specificity the generator had flattened: "Power
BI", "Databricks lakehouses", "manual data entry and content creation", "sales
assets", "collateral on upcoming feature releases".

Generic paraphrase reads as generated. The bank stores facts in the user's words
— use them rather than synonyms.

### 8. Do not add sections that were not asked for

A summary section was added to bridge a perceived positioning gap. The author
removed it and used the space for content.

---

## Implications for the build

**Step 6 (telling generation)** must receive the requirement as *context for
selection*, not as *text to satisfy*. Prompts should forbid restating the
requirement's own language, and should cap bullet length.

**Step 5 (gap detection)** should keep flagging coverage, but the tool must stop
treating unmapped content as deletable.

**The eval harness (step 2)** needs a quality check beyond factual accuracy. The
truth check catches invented numbers; it would have passed every sentence above.
Candidate assertions: bullet length ceiling, no requirement phrasing echoed
verbatim, no negative-framed openings, presence of a concrete outcome.

This is the gap the postmortem warned about — well-formed output that is wrong in
a way nothing automated notices.
