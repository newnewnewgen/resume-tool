"""Baseline retrieval: keyword overlap between a requirement and the bank.

Step 5 replaces the scoring with hybrid semantic + keyword retrieval. The
interface here — (conn, requirement text, k) → ranked candidates — is what the
eval harness is written against, so the upgrade swaps internals, not callers.

Deliberately boring: lowercase tokens, a crude stemmer, a small stopword list,
overlap of requirement tokens against an experience's summary and fact values.
It exists to give the golden set a measurable floor, not to be good. Where it
misses — synonyms, paraphrase — is exactly the headroom step 5 has to show.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import store
from .models import Experience

# Hyphens, +, #, . and / stay inside a token so "cross-functional", "A/B" and
# "C++" survive as units instead of shattering into noise.
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+./#-]*")

_STOPWORDS = frozenset(
    """
    a an and are as at be been both but by can could did do for from had has
    have how i if in into is it its me my of on or our out so than that the
    their them they this those to was we were what when where which while who
    will with without would you your
    """.split()
)


def _stem(token: str) -> str:
    """Strip the inflections that make 'owning' miss 'owned'. Crude on purpose."""
    if token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        token = token[:-1]
    return token


def tokenize(text: str) -> set[str]:
    out = set()
    for raw in _TOKEN_RE.findall(text.lower()):
        if raw in _STOPWORDS:
            continue
        stemmed = _stem(raw)
        if stemmed not in _STOPWORDS:
            out.add(stemmed)
    return out


@dataclass
class Candidate:
    experience_id: int
    score: float


def score_experience(requirement_tokens: set[str], experience: Experience) -> float:
    """Fraction of the requirement's tokens found in the experience."""
    if not requirement_tokens:
        return 0.0
    text = " ".join([experience.summary, *(f.value for f in experience.facts)])
    return len(requirement_tokens & tokenize(text)) / len(requirement_tokens)


def retrieve(
    conn: sqlite3.Connection, requirement_text: str, k: int = 3
) -> list[Candidate]:
    """Top-k experiences for a requirement, best first. Zero-score rows are
    dropped, so a requirement nothing touches comes back empty — a gap."""
    requirement_tokens = tokenize(requirement_text)
    candidates = [
        Candidate(experience_id=e.id, score=score_experience(requirement_tokens, e))
        for e in store.list_experiences(conn)
    ]
    candidates = [c for c in candidates if c.score > 0.0]
    candidates.sort(key=lambda c: (-c.score, c.experience_id))
    return candidates[:k]
