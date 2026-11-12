"""Step 6: tellings — one framing of an experience, truth-checked.

The generation prompt encodes docs/writing-guidelines.md (action + scope +
outcome, the requirement is context for selection and never text to echo,
shortest defensible length). The truth check is the deterministic gate the
SPEC demands: every number in a telling must trace to the experience's own
facts or summary, or the telling is rejected — a hallucinated metric fails
here, not on the page.

Reuse before generation: an existing telling whose angle fits is free.
Without an LLM, the experience's summary is the fallback telling — facts
read fine as bullets; they are just unoptimized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .llm import CompleteFn
from .models import Experience, Telling

TELLING_SYSTEM = """You write one resume bullet from verified facts. Rules, \
all non-negotiable:
- The bullet is action + scope + outcome, at most 30 words, starting with a \
strong verb. Shortest defensible version; the author trims hard.
- Use ONLY the facts given. Never invent a number, tool, employer or \
outcome. Prefer the facts' own vocabulary over synonyms.
- The requirement below is context for emphasis ONLY. Do not echo its \
wording into the bullet; once the facts cover it, write to communicate the \
work.
- No negative framing, no reasoning narration ("identified X then..."), no \
requirement keywords stuffed in.
Output the bullet text only — no quotes, no bullet character, no commentary."""


@dataclass
class TruthViolation:
    value: str
    reason: str


_NUMBER_RE = re.compile(r"\d[\d,.]*")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER_RE.findall(text):
        cleaned = raw.replace(",", "").rstrip(".")
        if cleaned:
            out.add(cleaned)
    return out


def truth_check(text: str, experience: Experience) -> list[TruthViolation]:
    """Every number in the telling must appear in the experience's summary or
    fact values. Years inside date-like tokens are not exempted — a telling
    has no business citing dates the facts don't carry."""
    allowed = _numbers(experience.summary)
    for fact in experience.facts:
        allowed |= _numbers(fact.value)

    violations = []
    for number in _numbers(text):
        if number not in allowed:
            violations.append(TruthViolation(
                value=number,
                reason="number not present in the experience's facts or summary",
            ))
    return violations


def telling_for(
    experience: Experience,
    angle: str,
    existing: list[Telling],
    complete_fn: CompleteFn | None = None,
) -> tuple[str, str]:
    """Return (text, source) where source is reuse | generated | summary.

    Reuse wins when any stored telling matches the angle loosely; generation
    needs an LLM and must pass the truth check (one retry with the violation
    named); the summary is the always-available fallback.
    """
    for telling in existing:
        if _angle_matches(telling.angle, angle):
            return telling.text, "reuse"

    if complete_fn is not None:
        prompt = _build_prompt(experience, angle)
        text = complete_fn(TELLING_SYSTEM, prompt).strip().lstrip("•-* ").strip()
        violations = truth_check(text, experience)
        if violations:
            bad = ", ".join(v.value for v in violations)
            retry = complete_fn(
                TELLING_SYSTEM,
                prompt + f"\n\nYour previous attempt used numbers not in the "
                f"facts ({bad}). Rewrite using only the facts' numbers:\n{text}",
            ).strip().lstrip("•-* ").strip()
            if not truth_check(retry, experience):
                return retry, "generated"
            return experience.summary, "summary"  # refuse to ship a fabrication
        if text:
            return text, "generated"

    return experience.summary, "summary"


def _build_prompt(experience: Experience, angle: str) -> str:
    facts = "\n".join(f"- {f.kind.value}: {f.value}" for f in experience.facts)
    return (
        f"FACTS (the only allowed material):\n"
        f"summary: {experience.summary}\n{facts or '- (no structured facts)'}\n\n"
        f"REQUIREMENT CONTEXT (emphasis only, never echo): {angle}\n\n"
        "Write the bullet."
    )


def _angle_matches(stored: str, wanted: str) -> bool:
    a = set(re.findall(r"[a-z]+", stored.lower()))
    b = set(re.findall(r"[a-z]+", wanted.lower()))
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= 0.5
