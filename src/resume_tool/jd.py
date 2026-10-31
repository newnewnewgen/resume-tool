"""Step 4: a job description → tiered, screenable requirements.

The hard part is not extraction, it is translation (worksheets/README.md):
a requirement must be verifiable from a resume bullet or a portfolio link,
soft JD language becomes its observable proxy, and what cannot be translated
is a signal, not a requirement. The prompt carries that bar; the code here
validates structure, renders the worksheet, and stores the result — it never
trusts the model's output shape.

The committed hand-built worksheets (worksheets/*.yaml) are the acceptance
references: `resume eval-jd` scores a generated worksheet against one.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import store
from .llm import CompleteFn, complete
from .models import RequirementKind, Tier


class JDParseError(ValueError):
    """Raised when the model's output cannot be validated into a worksheet."""


# ── Shapes ──────────────────────────────────────────────────────────────────


@dataclass
class Knockout:
    id: str
    requirement: str
    evidence: str


@dataclass
class Requirement:
    id: str
    tier: Tier
    kind: RequirementKind
    requirement: str
    evidence: str
    note: str | None = None


@dataclass
class Signal:
    id: str
    signal: str
    prep: str


@dataclass
class ParsedJD:
    company: str
    role_title: str
    location: str | None
    knockouts: list[Knockout] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)

    def by_tier(self, tier: Tier) -> list[Requirement]:
        return [r for r in self.requirements if r.tier == tier]


# ── Prompt ──────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You turn a job description into a requirements worksheet \
for a resume-tailoring tool. Your output is JSON only — no prose, no fences.

THE QUALITY BAR (non-negotiable): every requirement must pass one test — a \
resume screener could verify it from a resume bullet or a portfolio link. \
JD lines that fail the test are NOT requirements:
- "excitement about X" → translate to: a named, hands-on project in X
- "a knack for design" → translate to: a reachable portfolio artifact
- "a love for users/customers" → translate to: worked directly with users on \
a decision
- "deeply technical" → translate to: built something technically non-trivial
What cannot be translated (essay fields, interview demeanor, communication \
quality) goes in "signals", never in "requirements".

KNOCKOUTS are binary eligibility checks (work authorization, location, \
degree, deadline, years-of-experience floors). They are answered yes/no \
before anything is written.

TIERS: "critical" = explicitly screened for, a gap likely costs the role; \
"important" = strongly implied, gaps survivable but visible; \
"nice_to_have" = differentiator only.

KINDS: "skill" = a thing done; "quality" = a trait, but still phrased \
screenably (e.g. "ramped on an unfamiliar domain fast — a concrete instance \
with a timeframe"); "domain" = sector or product-type familiarity.

EVIDENCE: quote the JD's own words (trimmed) for every knockout and \
requirement, so the author can check your reading. Add a short "note" only \
when it changes how the author should answer (e.g. "they want a number you \
owned and moved — baseline, change, result"). Requirements asking for \
metrics should note that a metric needs its period, denominator and \
baseline.

Aim for roughly 4 knockouts, 5-8 critical, 4-6 important, and 2-5 \
nice_to_have requirements, merging JD lines that screen for the same thing. \
Also extract company, role_title, and location from the JD when present.

OUTPUT exactly this JSON shape:
{
  "company": "...",
  "role_title": "...",
  "location": "..." | null,
  "knockouts": [{"id": "K1", "requirement": "...", "evidence": "..."}],
  "requirements": [{"id": "R1", "tier": "critical", "kind": "skill",
                    "requirement": "...", "evidence": "...", "note": null}],
  "signals": [{"id": "S1", "signal": "...", "prep": "..."}]
}

Worked example of the translation, from a real JD:
- JD: "Excitement about shaping how design evolves in an AI-powered world"
  → requirement: "A named, hands-on project in design systems, AI-in-design,
    or design-to-code" (kind: skill, tier: critical), and separately a
    signal: "AI conviction — evaluated in conversation; prep is an opinion
    formed by building."
