"""The unified run: parse → score → match → tellings → assemble → gates.

One orchestration of SPEC pipeline steps 1–9 minus the human ones. It never
invents: matches below threshold become persistent gap rows, tellings are
truth-checked or fall back to the raw summary, and the knockouts and gaps
are printed for the author rather than resolved by the machine.

Match decisions persist in requirement_match (the fix for v1's worst UX
failure): re-running against an edited JD re-validates instead of discarding.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import retrieval, store
from .jd import ParsedJD
from .models import MatchState, Tier
from .profile import Profile
from .render import Entry, ResumeDoc, Section, lint_docx, verify_roundtrip
from .scoring import FitReport, score_fit
from .tellings import telling_for

STRONG_AT = 0.4           # retrieval score for a strong match; below → weak
# Coverage is a floor, not a filter (writing-guidelines rule 5): every job
# stays on the page. A job that covers requirements earns up to 4 bullets;
# one that covers none keeps its 2 most JD-relevant, so range survives.
MAX_BULLETS_MATCHED_JOB = 4
MAX_BULLETS_OTHER_JOB = 2


@dataclass
class MatchDecision:
    requirement_id: int           # DB id
    requirement_label: str        # e.g. "R3"
    requirement_text: str
    tier: Tier
    experience_id: int | None
    score: float
    state: MatchState


@dataclass
class ApplyResult:
    application_id: int
    fit: FitReport
    decisions: list[MatchDecision] = field(default_factory=list)
    bullets: list[tuple[int, str, str]] = field(default_factory=list)  # (exp id, text, source)
    docx_path: Path | None = None
    roundtrip_ok: bool | None = None
    lint_clean: bool | None = None
    pages: int | None = None              # None when no PDF renderer is installed
    cut_to_fit: list[str] = field(default_factory=list)


def run_apply(
    conn: sqlite3.Connection,
    parsed: ParsedJD,
    jd_text: str,
    profile: Profile | None,
    out_dir: Path | str,
    complete_fn=None,
) -> ApplyResult:
    """Everything after the worksheet exists. complete_fn=None skips telling
    generation (summaries become the draft bullets) — zero LLM calls."""
    from .jd import store_application

    fit = score_fit(conn, parsed, complete_fn=complete_fn)
    application_id = store_application(conn, parsed, jd_text)
    decisions = _persist_matches(conn, application_id, fit)

    bullets = []
    for experience_id, angle in _plan_bullets(conn, decisions, parsed, profile):
        experience = store.get_experience(conn, experience_id)
        existing = store.tellings_for(conn, experience_id)
        text, source = telling_for(experience, angle, existing, complete_fn)
        bullets.append((experience_id, text, source))

    result = ApplyResult(application_id=application_id, fit=fit,
                         decisions=decisions, bullets=bullets)

    if profile is not None and bullets:
        matched = {d.experience_id for d in decisions if d.experience_id is not None}
        _assemble(conn, parsed, profile, bullets, matched, Path(out_dir), result)
    return result


def _persist_matches(conn, application_id: int, fit: FitReport) -> list[MatchDecision]:
    """One source of matching truth: the fit report (keyword + optional LLM
    pass, zero-evidence guard included)."""
    rows = store.requirements_for(conn, application_id)
    by_text = {r["text"]: r["id"] for r in rows}
    decisions = []
    with conn:
        for requirement_fit in fit.fits:
            requirement = requirement_fit.requirement
            db_id = by_text.get(requirement.requirement)
            if db_id is None:
                continue
            if requirement_fit.covered:
                state = MatchState.PROPOSED
                exp_id = requirement_fit.best_experience_id
            else:
                state, exp_id = MatchState.GAP, None
            conn.execute(
                "INSERT INTO requirement_match "
                "(requirement_id, experience_id, state, score) VALUES (?, ?, ?, ?)",
                (db_id, exp_id, state.value, requirement_fit.best_score),
            )
            decisions.append(MatchDecision(
                requirement_id=db_id, requirement_label=requirement.id,
                requirement_text=requirement.requirement, tier=requirement.tier,
                experience_id=exp_id, score=requirement_fit.best_score, state=state,
            ))
    return decisions


def _select_experiences(decisions: list[MatchDecision]) -> list[tuple[int, list[str]]]:
    """Experiences that earned a place, ranked by the tier-weighted matches
    they cover; each carries its requirement angles for the telling."""
    from .scoring import TIER_WEIGHTS

    weight: dict[int, float] = {}
    angles: dict[int, list[str]] = {}
    for decision in decisions:
        if decision.experience_id is None:
            continue
        weight[decision.experience_id] = (
            weight.get(decision.experience_id, 0.0)
            + TIER_WEIGHTS[decision.tier] * decision.score
        )
        angles.setdefault(decision.experience_id, []).append(decision.requirement_text)
    ranked = sorted(weight, key=lambda e: -weight[e])
    return [(e, angles[e]) for e in ranked]


def _project_employers(profile: Profile | None) -> set[str]:
    return set(profile.project_employers) if profile else set()


def _plan_bullets(conn, decisions: list[MatchDecision], parsed: ParsedJD,
                  profile: Profile | None) -> list[tuple[int, str]]:
    """Which experiences go on the page, in order, with each one's angle.

    Per job: experiences that matched requirements first (ranked by the
    tier-weighted coverage they carry), then the job's remaining facts by
    relevance to the whole JD, capped. Jobs named in the profile's
    project_employers are matched like any experience but render through
    the profile's Projects section, so they get no planned bullets here
    when the profile supplies its own project entries."""
    ranked = _select_experiences(decisions)
    rank = {exp_id: i for i, (exp_id, _) in enumerate(ranked)}
    angles = dict(ranked)
    jd_tokens = retrieval.tokenize(" ".join(
        f"{r.requirement} {r.evidence}" for r in parsed.requirements))
    skip = _project_employers(profile) if profile and profile.projects else set()
    default_angle = f"{parsed.role_title} at {parsed.company}"

    plan = []
    for job in store.list_jobs(conn):
        if job.employer in skip:
            continue
        experiences = store.list_experiences(conn, job.id)
        matched = sorted((e for e in experiences if e.id in rank), key=lambda e: rank[e.id])
        others = sorted((e for e in experiences if e.id not in rank),
                        key=lambda e: -retrieval.score_experience(jd_tokens, e))
        cap = MAX_BULLETS_MATCHED_JOB if matched else MAX_BULLETS_OTHER_JOB
        for experience in (matched + others)[:cap]:
            angle = "; ".join(angles.get(experience.id, [])) or default_angle
            plan.append((experience.id, angle))
    return plan


# Layout levers, gentlest first. Content is cut only after all of them fail
# (assembly-learnings: chasing wrap boundaries with wording edits never works).
LAYOUT_LADDER = (
    {"margin": 0.5, "size": 9.5},
    {"margin": 0.45, "size": 9.5},
    {"margin": 0.4, "size": 9.5},
    {"margin": 0.4, "size": 9.0},
)
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _human_date(value: str | None) -> str:
    """'2026-07' -> 'Jul 2026'; 'YYYY' and pre-formatted strings pass through."""
    if not value:
        return ""
    m = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
    return value.strip()


def _build_doc(conn, profile: Profile, bullets: list[tuple[int, str, str]]) -> ResumeDoc:
    order = [e for e, _, _ in bullets]
    text_for = {e: t for e, t, _ in bullets}
    project_employers = _project_employers(profile)
    entries, project_bullets = [], []
    for job in store.list_jobs(conn):
        job_ids = {e.id for e in store.list_experiences(conn, job.id)}
        job_bullets = [text_for[e] for e in order if e in job_ids]
        if not job_bullets:
            continue
        if job.employer in project_employers:
            project_bullets.extend(job_bullets)
            continue
        entries.append(Entry(
            title=job.title, organization=job.employer,
            start_date=_human_date(job.start_date), end_date=_human_date(job.end_date),
            location=job.location or "", bullets=job_bullets,
        ))

    available = {"Experience": Section(heading="Experience", entries=entries)}
    if profile.projects:
        available["Projects"] = Section(heading="Projects", entries=profile.projects)
    elif project_bullets:
        available["Projects"] = Section(heading="Projects", entries=[
            Entry(title="Selected projects", organization="", bullets=project_bullets)])
    if profile.skills:
        available["Skills"] = Section(heading="Skills", lines=profile.skills)
    if profile.education:
        available["Education"] = Section(heading="Education", entries=profile.education)

    sections = [available.pop(name) for name in profile.section_order if name in available]
    sections.extend(available.values())  # anything the order didn't name, appended
    return ResumeDoc(contact=profile.contact, sections=sections)


def _page_count(docx_path: Path) -> int | None:
    """Render with LibreOffice and count pages; None if no renderer exists."""
    import shutil
    import subprocess
    import tempfile

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                            "--outdir", tmp, str(docx_path)],
                           check=True, capture_output=True, timeout=120)
            from pypdf import PdfReader
            return len(PdfReader(str(Path(tmp) / f"{docx_path.stem}.pdf")).pages)
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            return None


def _cut_candidates(conn, bullets, matched: set[int]) -> list[int]:
    """Filler bullets (matched nothing), oldest job and lowest rank first,
    never a job's last remaining bullet."""
    job_of = {e: store.get_experience(conn, e).job_id for e, _, _ in bullets}
    return [e for e, _, _ in reversed(bullets) if e not in matched and job_of[e] is not None]


