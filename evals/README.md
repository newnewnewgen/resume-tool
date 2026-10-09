# Evals

The golden set: requirement → expected-experience pairs with known answers,
plus the synthetic bank they resolve against. Build step 2; step 5's retrieval
is tuned against it.

```bash
resume eval                     # score the baseline against evals/golden.yaml
resume eval --fail-under 75     # CI mode: exit 1 below 75% accuracy
```

## What gets measured

- **Accuracy** — for each case, is an expected experience in the top-k (or,
  for gap cases, was the gap flagged)?
- **False gaps** — a real answer the retriever was too timid to surface.
- **Forced matches** — an expected gap answered with a confident candidate.
  This is v1's worst failure (a missing capability silently became a weak
  bullet), so one forced match fails the run regardless of accuracy.

## The baseline

`resume_tool/retrieval.py` is a stemmed keyword-overlap retriever with no LLM
and no embeddings. It is deliberately weak: its score is the floor step 5's
hybrid retrieval has to beat, and the paraphrase cases it loses (marked with
notes in `golden.yaml`) are the justification for building step 5 at all.

## Why the bank is synthetic

This repository is public, so the committed set uses an invented persona
shaped like the real use case. A golden set built from your real history is
more honest about retrieval quality — keep it in `evals/private/` or under a
`*.filled.*` name, both gitignored, and point the command at it:

```bash
resume eval evals/private/mine.yaml
```

## File format

Self-contained on purpose — the eval builds a throwaway in-memory bank, so it
never touches your real database.

```yaml
jobs:
  - ref: acme                # experiences refer to this
    employer: Acme
    title: Analyst
    start_date: 2020-01

experiences:
  - ref: sql-pipeline        # cases refer to this
    job: acme
    summary: >
      What actually happened, facts only.
    facts:
      - kind: technology     # metric | technology | scope | collaborator | outcome
        value: SQL

cases:
  - id: G1
    tier: critical           # critical | important | nice_to_have
    requirement: Complex SQL across multiple data sources
    expect: sql-pipeline     # a ref, a list of refs (any counts), or `gap`
    note: optional — why this case is in the set
```