- JD: "A knack for visual design" → requirement: "A reachable portfolio
  artifact — interfaces or prototypes you made" (the form's portfolio field
  is where the 'knack' is actually checked)."""


def _build_prompt(jd_text: str) -> str:
    return f"THE JOB DESCRIPTION:\n\n{jd_text.strip()}\n\nReturn the JSON."


# ── Parse & validate ────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-z]*\n|\n```$", re.MULTILINE)


def parse_jd(jd_text: str, complete_fn: CompleteFn = complete) -> ParsedJD:
    """Run the JD through the model and validate the result strictly."""
    if not jd_text.strip():
        raise JDParseError("the job description is empty")

    raw = complete_fn(SYSTEM_PROMPT, _build_prompt(jd_text))
    stripped = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise JDParseError(f"model did not return valid JSON: {exc}") from exc
    return _validate(data)


def _validate(data: object) -> ParsedJD:
    if not isinstance(data, dict):
        raise JDParseError("output must be a JSON object")

    company = str(data.get("company") or "").strip()
    role_title = str(data.get("role_title") or "").strip()
    if not company or not role_title:
        raise JDParseError("company and role_title are required")
    location = str(data.get("location") or "").strip() or None

    seen_ids: set[str] = set()

    def _id(entry: dict, where: str) -> str:
        value = str(entry.get("id") or "").strip()
        if not value:
            raise JDParseError(f"{where}: id is required")
        if value in seen_ids:
            raise JDParseError(f"duplicate id {value!r}")
        seen_ids.add(value)
        return value

    def _text(entry: dict, key: str, where: str) -> str:
        value = " ".join(str(entry.get(key) or "").split())
        if not value:
            raise JDParseError(f"{where}: {key} is required")
        return value

    knockouts = []
    for i, entry in enumerate(data.get("knockouts") or []):
        where = f"knockouts[{i}]"
        if not isinstance(entry, dict):
            raise JDParseError(f"{where} must be an object")
        knockouts.append(Knockout(
            id=_id(entry, where),
            requirement=_text(entry, "requirement", where),
            evidence=_text(entry, "evidence", where),
        ))

    requirements = []
    for i, entry in enumerate(data.get("requirements") or []):
        where = f"requirements[{i}]"
        if not isinstance(entry, dict):
            raise JDParseError(f"{where} must be an object")
        try:
            tier = Tier(str(entry.get("tier") or "").strip())
        except ValueError:
            raise JDParseError(
                f"{where}: tier={entry.get('tier')!r} is invalid — use "
                f"{', '.join(t.value for t in Tier)}"
            ) from None
        try:
            kind = RequirementKind(str(entry.get("kind") or "").strip())
        except ValueError:
            raise JDParseError(
                f"{where}: kind={entry.get('kind')!r} is invalid — use "
                "skill, quality or domain"
            ) from None
        if kind == RequirementKind.KNOCKOUT:
            raise JDParseError(f"{where}: knockouts belong in the knockouts list")
        note = " ".join(str(entry.get("note") or "").split()) or None
        requirements.append(Requirement(
            id=_id(entry, where), tier=tier, kind=kind,
            requirement=_text(entry, "requirement", where),
            evidence=_text(entry, "evidence", where), note=note,
        ))

    signals = []
    for i, entry in enumerate(data.get("signals") or []):
        where = f"signals[{i}]"
        if not isinstance(entry, dict):
            raise JDParseError(f"{where} must be an object")
        signals.append(Signal(
            id=_id(entry, where),
            signal=_text(entry, "signal", where),
            prep=_text(entry, "prep", where),
        ))

    if not knockouts:
        raise JDParseError("no knockouts found — every JD has eligibility checks")
    if len(requirements) < 3:
        raise JDParseError(f"only {len(requirements)} requirement(s) — too few to be a real parse")
    if not any(r.tier == Tier.CRITICAL for r in requirements):
        raise JDParseError("no critical-tier requirements — tiers were not applied")

    return ParsedJD(company=company, role_title=role_title, location=location,
                    knockouts=knockouts, requirements=requirements, signals=signals)


# ── Worksheet rendering ─────────────────────────────────────────────────────

_HOW_TO_USE = """\
# ─────────────────────────────────────────────────────────────────────────────
# HOW TO USE THIS
#
# Copy this file to a gitignored name first — this repo is public:
#     cp {name} {stem}.filled.yaml
#
# Under each `your_experience:`, write ONE concrete thing you actually did.
#   - Facts, not framing. What happened, the numbers, the tools, who was involved.
#   - Every metric needs its period, denominator and baseline — it will be
#     challenged later if it doesn't have them now.
#   - LEAVE IT BLANK if you have no real story. Blanks are the most useful output
#     here — they are the gaps, and a blank critical gap is worth more of your
#     attention than a filled nice-to-have.
#
# ── YAML: use a `|` block, not quotes ───────────────────────────────────────
#
# Replace   your_experience: ""
# with      your_experience: |
#
# and indent your text under it. Spaces only, never tabs. Check before
# sending back:
#
#     python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" FILE.yaml
#
# Tiers:  critical = screened for, gap likely costs you the role
#         important = strongly implied, gaps are survivable but visible
#         nice_to_have = differentiator only
# ─────────────────────────────────────────────────────────────────────────────
"""


def _q(value: str) -> str:
    """A YAML-safe double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def render_worksheet(parsed: ParsedJD, filename: str = "worksheet.yaml") -> str:
    """Render a ParsedJD as a worksheet in the hand-built templates' format."""
    stem = Path(filename).stem
    lines = [
        f"# {parsed.company} — {parsed.role_title}",
    ]
    if parsed.location:
        lines.append(f"# {parsed.location}")
    lines += ["#", _HOW_TO_USE.format(name=filename, stem=stem)]

    lines += ["application:", f"  company: {_q(parsed.company)}",
              f"  role_title: {_q(parsed.role_title)}"]
    if parsed.location:
        lines.append(f"  location: {_q(parsed.location)}")

    lines += ["", "# ── KNOCKOUTS — binary. Check these before writing anything else. ────────────",
              "knockouts:"]
    for k in parsed.knockouts:
        lines += [f"  - id: {k.id}",
                  f"    requirement: {_q(k.requirement)}",
                  f"    evidence: {_q(k.evidence)}",
                  "    status:          # yes / no", ""]

    lines += ["# ── REQUIREMENTS ────────────────────────────────────────────────────────────",
              "requirements:"]
    for tier, label in ((Tier.CRITICAL, "CRITICAL"), (Tier.IMPORTANT, "IMPORTANT"),
                        (Tier.NICE_TO_HAVE, "NICE TO HAVE")):
        group = parsed.by_tier(tier)
        if not group:
            continue
        lines += ["", f"  # ─── {label} ─────────────────────────────────────────────────────────────", ""]
        for r in group:
            lines += [f"  - id: {r.id}",
                      f"    tier: {tier.value}",
                      f"    kind: {r.kind.value}",
                      f"    requirement: {_q(r.requirement)}",
                      f"    evidence: {_q(r.evidence)}"]
            if r.note:
                lines.append(f"    note: {_q(r.note)}")
            lines += ['    your_experience: ""', ""]

    if parsed.signals:
        lines += ["# ── SIGNALS — not requirements ───────────────────────────────────────────────",
                  "# Real parts of the evaluation that no resume bullet can carry. Nothing here",
                  "# gets matched against experiences; prep happens elsewhere.",
                  "signals:"]
        for s in parsed.signals:
            lines += [f"  - id: {s.id}",
                      f"    signal: {_q(s.signal)}",
                      f"    prep: {_q(s.prep)}", ""]

    return "\n".join(lines).rstrip() + "\n"


