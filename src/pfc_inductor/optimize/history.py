"""Persistence layer for optimizer Run History + Recent Picks.

Two lightweight stores, both JSON files under
``platformdirs.user_data_dir("MagnaDesign", "MagnaDesign")``:

- ``optimizer_recent_picks.json`` — last 5 applied design triples
  ``(material_id, core_id, wire_id)`` plus a display label and an
  ISO-8601 timestamp. Used by the "Recent picks" dropdown next to
  the Apply button so the engineer can re-apply a recent design
  without re-running a sweep.

- ``optimizer_run_history.json`` — last 10 sweep runs, each a small
  metadata blob: timestamp, combination count, feasible count, the
  objective key in effect, and the top-1 winner's IDs + score. Used
  by the "Run history" dropdown above the table so the engineer
  can see "what did I sweep last week, who won?" at a glance and
  re-apply that winner without re-sweeping.

Both stores are intentionally small (IDs + scalars only — no
``SweepResult``/``DesignResult`` payloads), which keeps the file
size under 10 kB even after months of use and avoids the
fragility of pickling rich Pydantic models across app versions.
Re-running the full sweep with the same filters is the right
recovery path if the engineer wants the complete ranking back.

All operations are best-effort: a missing or corrupt file just
returns an empty history. We never raise from this module — the
optimizer continues to function even when the disk is unwritable.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from platformdirs import user_data_dir

_LOG = logging.getLogger(__name__)

_RECENT_PICKS_FILE = "optimizer_recent_picks.json"
_RUN_HISTORY_FILE = "optimizer_run_history.json"

MAX_RECENT_PICKS = 5
MAX_RUN_HISTORY = 10


def _history_dir() -> Path:
    """Resolve and ensure the user-data directory for both stores."""
    path = Path(user_data_dir("MagnaDesign", "MagnaDesign"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_json_list(file_name: str) -> list[dict[str, Any]]:
    """Read ``file_name`` from the history dir as a JSON list.

    Returns ``[]`` if the file is missing, unreadable, or contains a
    non-list payload. Never raises.
    """
    try:
        path = _history_dir() / file_name
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.debug("history: %s unreadable (%s) — returning empty list", file_name, exc)
        return []


def _save_json_list(file_name: str, items: list[dict[str, Any]]) -> None:
    """Atomically write ``items`` to ``file_name`` in the history dir.

    Uses the standard "write to .tmp, rename" pattern so a crash mid-
    write can't corrupt the existing file. Failures are logged but
    not raised — the UI continues whether or not persistence succeeds.
    """
    try:
        path = _history_dir() / file_name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        _LOG.warning("history: failed to write %s: %s", file_name, exc)


# ─── Recent picks ─────────────────────────────────────────────────


def record_pick(
    material_id: str,
    core_id: str,
    wire_id: str,
    label: str,
) -> None:
    """Append a freshly-applied selection to the recent-picks store.

    Dedupes on ``(material_id, core_id, wire_id)`` — re-applying the
    same triple moves it to the top instead of accumulating dupes.
    The list is capped at ``MAX_RECENT_PICKS``.
    """
    items = _load_json_list(_RECENT_PICKS_FILE)
    key = (material_id, core_id, wire_id)
    items = [
        it for it in items if (it.get("material_id"), it.get("core_id"), it.get("wire_id")) != key
    ]
    items.insert(
        0,
        {
            "material_id": material_id,
            "core_id": core_id,
            "wire_id": wire_id,
            "label": label,
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    _save_json_list(_RECENT_PICKS_FILE, items[:MAX_RECENT_PICKS])


def recent_picks() -> list[dict[str, Any]]:
    """Return the recent-picks list, newest-first. Capped at 5."""
    return _load_json_list(_RECENT_PICKS_FILE)[:MAX_RECENT_PICKS]


# ─── Run history ──────────────────────────────────────────────────


def record_run(
    *,
    n_combinations: int,
    n_feasible: int,
    objective: str,
    top_pick: Optional[dict[str, Any]] = None,
    filter_summary: str = "",
) -> None:
    """Append a completed sweep's summary to the run-history store.

    ``top_pick`` is a small dict — typically
    ``{"material_id", "core_id", "wire_id", "P_total_W",
    "volume_cm3", "label"}`` — describing the #1-ranked design at
    the moment the sweep finished. Stored so the engineer can re-
    apply that winner from history without re-running the sweep.

    ``filter_summary`` is a short human-readable string like
    ``"3 mats × 28 cores × 1k wires"`` — used as the dropdown label.

    The list is capped at ``MAX_RUN_HISTORY``.
    """
    items = _load_json_list(_RUN_HISTORY_FILE)
    items.insert(
        0,
        {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "n_combinations": int(n_combinations),
            "n_feasible": int(n_feasible),
            "objective": str(objective),
            "filter_summary": str(filter_summary),
            "top_pick": dict(top_pick) if top_pick else None,
        },
    )
    _save_json_list(_RUN_HISTORY_FILE, items[:MAX_RUN_HISTORY])


def recent_runs() -> list[dict[str, Any]]:
    """Return the run-history list, newest-first. Capped at 10."""
    return _load_json_list(_RUN_HISTORY_FILE)[:MAX_RUN_HISTORY]


def format_relative_age(iso_ts: str) -> str:
    """Format an ISO timestamp as ``"5 min ago"`` / ``"2 d ago"``.

    Used by both dropdowns to keep entries scannable. Falls back to
    the raw timestamp string when parsing fails — never raises.
    """
    try:
        ts = datetime.fromisoformat(iso_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        delta = now - ts
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60} min ago"
        if seconds < 86_400:
            return f"{seconds // 3600} h ago"
        return f"{seconds // 86_400} d ago"
    except (ValueError, TypeError):
        return iso_ts


__all__ = [
    "MAX_RECENT_PICKS",
    "MAX_RUN_HISTORY",
    "format_relative_age",
    "recent_picks",
    "recent_runs",
    "record_pick",
    "record_run",
]
