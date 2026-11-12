"""The unified run: parse → score → match → tellings → assemble → gates.

One orchestration of SPEC pipeline steps 1–9 minus the human ones. It never
invents: matches below threshold become persistent gap rows, tellings are
truth-checked or fall back to the raw summary, and the knockouts and gaps
are printed for the author rather than resolved by the machine.

Match decisions persist in requirement_match (the fix for v1's worst UX
failure): re-running against an edited JD re-validates instead of discarding.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .jd import ParsedJD
from .models import MatchState, Tier
from .profile import Profile
from .render import Entry, ResumeDoc, Section, lint_docx, verify_roundtrip
from .scoring import FitReport, score_fit
from .tellings import telling_for

STRONG_AT = 0.4           # retrieval score for a strong match; below → weak
MAX_BULLETS_PER_JOB = 4


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

    selected = _select_experiences(decisions)
    bullets = []
    for experience_id, angles in selected:
        experience = store.get_experience(conn, experience_id)
        existing = store.tellings_for(conn, experience_id)
        text, source = telling_for(experience, "; ".join(angles), existing, complete_fn)
        bullets.append((experience_id, text, source))

    result = ApplyResult(application_id=application_id, fit=fit,
                         decisions=decisions, bullets=bullets)

    if profile is not None and bullets:
        result.docx_path, result.roundtrip_ok, result.lint_clean = _assemble(
            conn, parsed, profile, bullets, Path(out_dir))
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


def _assemble(conn, parsed: ParsedJD, profile: Profile,
              bullets: list[tuple[int, str, str]], out_dir: Path):
    from .render import write_docx

    by_experience = {e: (t, s) for e, t, s in bullets}
    jobs = store.list_jobs(conn)
    entries = []
    for job in jobs:
        job_bullets = []
        for experience in store.list_experiences(conn, job.id):
            if experience.id in by_experience:
                job_bullets.append(by_experience[experience.id][0])
        if job_bullets:
            entries.append(Entry(
                title=job.title, organization=job.employer,
                start_date=job.start_date or "", end_date=job.end_date or "",
                location=job.location or "",
                bullets=job_bullets[:MAX_BULLETS_PER_JOB],
            ))

    sections = [Section(heading="Experience", entries=entries)]
    if profile.projects:
        sections.append(Section(heading="Projects", entries=profile.projects))
    if profile.skills:
        sections.append(Section(heading="Skills", lines=profile.skills))
    if profile.education:
        sections.append(Section(heading="Education", entries=profile.education))
    doc = ResumeDoc(contact=profile.contact, sections=sections)

    out_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in parsed.company.lower()).strip("-")
    path = out_dir / f"draft-{slug or 'role'}.docx"
    write_docx(doc, path, tight=True)
    roundtrip = verify_roundtrip(doc, out_dir / f".roundtrip-{slug}.docx")
    issues = lint_docx(path)
    lint_clean = not any(i.level == "error" for i in issues)
    return path, roundtrip.ok, lint_clean


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
        lines.append(f"Draft resume: {result.docx_path}  (round-trip {rt}, lint {lint})")
    return "\n".join(lines)