def _assemble(conn, parsed: ParsedJD, profile: Profile,
              bullets: list[tuple[int, str, str]], matched: set[int],
              out_dir: Path, result: "ApplyResult") -> None:
    from .render import write_docx

    out_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in parsed.company.lower()).strip("-")
    path = out_dir / f"draft-{slug or 'role'}.docx"

    kept = list(bullets)
    pages = None
    while True:
        doc = _build_doc(conn, profile, kept)
        for layout in LAYOUT_LADDER:
            write_docx(doc, path, font=profile.font, size=layout["size"],
                       margin=layout["margin"], tight=True)
            pages = _page_count(path)
            if pages is None or pages <= 1:
                break
        if pages is None or pages <= 1:
            break
        job_of = {e: store.get_experience(conn, e).job_id for e, _, _ in kept}
        per_job: dict[int, int] = {}
        for e, _, _ in kept:
            per_job[job_of[e]] = per_job.get(job_of[e], 0) + 1
        victim = next((e for e in _cut_candidates(conn, kept, matched)
                       if per_job[job_of[e]] > 1), None)
        if victim is None:
            break  # nothing left that can be cut without losing a job or a match
        result.cut_to_fit.append(next(t for e, t, _ in kept if e == victim))
        kept = [b for b in kept if b[0] != victim]

    roundtrip = verify_roundtrip(doc, out_dir / f".roundtrip-{slug}.docx")
    issues = lint_docx(path)
    result.docx_path = path
    result.roundtrip_ok = roundtrip.ok
    result.lint_clean = not any(i.level == "error" for i in issues)
    result.pages = pages


