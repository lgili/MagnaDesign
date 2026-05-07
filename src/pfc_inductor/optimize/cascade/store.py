"""SQLite-backed persistence for cascade runs.

Schema (Phase A; future tiers extend the columns of `candidates`):

    runs(
        run_id        TEXT PRIMARY KEY,
        started_at    INTEGER,        -- unix seconds
        spec_hash     TEXT,           -- Spec.canonical_hash()
        spec_json     TEXT,           -- full canonical spec, for resume
        db_versions   TEXT,           -- JSON {materials, cores, wires}
        config        TEXT,           -- JSON tier thresholds, K_i, etc.
        status        TEXT,           -- 'running' | 'cancelled' | 'done'
        pid           INTEGER         -- writer PID; helps detect zombie runs
    )

    candidates(
        run_id         TEXT,
        candidate_key  TEXT,          -- Candidate.key()
        core_id        TEXT,
        material_id    TEXT,
        wire_id        TEXT,
        N              INTEGER,
        gap_mm         REAL,
        highest_tier   INTEGER,        -- 0..4
        feasible_t0    INTEGER,        -- bool, nullable
        loss_t1_W      REAL,
        temp_t1_C      REAL,
        cost_t1_USD    REAL,
        loss_t2_W      REAL,
        saturation_t2  INTEGER,
        L_t3_uH        REAL,
        Bpk_t3_T       REAL,
        L_t4_uH        REAL,
        notes          TEXT,           -- JSON; warnings / errors
        PRIMARY KEY (run_id, candidate_key)
    )

The store is process-safe via SQLite WAL mode: any number of
processes (orchestrator + workers) can write concurrently. Reads
during writes do not block.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

from pfc_inductor.models import Spec

RunStatus = Literal["running", "cancelled", "done"]


@dataclass(frozen=True)
class RunRecord:
    """Header row from the `runs` table."""

    run_id: str
    started_at: int
    spec_hash: str
    spec_json: str
    db_versions: dict[str, str]
    config: dict[str, Any]
    status: RunStatus
    pid: int

    def spec(self) -> Spec:
        """Reconstruct the originating `Spec` from the stored JSON."""
        return Spec.model_validate_json(self.spec_json)


@dataclass(frozen=True)
class CandidateRow:
    """A single candidate's persisted state across all tiers."""

    candidate_key: str
    core_id: str
    material_id: str
    wire_id: str
    N: Optional[int]
    gap_mm: Optional[float]
    highest_tier: int
    feasible_t0: Optional[bool] = None
    loss_t1_W: Optional[float] = None
    temp_t1_C: Optional[float] = None
    cost_t1_USD: Optional[float] = None
    loss_t2_W: Optional[float] = None
    saturation_t2: Optional[bool] = None
    L_t3_uH: Optional[float] = None
    Bpk_t3_T: Optional[float] = None
    L_t4_uH: Optional[float] = None
    notes: Optional[dict[str, Any]] = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  INTEGER NOT NULL,
    spec_hash   TEXT NOT NULL,
    spec_json   TEXT NOT NULL,
    db_versions TEXT NOT NULL,
    config      TEXT NOT NULL,
    status      TEXT NOT NULL,
    pid         INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_status   ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_specHash ON runs(spec_hash);

CREATE TABLE IF NOT EXISTS candidates (
    run_id         TEXT NOT NULL,
    candidate_key  TEXT NOT NULL,
    core_id        TEXT NOT NULL,
    material_id    TEXT NOT NULL,
    wire_id        TEXT NOT NULL,
    N              INTEGER,
    gap_mm         REAL,
    highest_tier   INTEGER NOT NULL,
    feasible_t0    INTEGER,
    loss_t1_W      REAL,
    temp_t1_C      REAL,
    cost_t1_USD    REAL,
    loss_t2_W      REAL,
    saturation_t2  INTEGER,
    L_t3_uH        REAL,
    Bpk_t3_T       REAL,
    L_t4_uH        REAL,
    notes          TEXT,
    PRIMARY KEY (run_id, candidate_key)
);

