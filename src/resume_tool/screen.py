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
import time
import urllib.error
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


def _get(url: str, retries: int = 3):
    """GET JSON. Workday's firewall answers bursts with 429, so back off and retry."""
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.5.0", "Accept": "application/json"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries:
                raise
            time.sleep(5 * (attempt + 1))


_WORKDAY_JOBS = re.compile(
    r"^https://(?P<tenant>[\w-]+)\.(?P<inst>wd[\w-]*)\.myworkdayjobs\.com/"
    r"(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[^/?#]+)(?P<path>/job/[^?#]+)")
_WORKDAY_SITE = re.compile(
    r"^https://(?P<host>[\w-]+\.myworkdaysite\.com)/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/"
    r"(?P<tenant>[\w-]+)/(?P<site>[^/?#]+)(?P<path>/job/[^?#]+)")


def workday_detail_url(posting_url: str) -> str | None:
    """The CXS detail endpoint for a Workday posting URL, or None if it isn't one.
    Both public shapes career-ops emits: {tenant}.wdN.myworkdayjobs.com/{site}/job/...
    and wdN.myworkdaysite.com/recruiting/{tenant}/{site}/job/..."""
    m = _WORKDAY_JOBS.match(posting_url)
    if m:
        host = f"{m['tenant']}.{m['inst']}.myworkdayjobs.com"
        return f"https://{host}/wday/cxs/{m['tenant']}/{m['site']}{m['path']}"
    m = _WORKDAY_SITE.match(posting_url)
    if m:
        return f"https://{m['host']}/wday/cxs/{m['tenant']}/{m['site']}{m['path']}"
    return None


# ── Workday discovery ───────────────────────────────────────────────────────
# career-ops reads Workday too, but by paging every tenant's whole board, and
# Workday's firewall rate-limits this egress after a few hundred requests (all
# 22 tenants failed with 429 on the first wide scan). One keyword search per
# tenant, spaced out, finds the same product roles in a request or two.

SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|director|head of|vp|vice president|lead|manager ii+|"
    r"intern|internship|co-op)\b|\b(ii|iii|iv)\b", re.I)
_CAREERS_JOBS = re.compile(
    r"^https://(?P<tenant>[\w-]+)\.(?P<inst>wd[\w-]*)\.myworkdayjobs\.com/"
    r"(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[^/?#]+)/?$")
_CAREERS_SITE = re.compile(
    r"^https://(?P<host>[\w-]+\.myworkdaysite\.com)/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/"
    r"(?P<tenant>[\w-]+)/(?P<site>[^/?#]+)/?$")


def workday_board(careers_url: str) -> tuple[str, str] | None:
    """(jobs API url, public posting base) for a Workday careers URL, else None."""
    m = _CAREERS_JOBS.match(careers_url)
    if m:
        origin = f"https://{m['tenant']}.{m['inst']}.myworkdayjobs.com"
        return f"{origin}/wday/cxs/{m['tenant']}/{m['site']}/jobs", f"{origin}/{m['site']}"
    m = _CAREERS_SITE.match(careers_url)
    if m:
        origin = f"https://{m['host']}"
        return (f"{origin}/wday/cxs/{m['tenant']}/{m['site']}/jobs",
                f"{origin}/recruiting/{m['tenant']}/{m['site']}")
    return None


def posted_days_ago(label: str) -> int | None:
    """Workday's relative 'postedOn' label in days; None for '30+ Days Ago'."""
    label = label.lower()
    if "today" in label:
        return 0
    if "yesterday" in label:
        return 1
    m = re.search(r"(\d+)\+?\s*days?", label)
    if not m or "+" in label:
        return None
    return int(m.group(1))


def _post(url: str, body: dict, retries: int = 3):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "curl/8.5.0"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries:
                raise
            time.sleep(10 * (attempt + 1))


