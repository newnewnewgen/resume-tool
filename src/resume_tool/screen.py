"""Deterministic screening of scanned postings, before any model reads them.

After career-ops' scan fills data/pipeline.md, this keeps product roles,
fetches each JD from its public board API, and extracts the eligibility
facts that decided the first live run: the stated years of experience, a
CS/engineering-degree requirement, and graduation-window lines. Roles over
the experience ceiling are dropped here, for free; the rest go to the model
with their flags attached.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .careerops import parse_pipeline

PRODUCT_TITLE = re.compile(
    r"product (manager|management|ops|operations)|\bapm\b|\bapx\b|apprentice product|"
    r"product analyst|associate product", re.I)
NOT_PRODUCT = re.compile(r"engineer|design(er)?\b|marketing manager", re.I)
EARLY_TITLE = re.compile(
    r"associate|apprentice|new grad|early career|\bapm\b|\bapx\b|rotational|accelerator|junior",
    re.I)
_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:\+\s*)?years?\b(?:\s+of)?"
    r"(?=[^.\n]{0,60}(?:experience|product|industry|software|working|role))", re.I)
_DEGREE = re.compile(
    r"(computer science|\bCS\b|engineering|technical)[^.\n]{0,40}degree|"
    r"degree[^.\n]{0,40}(computer science|\bCS\b|engineering)", re.I)


@dataclass
class Screened:
    company: str
    title: str
    url: str
    years_required: int | None
    cs_degree_required: bool
    graduation_lines: list[str] = field(default_factory=list)
    early_title: bool = False
    jd_path: str = ""
    fetch_error: str = ""

    @property
    def within(self) -> bool:
        return self.early_title or self.years_required is None or self.years_required <= 2


def years_required(text: str) -> int | None:
    found = [int(n) for n in _YEARS.findall(text) if 0 <= int(n) < 20]
    return max(found) if found else None


def cs_degree_required(text: str) -> bool:
    return bool(_DEGREE.search(text))


def graduation_lines(text: str) -> list[str]:
    return [ln.strip()[:200] for ln in text.splitlines() if re.search(r"graduat", ln, re.I)][:3]


def _strip_html(h: str) -> str:
    h = html.unescape(h)
    h = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", h)
    h = re.sub(r"<li[^>]*>", "- ", h)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"<[^>]+>", "", h)).strip()


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_jd(careers_url: str, posting_url: str) -> str:
    """JD text from the board's public API, keyed off the company's board URL."""
    board = urllib.parse.urlparse(careers_url)
    slug = board.path.strip("/").split("/")[0]
    posting = urllib.parse.urlparse(posting_url)
    query = urllib.parse.parse_qs(posting.query)

    if "greenhouse" in board.netloc:
        jid = (query.get("gh_jid") or [""])[0] or posting.path.rstrip("/").split("/")[-1]
        d = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}")
        return f"{d['title']}\n\n{_strip_html(d['content'])}"
    if "ashbyhq" in board.netloc:
        jid = posting.path.rstrip("/").split("/")[-1]
        jobs = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")["jobs"]
        job = next(j for j in jobs if j["id"] == jid)
        return f"{job['title']}\n\n{job.get('descriptionPlain') or _strip_html(job.get('descriptionHtml', ''))}"
    if "lever" in board.netloc:
        jid = posting.path.rstrip("/").split("/")[-1]
        d = _get(f"https://api.lever.co/v0/postings/{slug}/{jid}")
        return f"{d['text']}\n\n{d.get('descriptionPlain', '')}\n{d.get('additionalPlain', '')}"
    raise ValueError(f"no JD fetcher for {board.netloc}")


def screen_pipeline(pipeline_md: Path, portals_yml: Path, jd_dir: Path) -> list[Screened]:
    portals = yaml.safe_load(portals_yml.read_text(encoding="utf-8")) or {}
    boards = {c["name"]: c["careers_url"] for c in portals.get("tracked_companies") or []}
    jd_dir.mkdir(parents=True, exist_ok=True)

    out = []
    for item in parse_pipeline(pipeline_md.read_text(encoding="utf-8")):
        if item.state != "pending":
            continue
        if not PRODUCT_TITLE.search(item.title) or NOT_PRODUCT.search(item.title):
            continue
        s = Screened(company=item.company, title=item.title, url=item.url,
                     years_required=None, cs_degree_required=False,
                     early_title=bool(EARLY_TITLE.search(item.title)))
        try:
            text = fetch_jd(boards.get(item.company, ""), item.url)
        except Exception as exc:  # one dead board must not sink the run
            s.fetch_error = str(exc)[:200]
            out.append(s)
            continue
        path = jd_dir / f"{re.sub(r'[^a-z0-9]+', '-', (item.company + ' ' + item.title).lower()).strip('-')}.txt"
        path.write_text(text, encoding="utf-8")
        s.jd_path = str(path)
        s.years_required = years_required(text)
        s.cs_degree_required = cs_degree_required(text)
        s.graduation_lines = graduation_lines(text)
        out.append(s)
    return out


def to_json(results: list[Screened]) -> str:
    return json.dumps([asdict(r) | {"within": r.within} for r in results], indent=1)
