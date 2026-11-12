"""The author's profile: contact, education, skills, projects.

The bank holds what happened at jobs; a resume also needs who you are and
the sections that rarely change per application. Those live in a small YAML
file the author owns — never generated, never guessed.

Default path: ~/.resume-tool/profile.yaml ($RESUME_TOOL_PROFILE or --profile
override). Template written by `resume init-profile`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .render import Contact, Entry

DEFAULT_PROFILE_PATH = Path.home() / ".resume-tool" / "profile.yaml"

TEMPLATE = """\
# resume-tool profile — the per-person constants assembly needs.
# Facts only; this file is yours and is never generated or overwritten.

contact:
  name: ""
  location: ""
  phone: ""
  email: ""
  linkedin: ""          # e.g. linkedin.com/in/you
  website: ""           # portfolio domain

education:
  - title: ""           # e.g. UBC Sauder School of Business
    detail: ""          # e.g. Bachelor of Commerce (Marketing) | Dean's Honour List
    start: ""           # e.g. Sep 2021
    end: ""             # e.g. May 2026

# Rendered as "Label: items" lines, verbatim.
skills:
  - ""

# Optional fixed projects/leadership entries (title, link_label, link_url,
# date, bullets). Selection may trim them, never invent them.
projects: []
"""


class ProfileError(ValueError):
    """Raised when the profile file is missing or malformed."""


@dataclass
class Profile:
    contact: Contact
    education: list[Entry] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    projects: list[Entry] = field(default_factory=list)


def profile_path(override: Path | str | None = None) -> Path:
    if override is not None:
        return Path(override)
    if env := os.environ.get("RESUME_TOOL_PROFILE"):
        return Path(env)
    return DEFAULT_PROFILE_PATH


def write_template(path: Path | str) -> Path:
    path = Path(path)
    if path.exists():
        raise ProfileError(f"{path} already exists — edit it instead")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


def load_profile(path: Path | str | None = None) -> Profile:
    resolved = profile_path(path)
    if not resolved.exists():
        raise ProfileError(
            f"no profile at {resolved} — run `resume init-profile` and fill it in"
        )
    try:
        data = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"invalid YAML in {resolved}: {exc}") from exc

    raw_contact = data.get("contact") or {}
    contact = Contact(
        name=str(raw_contact.get("name") or "").strip(),
        location=str(raw_contact.get("location") or "").strip(),
        phone=str(raw_contact.get("phone") or "").strip(),
        email=str(raw_contact.get("email") or "").strip(),
        linkedin=str(raw_contact.get("linkedin") or "").strip(),
        website=str(raw_contact.get("website") or "").strip(),
    )
    if not contact.name or not contact.email:
        raise ProfileError(f"{resolved}: contact.name and contact.email are required")

    education = []
    for entry in data.get("education") or []:
        if not str(entry.get("title") or "").strip():
            continue
        education.append(Entry(
            title=str(entry["title"]).strip(),
            organization=str(entry.get("detail") or "").strip(),
            start_date=str(entry.get("start") or "").strip(),
            end_date=str(entry.get("end") or "").strip(),
        ))

    projects = []
    for entry in data.get("projects") or []:
        if not str(entry.get("title") or "").strip():
            continue
        projects.append(Entry(
            title=str(entry["title"]).strip(),
            organization="",
            link_label=str(entry.get("link_label") or "").strip(),
            link_url=str(entry.get("link_url") or "").strip(),
            start_date=str(entry.get("date") or "").strip(),
            end_date=str(entry.get("date") or "").strip(),
            bullets=[str(b).strip() for b in entry.get("bullets") or [] if str(b).strip()],
        ))

    skills = [str(s).strip() for s in data.get("skills") or [] if str(s).strip()]
    return Profile(contact=contact, education=education, skills=skills, projects=projects)
