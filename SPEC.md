# Resume Tool — Build Spec

**Scope: personal tool.** Single user, local, no auth, no hosting, no web UI.
SQLite file + CLI. Core logic stays UI-agnostic so an interface is additive later,
but none gets built until the engine is testable and stateful.

Supersedes RAGResume. See `ultimateresume/POSTMORTEM.md` for why.

---

## Goal

A resume that matches the JD.

## Blockers this must solve

1. **Surface gaps.** The JD asks for things my resume doesn't show but I have done. I need
   to be told what's missing so I can write it.
2. **Stop context going stale.** Know when a new write is a *new experience* vs. a *new
   telling of an existing one* vs. a *correction to one*.
3. **Cut edit/rewrite time.** Reuse what's already written instead of regenerating.
4. **Guarantee ATS parseability**, with an actual test — not an assertion.

---

## The core idea

**Facts are durable. Narrative is disposable.**

Everything else follows from this. An Experience holds what actually happened; a Telling
holds one framing of it. Facts never go stale, so blocker 2 dissolves — the durable layer
is never rewritten, and the disposable layer is cheap to regenerate from it.

```
Job              employer, title, dates, location
 └─ Experience   the thing that happened. FACTS. canonical. written once.
     └─ Telling  one framing, for one angle. many per Experience. regenerable.
```

---

## Data model

```sql
job(id, employer, title, start_date, end_date, location)

-- Canonical. Facts only. Never rewritten for an application.
experience(id, job_id, summary, created_at, updated_at)

-- Structured facts, separately queryable. Powers the truth check.
experience_fact(id, experience_id, kind, value)
  -- kind: metric | technology | scope | collaborator | outcome

experience_embedding(experience_id, vector)   -- for experience↔experience dedup

-- One framing. Reusable across applications.
telling(id, experience_id, text, angle, created_at)
  -- angle: what this framing emphasizes, e.g. "cross-functional leadership"

application(id, company, role_title, jd_text, created_at, status)

requirement(id, application_id, text, tier, kind)
  -- tier: critical | important | nice_to_have
  -- kind: knockout | skill | quality

-- User decisions. Persistent. Survive re-runs.
match(id, requirement_id, experience_id, telling_id, state)
  -- state: proposed | approved | rejected | gap
```

`match` is the fix for v1's worst UX failure: decisions were disposable, so changing one
word in the JD discarded every selection. Here they persist and are re-validated, not
re-made.

---

## Pipeline

```
1. ingest JD                → requirements, tiered and typed
2. knockout check           → fail fast, before spending anything
3. retrieve per requirement → candidate experiences (hybrid: semantic + keyword + context)
4. classify each            → strong match | weak match | GAP
5. user review              → approve / reject / FILL GAP (writes a new Experience)
6. telling                  → reuse existing if angle fits, else generate
7. assemble                 → .docx
8. ATS round-trip test      → pass/fail with specifics
```

**Step 5 is the whole product.** v1 force-matched every requirement to the best of three
candidates even when none fit, so a missing capability silently became a weak bullet. Here a
gap is a first-class output, and filling it creates a new Experience that flows back into
the bank — so the same gap is never surfaced twice. That loop is what makes the tool
compound with use instead of being a nicer form.

### Gap priority

Tier drives *which gaps are worth stopping for*, not just keyword weight. A gap on a
critical requirement halts for input. A gap on a nice-to-have is reported and skipped.
Without this you get handed 15 gaps and abandon the run, which defeats blocker 3.

### Write classification (blocker 2)

When the user writes something new, compare against existing **Experiences** (not
Tellings). Present a three-way choice — never auto-resolve:

1. **New Experience** — genuinely new
2. **New Telling of an existing Experience** — same event, different angle
3. **Fact correction** — a detail changed or was remembered

This is where embeddings earn their place. Experience↔experience dedup is a much better
job for them than the JD↔bullet matching v1 used them for, where hybrid scoring had to
rescue them.

### Truth boundary

The system surfaces the gap and asks *the user* for the fact. **It reframes; it never
invents the experience.** Enforced by test, not by hope — see below.

---

## Testing

The harness exists before the second prompt. This is learning #1 from the postmortem and
non-negotiable; its absence caused the five-times truncation bug, weeks of invisible
context gaps, and the prompts-patching-prompts spiral.

| Test | Asserts |
|---|---|
| **Retrieval** | golden (requirement → expected experience) pairs; correct experience in top-k |
| **Gap detection** | requirements with no true story are flagged as gaps, never force-matched |
| **Truth** | every number and technology in a Telling appears in that Experience's `experience_fact` rows |
| **ATS round-trip** | generate .docx → parse → assert fields recovered intact |

The truth test is what makes the truth boundary real rather than aspirational: extract
entities from generated text, assert each traces to a stored fact. A hallucinated metric
fails the build.

### ATS test, concretely (blocker 4)

**Round-trip.** Generate the .docx → extract text the way a parser does → re-parse into
structured fields → assert what comes back matches what went in. If a job title vanishes,
dates mangle, or two roles merge into one, the layout is broken.

**Static lint** before anything ships: no tables, no text boxes, nothing load-bearing in
headers/footers, single column, standard section headings, standard date format, contact
info in the body.

This is the only part of the system with an objectively correct answer. It's deterministic,
needs no LLM, and runs in CI — exploit that.

---

## Stack

- Python, SQLite, CLI (`typer`)
- `python-docx` for output
- `pytest` for the harness
- One LLM provider behind a thin interface; **model IDs and token budgets in config, not
  constants** (learning #6 — v1 hardcoded them and a mid-project deprecation touched core
  logic)
- Embeddings as blobs + numpy brute force. At ~50–200 experiences a vector DB is
  infrastructure for a problem that doesn't exist yet.

---

## Build order

Deliberate: the deterministic, LLM-free pieces come first so the output format is de-risked
before anything depends on it.

1. **Schema + SQLite + ingest existing resume → Experiences.** No LLM writing. Get the
   bank populated and inspectable.
2. **Eval harness skeleton + golden set.** ~10 requirement/experience pairs with known
   answers.
3. **ATS round-trip test + docx writer.** Pure, deterministic, no LLM. Kills blocker 4
   before anything is built on top of it.
4. **JD → tiered requirements.**
5. **Retrieval + gap detection.** Where the golden set pays off.
6. **Telling generation + reuse + truth check.**
7. **Assembly.**
8. **CLI polish.**

No UI until 1–7 pass.

---

## Target interaction

```
$ resume apply --jd ./jd.txt

Knockouts: PASS (3/3)

CRITICAL (4)
  ✓ Kubernetes at production scale   → EXP-012 (0.84)  reusing telling T-031
  ✓ Cross-functional leadership      → EXP-004 (0.79)  new telling
  ⚠ Terraform / IaC                  → EXP-008 (0.41)  weak — confirm or fill
  ✗ FedRAMP compliance               → NO STORY        gap

IMPORTANT (6) …

2 critical gaps. Fill now? [y/N]
```

Filling prompts for the fact, creates an Experience, links the match, and it's in the bank
permanently.

---

## Explicitly out of scope

Auth. Hosting. Multi-user. Web UI. A WYSIWYG designer. LaTeX. Cover letters.

v1 built most of these for a system with one user. "For now" means keep the core
UI-agnostic — which is free — and add nothing else speculatively.


## Writing quality

See [docs/writing-guidelines.md](docs/writing-guidelines.md) — derived from the
author rejecting the first generated resume as "mechanical and fake". Core rule:
the coverage matrix selects what goes on the page; it must not shape how the
sentence is written.
