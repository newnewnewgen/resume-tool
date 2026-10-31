# resume-tool

Personal tool. Matches your experience against a job description, surfaces the gaps it
can't cover, and builds an ATS-parseable resume.

See [SPEC.md](SPEC.md) for the full design, and [docs/process.md](docs/process.md)
for the standard per-application run (what the tool automates step by step).

## Status

**Build steps 1–3 complete** — schema, storage, deterministic ingest, ATS-safe rendering,
and the eval harness with its golden set. No LLM dependency yet; nothing here needs an API key.

| Step | | |
|---|---|---|
| 1 | Schema + SQLite + ingest resume → Experiences | ✅ done |
| 2 | Eval harness + golden set | ✅ done |
| 3 | ATS round-trip test + docx writer | ✅ done |
| 4 | JD → tiered requirements | ✅ built — acceptance eval vs the hand-made worksheets runs with an API key |
| 5 | Retrieval + gap detection | |
| 6 | Telling generation + reuse + truth check | |
| 7 | Assembly | |
| 8 | CLI polish | |

No UI until 1–7 pass.

## The model

Facts are durable, narrative is disposable.

```
Job              employer, title, dates
 └─ Experience   what actually happened. FACTS. written once, never rewritten.
     └─ Telling  one framing of it, for one angle. many per Experience. regenerable.
```

Because the durable layer holds facts rather than prose, it never goes stale. Framing is
regenerated per application and thrown away.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Use

```bash
resume init                      # create the database
resume ingest my-resume.pdf      # parse → draft.yaml (does NOT touch the database)
$EDITOR draft.yaml               # review and correct — this is the point
resume commit draft.yaml         # validate and import
```

Parsing is heuristic and will misread unusual layouts. Nothing reaches the database
without passing through a file you edit; uncertain guesses are flagged in `notes`.
Re-committing an edited draft is safe — existing entries are skipped, not duplicated.

### Inspecting

```bash
resume jobs
resume experiences [--job 1]
resume show EXP-001
resume stats
```

### Loading a filled worksheet

```bash
resume load-worksheet worksheets/myjob.filled.yaml
```

Writes the worksheet's jobs, experiences and facts into the bank. Idempotent —
re-run after editing and only new entries land.

### Parsing a job description (step 4 — needs Anthropic credentials)

```bash
resume parse-jd jd.txt                 # → worksheets/<company>.yaml, screenable bar applied
resume parse-jd jd.pdf --store         # also store application + requirements in the bank
resume eval-jd worksheets/figma.yaml worksheets/figma-apm-2027.yaml   # score vs a hand-built reference
```

The model and token budget come from `$RESUME_TOOL_MODEL` / `$RESUME_TOOL_MAX_TOKENS`
(defaults in `config.py`), never from code. The two committed templates are the
acceptance references: run the same JD through `parse-jd` and `eval-jd` scores
requirement coverage, tiering agreement, and knockout extraction against them.

### Scoring retrieval against the golden set

```bash
resume eval                        # evals/golden.yaml under the keyword baseline
resume eval --fail-under 75       # CI mode: exit 1 below 75% accuracy
```

Runs requirement → experience retrieval against cases with known answers, in a
throwaway in-memory bank. A forced match — an expected gap answered with a
confident candidate — always fails the run. See [evals/README.md](evals/README.md).

### Checking a document for ATS problems

```bash
resume lint my-resume.docx
```

Flags tables, text boxes, images, multi-column layout, contact details stranded in
a page header, missing email, nonstandard section headings, and Word list bullets
that vanish from extracted text. Exits non-zero on anything blocking.

### Manual entry

```bash
resume add-job
resume add-experience --job 1
resume add-fact EXP-001 --kind technology --value Kubernetes
```

Fact kinds: `metric`, `technology`, `scope`, `collaborator`, `outcome`.
Facts are what the truth check will verify generated text against in step 6 — every
number and technology in a bullet must trace back to one.

## Database location

`~/.resume-tool/bank.db`, overridable with `$RESUME_TOOL_DB` or `--db`.
The bank is personal data and is gitignored.

## Tests

```bash
.venv/bin/python -m pytest
```

158 tests, no network, no API key — the LLM seam is a plain callable, so
everything after the model (validation, rendering, storage, the acceptance
comparator, the v1→v2 schema migration) is tested with canned output.
