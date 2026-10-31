"""Configuration. Values live here or in the environment — never as constants in logic.

v1 hardcoded model IDs inside the engine, so a mid-project provider deprecation meant
editing core logic. Settings that providers, budgets or paths control belong here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".resume-tool" / "bank.db"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 16000


@dataclass(frozen=True)
class Config:
    db_path: Path
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    @classmethod
    def load(cls, db_path: Path | str | None = None) -> "Config":
        """Resolve config from an explicit path, then the environment, then the default."""
        if db_path is not None:
            resolved = Path(db_path)
        elif env := os.environ.get("RESUME_TOOL_DB"):
            resolved = Path(env)
        else:
            resolved = DEFAULT_DB_PATH
        return cls(
            db_path=resolved.expanduser(),
            model=os.environ.get("RESUME_TOOL_MODEL", DEFAULT_MODEL),
            max_tokens=int(os.environ.get("RESUME_TOOL_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
        )
