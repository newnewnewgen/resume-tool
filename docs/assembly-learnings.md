# Learnings from the first full assembly (Figma APM, Oct 2026)

The first end-to-end run of the manual pipeline: worksheet → fill → gap audit →
assembly → review → submit. Seventeen-plus versions, three fresh-context
reviews, and roughly forty author edits. This document records what the
author's edits revealed, because they are the ground truth steps 4–7 must
reproduce.

## The author's actual process (reconstructed from the edit sequence)

The edits were not random polish. They came in distinct passes, each with one
objective, in this order:

1. **Requirement quality** — rejected JD-copied requirements as "too soft";
   forced the screenable-evidence bar (now in worksheets/README.md).
2. **Coverage** — filled the worksheet, confirmed gaps explicitly rather than
   papering over them.
3. **Defensibility** — every number got interrogated or died: 1,470+ hours
   became 360/quarter (period added), "4 key accounts" became unquantified
   (count was wrong), 22x was dropped entirely rather than defended, "8+"
   became "8".
4. **Narrative frame** — job titles, section order, and bullet *focus*
   (discovery-and-research vs. strategy) were edited as a separate concern
   from bullet quality. The biggest levers of the whole exercise were never
   sentences: they were a title, a section order, and which project led.
5. **Relevance pruning** — strong bullets (Power BI dashboards, 15x LVR
   pipelines, a $25M fraud-model win) were cut *because* they served the
   candidate in general rather than this JD. Impressiveness lost to relevance
   every time they conflicted.
6. **Personality** — added last, only in low-stakes sections (Leadership),
   only as named specifics (Geary, Beyblade), never near a dollar figure.
7. **Visual polish** — typography, brand accents, hyperlinks. Strictly last.

Steps 4–7 of the build should mirror this ordering. In particular: narrative
framing (pass 4) is a first-class output of assembly, not a side effect of
bullet selection.

## The page-vs-pocket rule (the author's core heuristic)

The single most repeated edit: **move mechanism off the page and into the
interview.** "Don't mention the middle part because that can go in an
interview." The engineering-tradeoff story, the k-means method, Treesumé's
trunk/branch/merge mechanics, the Figma parallel ("too on the nose") — all
deliberately withheld. The resume's job is to earn the conversation; detail
held back is interview ammunition, not lost value.

This *extends* writing-guidelines rule 1 (reasoning is interview material):
mechanism beyond one clause is interview material too. A bullet is a headline
with one number; if a link can carry the proof (a live app, a case study),
the bullet should not retell it.

Corollary observed twice: when the author trims a line, they trim harder than
the generator expects. Generate the shortest defensible telling first; offer
the longer one as the alternative, not the default.

## Reviewer feedback is a proposal, not a verdict

Three fresh-context reviews (JD + resume only, no conversation history) were
the highest-value quality step in the run — they caught the number-credibility
pattern, the title framing problem, and the buried-evidence problem, none of
which inside-context editing had seen. **A cold-reader pass belongs in the
pipeline** (after step 7 assembly, before output): same bank, zero
conversation context, JD only.

But the author accepted roughly 60% of reviewer findings and rejected the
rest on consistent grounds: reviewers optimize for legibility to reviewers;
the author optimized for authenticity and the interview funnel. Rejected:
projects-before-experience, naming Figma in a bullet, keeping mechanism in
Treesumé. Accepted: education-on-top, number audits, the vague-bullet rewrite.
The accept/reject record is labeled training data — the eval harness should
eventually score generated findings against author verdicts, the same way the
golden set scores retrieval.

## Facts must be captured with denominator and period

Every number that later failed review failed the same way: it was stored as a
telling ("1,470+ hours", "22x", "78% adoption") without its denominator,
period, or baseline. The challenge always came eventually — better at
fact-capture time than at review time. Worksheet and ingest prompts should
demand, for every metric fact: **over what period, out of what denominator,
against what baseline.** A metric that cannot answer those is stored as a
claim, not a fact, and flagged.

## Version control was reinvented ad hoc

Seventeen versions shipped as v5…v17 + FINAL filenames; identical filenames
early on caused a real "it hasn't changed" confusion. Tellings need
versioning in the bank (which telling shipped to which application), and the
delivery convention is: versioned filename, every artifact verified in the
*output* (extract and assert the edit landed) before sending. The author's
own product thesis — trunk/branches/diffs for resumes — is this exact gap.

## Assembly is a layout problem, not just a selection problem

One page is a hard constraint, and it shaped content decisions (what got cut,
what got merged) as much as relevance did. Chasing line-wrap boundaries with
wording edits was the wrong tool every time; the right tools were layout
knobs (tight spacing, 0.97 line spacing, margins, hyperlink labels replacing
URL lines) — which now exist in the writer. Step 7 needs a line-budget check
(render → page count) in the loop, not as a post-hoc manual step, and should
prefer layout levers over content cuts, surfacing a ranked cut list only when
layout is exhausted.

## What worked and should be kept

- The gap audit as a conversation: misfiled stories (a collateral story under
  "customer contact") were detected and re-homed; blanks were confirmed as
  gaps, never filled by generation. Zero forced matches survived to the page.
- Teaching by example: the author corrected by rewriting one bullet, and the
  correction generalized. Treat every author rewrite as a few-shot example
  for the next generation pass.
- The validation loop per iteration: build → round-trip → lint → PDF page
  count → assert the edit text appears in extracted output. Cheap, caught
  real regressions, never shipped a broken file.
- Privacy boundary held: all real career data stayed in gitignored files and
  the scratchpad; the repo got only synthetic equivalents and rules.
