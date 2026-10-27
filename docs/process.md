# The standard run

The canonical per-application process, standardized from the first full run
(Figma APM, Oct 2026 — see `assembly-learnings.md`). Steps marked **[manual]**
are done by hand or in conversation until the corresponding build step
automates them; the phase structure is the contract either way.

## Standing rules (always on, every phase)

- **Truth boundary.** The system reframes; it never invents. A blank is
  output, not a failure. Zero forced matches, enforced by the eval harness.
- **Privacy boundary.** Real career data lives only in gitignored files
  (`*.filled.*`, `worksheets/private/`, the bank DB) and scratch space. The
  public repo gets rules and synthetic equivalents only.
- **Metric hygiene.** A number enters the bank with its period, denominator,
  and baseline, or it is stored as a claim and flagged. Challenges are cheap
  at capture time and expensive at review time.
- **Versioned, verified delivery.** Every artifact ships under a versioned
  name, and only after the requested change is asserted present in the
  *extracted output* — never trusted from the source edit alone.
- **Relevance beats impressiveness** whenever the two conflict.

## Phase 0 — Intake [manual until step 4]

1. Paste the JD. Generate the requirements worksheet: knockouts first, then
   requirements tiered critical / important / nice_to_have, each with the
   JD's evidence quoted.
2. Apply the screenable bar (worksheets/README.md): a requirement must be
   verifiable from a resume bullet or a portfolio link. Soft JD language is
   translated to its observable proxy; what cannot be translated goes in a
   `signals:` section, outside the match list.
3. Author answers the knockouts before anything else is written. A failed
   knockout ends the run here.

## Phase 1 — Coverage [manual until step 5]

4. Fill the worksheet conversationally, one requirement at a time. Stories
   are filed against requirements; a story that does not answer its
   requirement is re-homed or parked, never left mis-filed.
5. Blanks are confirmed as gaps, explicitly and in writing. Critical gaps
   get the author's attention (fill with a real story, or accept); lower
   tiers are report-and-skip.
6. New stories flow into the bank as facts, through write classification:
   new experience, new telling of an existing one, or correction.

## Phase 2 — Assembly [manual until steps 6–7]

7. Decide the **narrative frame first**, as its own decision: which titles
   and dates (facts — verifiable against HR records), which section order,
   what leads the page, what the top third must say. The biggest levers are
   structural, not sentence-level.
8. Select content: coverage is the floor, relevance is the filter, and
   unmapped bullets that show scope or range still earn their place
   (writing-guidelines rule 5).
9. Generate tellings at the **shortest defensible length** — the author
   always trims harder than expected — obeying writing-guidelines plus the
   page-vs-pocket rule: one clause of mechanism on the page, the rest held
   for interviews. If a link can carry the proof, the bullet does not
   retell it.
10. Render through the writer and pass the four gates, every iteration:
    round-trip PASS, ATS lint clean, page count = 1, requested edits
    asserted in the extracted text. On overflow, use layout levers (tight
    mode, spacing, link labels, margins) before cutting content; when
    content must go, cut by relevance.

## Phase 3 — Review

11. **Cold-reader pass** (now SPEC pipeline step 9): at least one reviewer
    with the JD and the rendered resume only — no conversation context.
    Separate briefs where useful: line-level credibility, then structural.
12. Findings are proposals, not verdicts. Present them with costs; the
    author accepts or rejects; record both. The accept/reject log is
    labeled training data for the eval harness.
13. Iterate in the seven-pass order (assembly-learnings.md): requirement
    quality → coverage → defensibility → narrative frame → relevance →
    personality → visual polish. Personality goes last and low-stakes;
    polish strictly after content settles.

## Phase 4 — Ship and learn

14. Submit. Record what shipped: which tellings, which version, where it
    went — the bank's answer to "which version did I send to Stripe?"
15. Harvest the run: author rejections become documented rules; tool
    friction becomes writer/lint/eval features, committed before the run is
    considered closed; new requirement→story pairs become golden-set
    candidates (synthetic equivalents only).

## Build-step mapping

| Phase | Automated by |
|---|---|
| 0 Intake | Step 4 (JD → tiered requirements) — hardest part is the screenable translation |
| 1 Coverage | Step 5 (retrieval + gap detection) scored by the step-2 harness |
| 2 Assembly | Step 6 (telling generation + truth check) and step 7 (assembly + gates) |
| 3 Review | New pipeline step 9: cold-reader pass; verdict log feeds the harness |
| 4 Ship/learn | Bank bookkeeping (`requirement_match`, telling versioning) + this docs loop |