def format_result(result: ApplyResult) -> str:
    """The SPEC's target interaction, rendered honestly."""
    lines = [str(result.fit), ""]
    knockouts = result.fit.parsed.knockouts
    if knockouts:
        lines.append(f"Knockouts: {len(knockouts)} to answer yourself:")
        for k in knockouts:
            lines.append(f"  [ ] {k.id}  {k.requirement}")
        lines.append("")

    for tier in Tier:
        group = [d for d in result.decisions if d.tier == tier]
        if not group:
            continue
        lines.append(f"{tier.value.upper()} ({len(group)})")
        for d in group:
            if d.state == MatchState.GAP:
                lines.append(f"  ✗ {d.requirement_label:<4} {d.requirement_text[:58]:<58} → GAP")
            else:
                strength = "✓" if d.score >= STRONG_AT else "⚠"
                lines.append(
                    f"  {strength} {d.requirement_label:<4} {d.requirement_text[:58]:<58} "
                    f"→ EXP-{d.experience_id:03d} ({d.score:.2f})"
                )
        lines.append("")

    sources = {}
    for _, _, source in result.bullets:
        sources[source] = sources.get(source, 0) + 1
    if result.bullets:
        parts = ", ".join(f"{n} {s}" for s, n in sources.items())
        lines.append(f"Draft bullets: {len(result.bullets)} ({parts})")
    if result.docx_path:
        rt = "PASS" if result.roundtrip_ok else "FAIL"
        lint = "clean" if result.lint_clean else "ISSUES"
        pages = "unchecked (no LibreOffice)" if result.pages is None else str(result.pages)
        lines.append(f"Draft resume: {result.docx_path}  "
                     f"(round-trip {rt}, lint {lint}, pages {pages})")
        if result.pages and result.pages > 1:
            lines.append("  ! still over one page after every layout lever and safe cut")
        for text in result.cut_to_fit:
            lines.append(f"  cut to fit: {text}")
    return "\n".join(lines)
