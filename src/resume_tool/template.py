"""Tailor the author's own Google Docs template instead of generating a design.

The template is the design source of truth: fonts, spacing, section order and
the author's wording all live there, refined over many applications. The
bank decides content. So per application the tool does not render anything;
it plans edits against a clone of the template, and an agent with the Docs
connector applies them (docs/template-editing.md has that procedure).

The plan, from a Markdown export of the template plus a fit report:
  - the headline role-title swap (the one edit safe to automate),
  - for every bullet: which bank experience it tells and which requirements
    it covers, or that it carries none and is a cut candidate,
  - additions: requirements the bank covers that no template bullet does —
    the "be more aggressive about what gets added" half of tailoring,
  - gaps: requirements nothing covers, for the author.

Bullet → experience mapping is token overlap: template bullets and bank
summaries are the same stories in nearly the same words, so this is a
matching problem keyword overlap is good at.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import retrieval, store
from .jd import ParsedJD
from .scoring import FitReport

SAME_STORY_AT = 0.45   # bullet-vs-summary overlap to call them one story


@dataclass
class TemplateEntry:
    section: str
    heading: str
    subheading: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class TemplateDoc:
    title_line: str
    entries: list[TemplateEntry] = field(default_factory=list)


_ESCAPES = re.compile(r"\\(.)")


def _clean(line: str) -> str:
    """Strip Markdown emphasis, links and escapes down to the visible text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
    text = _ESCAPES.sub(r"\1", text)
    text = text.replace("**", "").replace("*", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_template_markdown(md: str) -> TemplateDoc:
    """Parse a Docs Markdown export (Drive `text/markdown` export or the
    `read_file_content` rendering): `#` sections, `##` entry lines, bullets."""
    title_line, section = "", ""
    entries: list[TemplateEntry] = []
    current: TemplateEntry | None = None
    last_was_heading = False

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("# "):
            text = _clean(stripped[2:])
            if not title_line:
                title_line = text
            else:
                section = text
            current, last_was_heading = None, False
        elif stripped.startswith("## "):
            text = _clean(stripped[3:])
            if current is not None and last_was_heading and not current.subheading:
                current.subheading = text
            else:
                current = TemplateEntry(section=section, heading=text)
                entries.append(current)
            last_was_heading = True
        elif re.match(r"^[*-] ", stripped):
            text = _clean(stripped[2:])
            if current is None:
                current = TemplateEntry(section=section, heading="")
                entries.append(current)
            current.bullets.append(text)
            last_was_heading = False
        else:
            last_was_heading = False
    return TemplateDoc(title_line=title_line, entries=entries)


@dataclass
class BulletPlan:
    section: str
    entry: str
    text: str
    experience_id: int | None
    overlap: float
    covers: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.covers:
            return "keep"
        if self.experience_id is None:
            return "not in bank"
        return "cut candidate"


@dataclass
class TemplatePlan:
    title_change: tuple[str, str] | None
    bullets: list[BulletPlan] = field(default_factory=list)
    additions: list[tuple[str, int, str]] = field(default_factory=list)  # (req id, exp id, summary)
    gaps: list[tuple[str, str]] = field(default_factory=list)            # (req id, text)

    def docs_requests(self, tab_id: str = "t.0") -> list[dict]:
        """The automatable edits as Docs batchUpdate requests. Only the title
        swap qualifies; content changes go to the author first."""
        if not self.title_change:
            return []
        old, new = self.title_change
        return [{"replaceAllText": {
            "containsText": {"text": old, "matchCase": True},
            "replaceText": new, "tabsCriteria": {"tabIds": [tab_id]}}}]

    def __str__(self) -> str:
        lines = []
        if self.title_change:
            lines.append(f"title      {self.title_change[0]!r} → {self.title_change[1]!r}")
            lines.append("")
        current = None
        for b in self.bullets:
            if b.entry != current:
                current = b.entry
                lines.append(f"[{b.section}] {b.entry}")
            mark = {"keep": "✓", "cut candidate": "·", "not in bank": "?"}[b.verdict]
            why = (f"covers {', '.join(b.covers)}" if b.covers else b.verdict)
            lines.append(f"  {mark} {b.text[:70]:<70}  {why}")
        if self.additions:
            lines.append("")
            lines.append("add (the bank covers these, the template doesn't):")
            for req_id, exp_id, summary in self.additions:
                lines.append(f"  + {req_id}  EXP-{exp_id:03d}  {summary[:80]}")
        if self.gaps:
            lines.append("")
            lines.append("gaps (nothing in the bank covers these):")
            for req_id, text in self.gaps:
                lines.append(f"  ✗ {req_id}  {text[:80]}")
        cuts = sum(1 for b in self.bullets if b.verdict == "cut candidate")
        lines.append("")
        lines.append(f"{len(self.bullets)} bullets: "
                     f"{sum(1 for b in self.bullets if b.verdict == 'keep')} carry requirements, "
                     f"{cuts} cut candidates (range only — cut if space is needed), "
                     f"{sum(1 for b in self.bullets if b.verdict == 'not in bank')} not in the bank")
        return "\n".join(lines)


def headline_role(role_title: str) -> str:
    """'Apprentice Product Manager (APM) — 2027 cohort' → 'Apprentice Product Manager'."""
    text = re.split(r"\s+[—–-]\s+", role_title)[0]
    return re.sub(r"\s*\([^)]*\)", "", text).strip()


def plan_template(conn: sqlite3.Connection, template: TemplateDoc,
                  parsed: ParsedJD, fit: FitReport) -> TemplatePlan:
    title_change = None
    if "|" in template.title_line:
        name, current_role = (p.strip() for p in template.title_line.split("|", 1))
        wanted = headline_role(parsed.role_title)
        if wanted and wanted != current_role:
            title_change = (f"{name} | {current_role}", f"{name} | {wanted}")

    covers_by_exp: dict[int, list[str]] = {}
    for f in fit.fits:
        if f.covered and f.best_experience_id is not None:
            covers_by_exp.setdefault(f.best_experience_id, []).append(f.requirement.id)

    experiences = store.list_experiences(conn)
    plan = TemplatePlan(title_change=title_change)
    mapped: set[int] = set()
    for entry in template.entries:
        if entry.section.upper().startswith(("SKILL", "EDUCATION", "INTEREST")):
            continue
        for text in entry.bullets:
            tokens = retrieval.tokenize(text)
            best_id, best = None, 0.0
            for e in experiences:
                score = retrieval.score_experience(tokens, e)
                if score > best:
                    best_id, best = e.id, score
            exp_id = best_id if best >= SAME_STORY_AT else None
            if exp_id is not None:
                mapped.add(exp_id)
            plan.bullets.append(BulletPlan(
                section=entry.section, entry=entry.subheading or entry.heading,
                text=text, experience_id=exp_id, overlap=best,
                covers=list(covers_by_exp.get(exp_id, [])) if exp_id else [],
            ))

    for f in fit.fits:
        exp_id = f.best_experience_id
        if f.covered and exp_id is not None and exp_id not in mapped:
            plan.additions.append(
                (f.requirement.id, exp_id, store.get_experience(conn, exp_id).summary))
        elif not f.covered:
            plan.gaps.append((f.requirement.id, f.requirement.requirement))
    return plan