def workday_search(careers_url: str, search: str = "product", max_pages: int = 3,
                   since_days: int | None = None, post=_post) -> list[dict]:
    """Early-career-eligible product postings on one Workday board."""
    board = workday_board(careers_url)
    if not board:
        raise ValueError(f"not a Workday careers URL: {careers_url}")
    api, base = board
    found = []
    for page in range(max_pages):
        d = post(api, {"limit": 20, "offset": page * 20, "searchText": search, "appliedFacets": {}})
        rows = d.get("jobPostings") or []
        for j in rows:
            title = j.get("title", "")
            if not j.get("externalPath") or not PRODUCT_TITLE.search(title):
                continue
            if NOT_PRODUCT.search(title) or SENIOR_TITLE.search(title):
                continue
            age = posted_days_ago(j.get("postedOn", ""))
            if since_days is not None and (age is None or age > since_days):
                continue
            found.append({"title": title, "url": base + j["externalPath"],
                          "location": j.get("locationsText", ""), "posted": j.get("postedOn", "")})
        if len(rows) < 20 or (page + 1) * 20 >= (d.get("total") or 0):
            break
        time.sleep(2)
    return found


def scan_workday(portals_yml: Path, pipeline_md: Path, since_days: int | None = 7,
                 pause: float = 4.0, search=workday_search) -> tuple[int, list[str]]:
    """Search every Workday entry in portals.yml (enabled or not: career-ops is
    told to skip them) and append new postings to the pipeline as pending rows.
    Returns (rows added, per-company errors)."""
    portals = yaml.safe_load(portals_yml.read_text(encoding="utf-8")) or {}
    existing = pipeline_md.read_text(encoding="utf-8") if pipeline_md.exists() else "## Pending\n"
    known = {i.url for i in parse_pipeline(existing)}
    lines, errors = [], []
    entries = [c for c in portals.get("tracked_companies") or [] if workday_board(c.get("careers_url", ""))]
    for n, c in enumerate(entries):
        if n:
            time.sleep(pause)
        try:
            for job in search(c["careers_url"], since_days=since_days):
                if job["url"] in known:
                    continue
                known.add(job["url"])
                lines.append(f"- [ ] {job['url']} | {c['name']} | {job['title']} | "
                             f"{job['location']} | {job['posted']}")
        except Exception as exc:  # one throttled tenant must not sink the rest
            errors.append(f"{c['name']}: {str(exc)[:120]}")
    if lines:
        text = existing.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
        pipeline_md.parent.mkdir(parents=True, exist_ok=True)
        pipeline_md.write_text(text, encoding="utf-8")
    return len(lines), errors


def fetch_jd(careers_url: str, posting_url: str) -> str:
    """JD text from the board's public API, keyed off the posting URL where it
    carries enough (Workday, SmartRecruiters, Workable) and the company's board
    URL otherwise (Greenhouse, Ashby, Lever)."""
    detail = workday_detail_url(posting_url)
    if detail:
        info = _get(detail)["jobPostingInfo"]
        return f"{info['title']}\n\n{_strip_html(info.get('jobDescription', ''))}"
    posting = urllib.parse.urlparse(posting_url)
    parts = [p for p in posting.path.split("/") if p]
    if posting.netloc == "jobs.smartrecruiters.com" and len(parts) >= 2:
        jid = parts[1].split("-")[0]
        d = _get(f"https://api.smartrecruiters.com/v1/companies/{parts[0]}/postings/{jid}")
        sections = (d.get("jobAd") or {}).get("sections") or {}
        body = "\n\n".join(_strip_html(v.get("text", "")) for v in sections.values() if isinstance(v, dict))
        return f"{d['name']}\n\n{body}"
    if posting.netloc == "apply.workable.com" and len(parts) >= 3 and parts[1] == "j":
        d = _get(f"https://apply.workable.com/api/v2/accounts/{parts[0]}/jobs/{parts[2]}")
        body = "\n\n".join(_strip_html(d.get(k) or "") for k in ("description", "requirements", "benefits"))
        return f"{d['title']}\n\n{body}"

    board = urllib.parse.urlparse(careers_url)
    slug = board.path.strip("/").split("/")[0]
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
    raise ValueError(f"no JD fetcher for {posting.netloc or board.netloc}")


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