# ── Worksheet loading (references and generated files alike) ────────────────


def load_worksheet_template(path: Path | str) -> ParsedJD:
    """Parse a worksheet file (hand-built or generated) back into a ParsedJD.

    Ignores fill-in fields (status, your_experience). Hand-built templates
    carry extra keys (role, etc.) — they are ignored too.
    """
    path = Path(path)
    if not path.exists():
        raise JDParseError(f"worksheet not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise JDParseError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise JDParseError(f"{path} is not a worksheet")

    app = data.get("application") or {}
    payload = {
        "company": app.get("company") or "unknown",
        "role_title": app.get("role_title") or "unknown",
        "location": app.get("location"),
        "knockouts": [
            {"id": k.get("id"), "requirement": k.get("requirement"),
             "evidence": k.get("evidence") or "(none given)"}
            for k in data.get("knockouts") or []
        ],
        "requirements": [
            {"id": r.get("id"), "tier": r.get("tier"), "kind": r.get("kind"),
             "requirement": r.get("requirement"),
             "evidence": r.get("evidence") or "(none given)",
             "note": r.get("note")}
            for r in data.get("requirements") or []
        ],
        "signals": [
            {"id": s.get("id"), "signal": s.get("signal"),
             "prep": s.get("prep") or "(none given)"}
            for s in data.get("signals") or []
        ],
    }
    return _validate(payload)


# ── Storage ─────────────────────────────────────────────────────────────────


def store_application(conn: sqlite3.Connection, parsed: ParsedJD, jd_text: str) -> int:
    """Write the application and its requirements. Returns the application id."""
    application_id = store.add_application(conn, parsed.company, parsed.role_title, jd_text)
    position = 0
    with conn:
        for k in parsed.knockouts:
            conn.execute(
                "INSERT INTO requirement (application_id, text, tier, kind, evidence, position) "
                "VALUES (?, ?, 'critical', 'knockout', ?, ?)",
                (application_id, k.requirement, k.evidence, position),
            )
            position += 1
        for r in parsed.requirements:
            conn.execute(
                "INSERT INTO requirement (application_id, text, tier, kind, evidence, note, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (application_id, r.requirement, r.tier.value, r.kind.value,
                 r.evidence, r.note, position),
            )
            position += 1
    return application_id
