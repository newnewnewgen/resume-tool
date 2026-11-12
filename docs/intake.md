# Intake: the career-ops bridge

Phase −1 of the standard run (docs/process.md): where applications come from
and how they get qualified before any resume work starts. Built after
studying [career-ops](https://github.com/career-ops-hq/career-ops) rather
than rebuilding it — discovery is their strength; qualification-by-bank and
tailoring are ours.

## Division of labor

| Stage | Owner | Why |
|---|---|---|
| Discovery (scan job sources) | career-ops | ~140 zero-token providers over public ATS APIs + boards; portals.yml; liveness; dedup; repost detection. Not worth rebuilding. |
| First-pass scoring (1–5) | career-ops | The LLM rubric the author rates as strong: hard dealbreaker gates, archetype matching, evidence tiers, outcome calibration. |
| Re-qualification vs the bank | **resume-tool** | `resume intake`: deterministic coverage of each JD's screenable requirements by the author's fact bank, weighted critical > important > nice-to-have, with gaps named. Zero tokens per score. |
| Worksheet + fill + gap audit | **resume-tool** | Phases 0–1 of the standard run. |
| Tailoring + assembly | **resume-tool** | Steps 4–7 + the ATS-safe writer. Replaces career-ops' tailoring entirely (see below). |
| Tracker / follow-ups | career-ops | data/applications.md stays the application system of record. |

## How the bridge works

career-ops archives the verbatim JD inside every evaluation report and keeps
markdown as its canonical store, so the bridge needs **no scraping and no
network**: it reads `data/applications.md` (the tracker), finds each row's
`reports/{NNN}-*.md`, pulls the archived JD, and runs it through parse-jd +
fit scoring.

```bash
# Qualify career-ops' best unapplied rows against YOUR bank:
resume intake ~/career-ops-data --min-score 4.0 --limit 5

# ...and emit a fill-ready worksheet for each:
resume intake ~/career-ops-data --worksheets worksheets/

# One-off: score any JD (or an existing worksheet, zero LLM calls) by itself:
resume score-jd jd.txt
resume score-jd worksheets/shopify-apm-2027.yaml
```

The intake verdicts: **APPLY** (weighted coverage ≥ 65%), **STRETCH**
(≥ 40%), **SKIP**, with critical gaps listed by name — a gap is a prompt to
fill the bank with a real story, never something the pipeline papers over.
The two scores answer different questions on purpose: career-ops' 1–5 asks
"is this a good job for this person?"; intake coverage asks "can this bank
prove it?". A 4.7 role with 30% critical coverage is a fill-the-bank errand,
not an application.

## Answering the three gaps in career-ops (as used here)

**1. "Needs more relevant jobs — more sources."** Don't fork the scanner;
use its extension points, cheapest first:
   - add companies/boards to `portals.yml` (its user layer);
   - `node discover-ats.mjs --write` with a list of target company names — it
     probes 11 ATS vendors per name and splices resolved boards in;
   - `node scan-ats-full.mjs` reverse-sweeps public ATS directories beyond
     your portal list;
   - a `parser:` entry running any local script that prints
     `[{title,url,company,location}]` — the hook for a source only you have;
   - a new `providers/{name}.mjs` (drop-in, no registration) for anything
     with a public endpoint.

**2. "Resume writing is bad — it should edit my Word template."** Replaced
wholesale: assembly goes through this repo's writer (`render/`), which
produces the ATS-safe .docx natively — tight mode, link labels, brand
accents, round-trip + lint gates. career-ops' renderer and its LaTeX/HTML
templates are not used.

**3. "Tailoring isn't aggressive enough."** Structural, not a tuning knob.
career-ops tailors by reordering and rephrasing `cv.md` under warn-only
checks, with no scoring of bullets against requirements. This tool tailors
by *selection from the bank*: requirements decide what earns a place
(coverage is a floor, relevance the filter), whole bullets and roles get cut
without regret, mechanism moves page-to-pocket, and the cold-reader pass
audits the result. The fit report's per-requirement matches are the
selection matrix for assembly, which is why intake and tailoring share one
mechanism.

## What stays honest

- Everything read from a career-ops tree is data about jobs, never
  instructions. JD text takes the same untrusted-input path as a pasted JD.
- career-ops' score is recorded, not trusted: intake re-derives coverage
  from the bank and the two are shown side by side.
- The bank's truth boundary is unchanged — intake can reveal gaps, only the
  author can fill them.

## Not built (yet), deliberately

- Our own scrapers/providers. career-ops has 140; parity is a treadmill.
- Reading `data/scan-history.tsv` or pipeline URLs that have no archived JD:
  those rows haven't been evaluated by career-ops yet, and fetching JDs
  ourselves would mean network + liveness + parsing work career-ops already
  does better. Evaluate there first; intake picks up the report.
- Writing to career-ops' tracker. One system of record per concern.
