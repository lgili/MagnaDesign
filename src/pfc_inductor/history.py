"""Project history — git-like timeline of design iterations.

Every recalc the user triggers writes a snapshot here: the
project name, the full :class:`Spec`, the picked
material / core / wire IDs, and a summary of the resulting
:class:`DesignResult`. Subsequent iterations diff against the
previous snapshot, so the user can scroll back through their
design choices and see exactly what changed and what it cost
in losses, ΔT, volume.

Storage
-------
SQLite at ``~/Library/Application Support/MagnaDesign/history.db``
(macOS) or the platform equivalent (we reuse the same QStandardPaths
location the cascade store uses). Schema:

    CREATE TABLE history (
        id            INTEGER PRIMARY KEY,
        ts            INTEGER,        -- unix epoch (seconds)
        project       TEXT NOT NULL,  -- project name from File →
                                       --   Save As (or "Untitled")
        spec_json     TEXT NOT NULL,
        selection_json TEXT NOT NULL,
        summary_json  TEXT NOT NULL,  -- compact subset of
                                       --   DesignResult for the
                                       --   timeline preview
        note          TEXT DEFAULT ''
    );
    CREATE INDEX idx_history_project_ts ON history(project, ts DESC);

Why SQLite (not append-only JSON):
    Storage scales linearly with snapshot count; querying "last N
    for project X" is O(log N). JSON requires reading the whole
    file. The DB also gives us the future option of an "annotate
    snapshot" feature without re-encoding the whole file.

Pure-Python (no Qt dep) so unit tests can drive it headless and
the optimizer / worker threads can append snapshots without
pulling PySide6 into the cascade module.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def default_history_path() -> Path:
    """Return the platform's app-data directory + ``history.db``."""
    import platformdirs

    base = Path(platformdirs.user_data_dir("MagnaDesign", "MagnaDesign"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "history.db"


# ---------------------------------------------------------------------------
# Snapshot model — pure data.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Snapshot:
    """One row in the history table.

    Read-only by design — every recalc creates a new row rather
    than mutating an old one. Mirrors the git-commit semantics the
    feature is named after.
    """

    id: int
    ts: int  # unix epoch seconds
    project: str
    spec_json: str
    selection_json: str
    summary_json: str
    note: str = ""

    @property
    def spec(self) -> dict:
        return _safe_json(self.spec_json) or {}

    @property
    def selection(self) -> dict:
        return _safe_json(self.selection_json) or {}

    @property
    def summary(self) -> dict:
        return _safe_json(self.summary_json) or {}

    @property
    def topology(self) -> str:
        return str(self.spec.get("topology", ""))

    @property
    def headline(self) -> str:
        """One-line title for the timeline entry. Format:
        ``Pout=1500W f_sw=100kHz Loss=3.15W ΔT=18°C``."""
        spec = self.spec
        s = self.summary
        bits = []
        if "Pout_W" in spec:
            bits.append(f"P={spec['Pout_W']:.0f}W")
        if "f_sw_kHz" in spec:
            bits.append(f"fsw={spec['f_sw_kHz']:.0f}kHz")
        if "loss_W" in s:
            bits.append(f"Loss={s['loss_W']:.2f}W")
        if "T_rise_C" in s:
            bits.append(f"ΔT={s['T_rise_C']:.0f}°C")
        if "L_actual_uH" in s:
            bits.append(f"L={s['L_actual_uH']:.0f}µH")
        return "  ·  ".join(bits) if bits else "(empty)"


def _safe_json(raw: str) -> Optional[dict]:
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Store — SQLite-backed, thread-safe via ``check_same_thread=False``.
# ---------------------------------------------------------------------------
class HistoryStore:
    """SQLite-backed snapshot log.

    Constructed once per app session; lazy-creates the schema on
    first ``append``. Safe to share across the main thread and
    worker threads (we open with ``check_same_thread=False`` and
    every public method serialises through a single ``Connection``).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or default_history_path()
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY,
                    ts INTEGER NOT NULL,
                    project TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    selection_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                )"""
            )
            self._conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_history_project_ts
                   ON history(project, ts DESC)"""
            )

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------
    def append(
        self,
        project: str,
        spec: dict | object,
        selection: dict,
        summary: dict,
        note: str = "",
    ) -> int:
        """Insert a snapshot. Returns the row id.

        ``spec`` may be a Pydantic model (``Spec``) — we
        ``model_dump(mode="json")`` it before serialising — or a
        plain dict already in JSON-compatible form."""
        spec_dict = spec.model_dump(mode="json") if hasattr(spec, "model_dump") else spec
        ts = int(time.time())
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO history
                   (ts, project, spec_json, selection_json,
                    summary_json, note)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    ts,
                    project,
                    json.dumps(spec_dict, ensure_ascii=False),
                    json.dumps(selection, ensure_ascii=False),
                    json.dumps(summary, ensure_ascii=False),
                    note,
                ),
            )
            return int(cur.lastrowid or 0)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def list_snapshots(
        self,
        project: Optional[str] = None,
        limit: int = 100,
    ) -> list[Snapshot]:
        """Most-recent-first list of snapshots. ``project=None``
        returns everything across projects."""
        # ``id DESC`` is the tiebreaker for snapshots that landed
        # in the same wall-clock second (rapid recalcs during a
        # tight iteration loop). Without it the list-order is
        # SQLite-arbitrary, which makes the prior-snapshot diff
        # ("what did this last recalc change?") read garbage.
        if project is None:
            cur = self._conn.execute(
                """SELECT * FROM history
                   ORDER BY ts DESC, id DESC LIMIT ?""",
                (limit,),
            )
        else:
            cur = self._conn.execute(
                """SELECT * FROM history
                   WHERE project = ?
                   ORDER BY ts DESC, id DESC LIMIT ?""",
                (project, limit),
            )
        return [
            Snapshot(
                id=int(r["id"]),
                ts=int(r["ts"]),
                project=r["project"],
                spec_json=r["spec_json"],
                selection_json=r["selection_json"],
                summary_json=r["summary_json"],
                note=r["note"] or "",
            )
            for r in cur.fetchall()
        ]

    def projects(self) -> list[str]:
        """Distinct project names in the store, alphabetical."""
        cur = self._conn.execute("SELECT DISTINCT project FROM history ORDER BY project")
        return [r["project"] for r in cur.fetchall()]

    def annotate(self, snapshot_id: int, note: str) -> None:
        """Update the free-form ``note`` field on a snapshot."""
        with self._conn:
            self._conn.execute(
                "UPDATE history SET note = ? WHERE id = ?",
                (note, snapshot_id),
            )

    def delete(self, snapshot_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM history WHERE id = ?", (snapshot_id,))

    def clear_project(self, project: str) -> int:
        """Delete every snapshot for a project. Returns count."""
        with self._conn:
            cur = self._conn.execute("DELETE FROM history WHERE project = ?", (project,))
            return cur.rowcount

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Diff helpers — pure, used by the UI to render the timeline detail.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldDiff:
    """One changed field between two snapshots."""

    path: str  # dotted key, e.g. ``"spec.f_sw_kHz"``
    before: object
    after: object
    delta: Optional[float] = None  # absolute numeric delta when applicable
    delta_pct: Optional[float] = None
    is_better: Optional[bool] = None  # for summary metrics: lower-is-better
    # → True if after < before, etc.


def diff_snapshots(a: Snapshot, b: Snapshot) -> list[FieldDiff]:
    """Return the list of fields that differ between snapshot
    ``a`` (older) and snapshot ``b`` (newer). Includes spec,
    selection, and summary changes — all keyed by a dotted path
    so the UI can group them by section.
    """
    out: list[FieldDiff] = []

    # spec.* — every key that exists in either side, comparing strict.
    out.extend(_diff_dict(a.spec, b.spec, prefix="spec", better_lower=_BETTER_LOWER_KEYS))
    # selection.* — strings only, no numeric ordering.
    out.extend(_diff_dict(a.selection, b.selection, prefix="selection", better_lower=set()))
    # summary.* — same numeric rules as spec for the metrics that
    # exist in both (loss, ΔT, mass, cost — lower is better;
    # efficiency — higher is better).
    out.extend(
        _diff_dict(
            a.summary,
            b.summary,
            prefix="summary",
            better_lower=_BETTER_LOWER_KEYS,
            better_higher=_BETTER_HIGHER_KEYS,
        )
    )
    return out


# Domain rules for "did this change improve the design?".
_BETTER_LOWER_KEYS: frozenset[str] = frozenset(
    {
        "loss_W",
        "P_total_W",
        "T_rise_C",
        "T_winding_C",
        "mass_g",
        "cost_USD",
        "Volume_cm3",
    }
)
_BETTER_HIGHER_KEYS: frozenset[str] = frozenset(
    {
        "eta_pct",
        "sat_margin_pct",
    }
)


def _diff_dict(
    a: dict,
    b: dict,
    *,
    prefix: str,
    better_lower: frozenset = frozenset(),
    better_higher: frozenset = frozenset(),
) -> Iterable[FieldDiff]:
    """Generator over per-key differences. Skips nested dicts —
    the schemas we diff are flat at the level we care about; if a
    nested ``losses: {...}`` shows up its keys also live at the
    summary top level."""
    keys = set(a.keys()) | set(b.keys())
    for k in sorted(keys):
        va, vb = a.get(k), b.get(k)
        if va == vb:
            continue
        delta: Optional[float] = None
        delta_pct: Optional[float] = None
        is_better: Optional[bool] = None
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = float(vb) - float(va)
            if abs(va) > 1e-12:
                delta_pct = delta / abs(va) * 100.0
            if k in better_lower:
                is_better = vb < va
            elif k in better_higher:
                is_better = vb > va
        yield FieldDiff(
            path=f"{prefix}.{k}",
            before=va,
            after=vb,
            delta=delta,
            delta_pct=delta_pct,
            is_better=is_better,
        )


# ---------------------------------------------------------------------------
# Convenience builder — assemble a summary dict from a DesignResult.
# ---------------------------------------------------------------------------
def summary_from_result(result) -> dict:
    """Reduce a full ``DesignResult`` to the compact dict the
    timeline displays. Picks the metrics designers actually
    compare iteration-to-iteration; the full result stays in the
    .pfc file or the cascade store for deeper analysis."""
    losses = getattr(result, "losses", None)
    return {
        "L_actual_uH": _g(result, "L_actual_uH"),
        "N_turns": _g(result, "N_turns"),
        "B_pk_T": _g(result, "B_pk_T"),
        "sat_margin_pct": _g(result, "sat_margin_pct"),
        "loss_W": (
            (_g(losses, "P_cu_dc_W") or 0)
            + (_g(losses, "P_cu_ac_W") or 0)
            + (_g(losses, "P_core_line_W") or 0)
            + (_g(losses, "P_core_ripple_W") or 0)
        )
        if losses
        else None,
        "T_rise_C": _g(result, "T_rise_C"),
        "T_winding_C": _g(result, "T_winding_C"),
        "Ku_actual": _g(result, "Ku_actual"),
        "converged": _g(result, "converged"),
    }


def _g(obj, attr):
    if obj is None:
        return None
    v = getattr(obj, attr, None)
    return v
