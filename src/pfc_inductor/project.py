"""Project file format — ``.pfc`` JSON snapshot of a design session.

A ``.pfc`` file captures the three things a designer needs to resume
work after closing the app:

1. **Spec** — the full ``Spec`` model the engine ran against
   (topology, V/I/P/η/fsw/T_amb/etc.).
2. **Selection** — which material / core / wire IDs were picked.
3. **Project name** — what the user typed in the header field
   ("Reator 800 W 60 Hz", etc.).

The format is **plain JSON** so users can read / diff / version it
under git, and so we can extend it later without a binary migration.
The ``version`` field is a SemVer string the loader uses to detect
older revisions and apply (or refuse) a migration path.

Round-trip example:

    state = ProjectFile.from_session(name=..., spec=..., selection=...)
    save_project(path, state)
    loaded = load_project(path)
    assert loaded == state

The loader is **defensive**: it never raises on a malformed key —
unknown fields are ignored, missing fields fall back to sensible
defaults so a partial file still opens (the user gets a banner
explaining what was patched).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pfc_inductor.models import Spec

PROJECT_FILE_VERSION = "1.0"
PROJECT_FILE_EXTENSION = ".pfc"


class ProjectSelection(BaseModel):
    """The three picked IDs — empty strings mean "no selection yet"."""

    material_id: str = ""
    core_id: str = ""
    wire_id: str = ""


class ProjectFile(BaseModel):
    """Top-level project snapshot — what ``.pfc`` files contain.

    Pydantic-backed so validation, JSON round-trip and forward
    compatibility (``extra="ignore"`` on load) come for free.
    """

    version: str = PROJECT_FILE_VERSION
    name: str = "Untitled Project"
    spec: Spec = Field(default_factory=Spec)
    selection: ProjectSelection = Field(default_factory=ProjectSelection)

    model_config = {"extra": "ignore"}

    @classmethod
    def from_session(
        cls,
        name: str,
        spec: Spec,
        material_id: str = "",
        core_id: str = "",
        wire_id: str = "",
    ) -> ProjectFile:
        return cls(
            name=name,
            spec=spec,
            selection=ProjectSelection(
                material_id=material_id,
                core_id=core_id,
                wire_id=wire_id,
            ),
        )


def save_project(path: Path | str, state: ProjectFile) -> Path:
    """Serialize ``state`` to ``path`` (creates parents if needed).

    Always writes ``.pfc`` extension — appended if the user typed a
    bare path. Returns the resolved final ``Path``.
    """
    p = Path(path).expanduser()
    if p.suffix.lower() != PROJECT_FILE_EXTENSION:
        p = p.with_suffix(PROJECT_FILE_EXTENSION)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        state.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    )
    p.write_text(text + "\n", encoding="utf-8")
    return p


def load_project(path: Path | str) -> ProjectFile:
    """Read ``path`` into a ``ProjectFile``.

    Tolerates older ``version`` strings via Pydantic's
    ``extra="ignore"`` — unknown fields are dropped silently.
    Raises ``ValueError`` on malformed JSON or missing required
    fields (caller wraps with QMessageBox for the user).
    """
    p = Path(path).expanduser()
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Project file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Project file root must be a JSON object.")
    return ProjectFile(**data)


# ---------------------------------------------------------------------------
# Recent-projects list — stored in QSettings as a JSON-encoded list.
# Kept here (not in the menu module) so headless tests can drive it
# without pulling in Qt.
# ---------------------------------------------------------------------------
RECENTS_MAX = 5


def push_recent(recents: list[str], path: str) -> list[str]:
    """Return a new recents list with ``path`` at index 0, no dups,
    capped at ``RECENTS_MAX``."""
    out: list[str] = [path]
    for p in recents:
        if p == path:
            continue
        out.append(p)
        if len(out) >= RECENTS_MAX:
            break
    return out


def filter_existing(recents: list[str]) -> list[str]:
    """Drop recent entries whose files no longer exist on disk."""
    return [p for p in recents if Path(p).expanduser().is_file()]


def empty_state() -> ProjectFile:
    """A fresh new-project ``ProjectFile``. Used by ``File → New``."""
    return ProjectFile(
        name="Untitled Project",
        spec=Spec(),
        selection=ProjectSelection(),
    )