CREATE INDEX IF NOT EXISTS idx_candidates_run  ON candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_loss ON candidates(run_id, loss_t1_W);
"""


class RunStore:
    """SQLite store for cascade runs and candidates.

    Multiple processes may share a single store path. WAL mode lets
    workers write concurrently without blocking readers (UI, status
    polling). All public methods are thread/process-safe.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

    # ─── Connection management ────────────────────────────────────────

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # 30 s timeout absorbs short write contention without raising.
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ─── Runs ─────────────────────────────────────────────────────────

    def create_run(
        self,
        spec: Spec,
        db_versions: dict[str, str],
        config: dict[str, Any] | None = None,
    ) -> str:
        """Insert a new `runs` row and return the generated `run_id`.

        The `run_id` is a 16-hex-char random token prefixed by an
        ISO date stamp — readable in logs but unique enough to avoid
        collisions.
        """
        cfg = config or {}
        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs "
                "(run_id, started_at, spec_hash, spec_json, db_versions, config, status, pid) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    int(time.time()),
                    spec.canonical_hash(),
                    spec.model_dump_json(),
                    json.dumps(db_versions, sort_keys=True),
                    json.dumps(cfg, sort_keys=True),
                    "running",
                    os.getpid(),
                ),
            )
        return run_id

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_run(row)

    def update_status(self, run_id: str, status: RunStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ? WHERE run_id = ?",
                (status, run_id),
            )

    def list_runs(self, *, status: Optional[RunStatus] = None) -> list[RunRecord]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC",
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE status = ? ORDER BY started_at DESC",
                    (status,),
                ).fetchall()
        return [_row_to_run(r) for r in rows]

    def find_resumable_run(self, spec_hash: str) -> Optional[RunRecord]:
        """Most-recent `running` run for the given spec hash, if any."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE status = 'running' AND spec_hash = ? "
                "ORDER BY started_at DESC LIMIT 1",
                (spec_hash,),
            ).fetchone()
        return _row_to_run(row) if row else None

    # ─── Candidates ───────────────────────────────────────────────────

    def write_candidate(self, run_id: str, row: CandidateRow) -> None:
        """Insert or replace a candidate row (idempotent on `candidate_key`)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO candidates "
                "(run_id, candidate_key, core_id, material_id, wire_id, N, gap_mm, "
                " highest_tier, feasible_t0, loss_t1_W, temp_t1_C, cost_t1_USD, "
                " loss_t2_W, saturation_t2, L_t3_uH, Bpk_t3_T, L_t4_uH, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, row.candidate_key, row.core_id, row.material_id,
                    row.wire_id, row.N, row.gap_mm, row.highest_tier,
                    _bool_to_int(row.feasible_t0),
                    row.loss_t1_W, row.temp_t1_C, row.cost_t1_USD,
                    row.loss_t2_W, _bool_to_int(row.saturation_t2),
                    row.L_t3_uH, row.Bpk_t3_T, row.L_t4_uH,
                    json.dumps(row.notes) if row.notes else None,
                ),
            )

    def candidate_keys(self, run_id: str) -> set[str]:
        """All `candidate_key`s already written for `run_id` — for resume.

        Returning a set lets the orchestrator do O(1) `key in seen`
        membership checks without any further I/O.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT candidate_key FROM candidates WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        return {r["candidate_key"] for r in rows}

    def candidate_count(self, run_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM candidates WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def top_candidates(
        self,
        run_id: str,
        *,
        n: int = 50,
        order_by: str = "loss_t1_W",
    ) -> list[CandidateRow]:
        """Top-`n` candidates ordered by the given column (ascending).

        Only `loss_t1_W`, `temp_t1_C`, `cost_t1_USD`, `loss_t2_W` are
        accepted as `order_by` — anything else raises to prevent SQL
        injection.
        """
        if order_by not in {"loss_t1_W", "temp_t1_C", "cost_t1_USD", "loss_t2_W"}:
            raise ValueError(f"Unsupported order_by column: {order_by!r}")
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM candidates WHERE run_id = ? "
                f"AND {order_by} IS NOT NULL "
                f"ORDER BY {order_by} ASC LIMIT ?",
                (run_id, n),
            ).fetchall()
        return [_row_to_candidate(r) for r in rows]


# ─── Row deserialisation helpers ──────────────────────────────────────

def _row_to_run(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        started_at=row["started_at"],
        spec_hash=row["spec_hash"],
        spec_json=row["spec_json"],
        db_versions=json.loads(row["db_versions"]),
        config=json.loads(row["config"]),
        status=row["status"],
        pid=row["pid"],
    )


def _row_to_candidate(row: sqlite3.Row) -> CandidateRow:
    return CandidateRow(
        candidate_key=row["candidate_key"],
        core_id=row["core_id"],
        material_id=row["material_id"],
        wire_id=row["wire_id"],
        N=row["N"],
        gap_mm=row["gap_mm"],
        highest_tier=row["highest_tier"],
        feasible_t0=_int_to_bool(row["feasible_t0"]),
        loss_t1_W=row["loss_t1_W"],
        temp_t1_C=row["temp_t1_C"],
        cost_t1_USD=row["cost_t1_USD"],
        loss_t2_W=row["loss_t2_W"],
        saturation_t2=_int_to_bool(row["saturation_t2"]),
        L_t3_uH=row["L_t3_uH"],
        Bpk_t3_T=row["Bpk_t3_T"],
        L_t4_uH=row["L_t4_uH"],
        notes=json.loads(row["notes"]) if row["notes"] else None,
    )


def _bool_to_int(value: Optional[bool]) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


def _int_to_bool(value: Optional[int]) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)
