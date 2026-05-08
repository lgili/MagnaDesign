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
from types import MappingProxyType
from typing import Any, ClassVar, Iterable, Iterator, Literal, Mapping, Optional

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
    """A single candidate's persisted state across all tiers.

    Tier-2/3/4 each refine the analytical Tier-1 numbers and
    write their refined ``loss_t{N}_W`` / ``temp_t{N}_C`` columns
    so the Top-N table can rank on the highest-fidelity numbers
    a candidate has reached. The ``loss_top_W`` / ``temp_top_C``
    properties COALESCE down the tier ladder so a downstream
    surface that doesn't care about *which* tier produced the
    number can read one column.
    """

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
    temp_t2_C: Optional[float] = None
    saturation_t2: Optional[bool] = None
    L_t3_uH: Optional[float] = None
    Bpk_t3_T: Optional[float] = None
    loss_t3_W: Optional[float] = None
    temp_t3_C: Optional[float] = None
    L_t4_uH: Optional[float] = None
    loss_t4_W: Optional[float] = None
    temp_t4_C: Optional[float] = None
    notes: Optional[dict[str, Any]] = None

    # ─── Highest-fidelity reads ─────────────────────────────────
    @property
    def loss_top_W(self) -> Optional[float]:
        """The most-refined loss available — Tier 4 wins over
        Tier 3 wins over Tier 2 wins over Tier 1. ``None`` when
        no tier has produced a loss number yet."""
        for v in (self.loss_t4_W, self.loss_t3_W, self.loss_t2_W, self.loss_t1_W):
            if v is not None:
                return v
        return None

    @property
    def temp_top_C(self) -> Optional[float]:
        """Same COALESCE behaviour for winding temperature."""
        for v in (self.temp_t4_C, self.temp_t3_C, self.temp_t2_C, self.temp_t1_C):
            if v is not None:
                return v
        return None

    @property
    def L_FEA_uH(self) -> Optional[float]:
        """Most-refined FEA inductance: Tier 4 cycle-averaged
        beats Tier 3 magnetostatic. Returns ``None`` when no FEA
        ran (Tier 1 / 2 only). The analytical L lives on the
        engine's ``DesignResult`` and is recovered by the caller
        re-resolving the candidate; we don't surface a
        Tier-1 L_uH column on the row to keep the schema lean."""
        for v in (self.L_t4_uH, self.L_t3_uH):
            if v is not None and v > 0:
                return v
        return None


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
    temp_t2_C      REAL,
    saturation_t2  INTEGER,
    L_t3_uH        REAL,
    Bpk_t3_T       REAL,
    loss_t3_W      REAL,
    temp_t3_C      REAL,
    L_t4_uH        REAL,
    loss_t4_W      REAL,
    temp_t4_C      REAL,
    notes          TEXT,
    PRIMARY KEY (run_id, candidate_key)
);

CREATE INDEX IF NOT EXISTS idx_candidates_run  ON candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_loss ON candidates(run_id, loss_t1_W);
"""

# Columns added after Phase A — applied in-place via ``ALTER TABLE``
# on existing stores so older `.cascade.db` files keep working.
# Order matters: SQLite ALTER TABLE only appends columns. Any new
# entry here is "safe to add, nullable, default NULL".
_TIER_REFINEMENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("temp_t2_C", "REAL"),
    ("loss_t3_W", "REAL"),
    ("temp_t3_C", "REAL"),
    ("loss_t4_W", "REAL"),
    ("temp_t4_C", "REAL"),
)


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
            self._apply_migrations(conn)

    @staticmethod
    def _apply_migrations(conn: sqlite3.Connection) -> None:
        """Add per-tier refinement columns to legacy stores.

        SQLite's ``ALTER TABLE ... ADD COLUMN`` is a fast metadata
        update (no row rewrite), so re-running on every open is
        cheap. We probe ``PRAGMA table_info`` instead of catching
        the duplicate-column exception — explicit + fast.
        """
        existing = {
            row[1]  # column name
            for row in conn.execute("PRAGMA table_info(candidates)")
        }
        for name, sql_type in _TIER_REFINEMENT_COLUMNS:
            if name not in existing:
                conn.execute(f"ALTER TABLE candidates ADD COLUMN {name} {sql_type}")

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
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
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

    # Candidate-row INSERT shared by `write_candidate` and the batched
    # variant. Defined once so the column ordering stays in sync. Column
    # order matches the schema; new tier-refinement columns appended
    # at the end so legacy migrations (ALTER TABLE ADD COLUMN) keep the
    # same physical layout.
    _INSERT_CANDIDATE_SQL = (
        "INSERT OR REPLACE INTO candidates "
        "(run_id, candidate_key, core_id, material_id, wire_id, N, gap_mm, "
        " highest_tier, feasible_t0, loss_t1_W, temp_t1_C, cost_t1_USD, "
        " loss_t2_W, temp_t2_C, saturation_t2, L_t3_uH, Bpk_t3_T, "
        " loss_t3_W, temp_t3_C, L_t4_uH, loss_t4_W, temp_t4_C, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        " ?, ?, ?, ?)"
    )

    @staticmethod
    def _candidate_row_params(run_id: str, row: CandidateRow) -> tuple:
        return (
            run_id,
            row.candidate_key,
            row.core_id,
            row.material_id,
            row.wire_id,
            row.N,
            row.gap_mm,
            row.highest_tier,
            _bool_to_int(row.feasible_t0),
            row.loss_t1_W,
            row.temp_t1_C,
            row.cost_t1_USD,
            row.loss_t2_W,
            row.temp_t2_C,
            _bool_to_int(row.saturation_t2),
            row.L_t3_uH,
            row.Bpk_t3_T,
            row.loss_t3_W,
            row.temp_t3_C,
            row.L_t4_uH,
            row.loss_t4_W,
            row.temp_t4_C,
            json.dumps(row.notes) if row.notes else None,
        )

    def write_candidate(self, run_id: str, row: CandidateRow) -> None:
        """Insert or replace a candidate row (idempotent on `candidate_key`).

        Single-row API kept for Tier 2/3/4 update paths where the loop
        already runs at human pace. Tier 0/1 should use
        :meth:`write_candidates_batch` — opening a fresh sqlite3 connection
        per row was the bottleneck behind the cascade's "first step never
        finishes" symptom (~1 ms × 1.7 M rows = ~30 min).
        """
        with self._connect() as conn:
            conn.execute(
                self._INSERT_CANDIDATE_SQL,
                self._candidate_row_params(run_id, row),
            )

    def write_candidates_batch(
        self,
        run_id: str,
        rows: Iterable[CandidateRow],
    ) -> int:
        """Insert/replace many rows in a single connection + transaction.

        Returns the number of rows written. Throughput on a Tier-0 sweep
        improves from ~1 000 rows/s (per-call connection open + autocommit
        fsync) to ~50 000–100 000 rows/s on commodity SSDs — closing the
        cascade's headline bottleneck.

        Iterating ``rows`` lazily is fine; the method materialises them
        in chunks of ``_BATCH_CHUNK`` so a 1.7 M-element generator never
        builds a giant list in memory. Caller is free to pass a small
        list directly when batching is already done at the call site.
        """
        params_iter = (self._candidate_row_params(run_id, r) for r in rows)
        n_written = 0
        with self._connect() as conn:
            # Single explicit transaction per call — autocommit (the
            # default for `isolation_level=None`) would fsync after each
            # executemany, which defeats the batching.
            conn.execute("BEGIN")
            try:
                # Stream in fixed-size chunks so memory stays bounded.
                buf: list[tuple] = []
                for params in params_iter:
                    buf.append(params)
                    if len(buf) >= self._BATCH_CHUNK:
                        conn.executemany(self._INSERT_CANDIDATE_SQL, buf)
                        n_written += len(buf)
                        buf.clear()
                if buf:
                    conn.executemany(self._INSERT_CANDIDATE_SQL, buf)
                    n_written += len(buf)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return n_written

    # Chunk size for `write_candidates_batch`. 5 000 keeps each
    # `executemany` call under a few hundred KB of bound parameters
    # while still amortising the connection / transaction overhead.
    _BATCH_CHUNK = 5_000

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

    # Real columns that are safe to ORDER BY directly. Whitelisted
    # so the format-string in the SELECT below can't be a SQL-injection
    # vector.
    _ORDER_BY_REAL_COLUMNS: frozenset[str] = frozenset(
        {
            "loss_t1_W",
            "temp_t1_C",
            "cost_t1_USD",
            "loss_t2_W",
            "temp_t2_C",
            "loss_t3_W",
            "temp_t3_C",
            "L_t3_uH",
            "loss_t4_W",
            "temp_t4_C",
            "L_t4_uH",
        }
    )
    # Virtual columns: COALESCE expressions that pick the highest-
    # fidelity number a candidate has reached. The Top-N table
    # consumers (UI + CLI) read these so a candidate that ran
    # through Tier 4 is sorted by Tier-4 loss, while a Tier-1-only
    # candidate sorts by Tier-1 loss without mode-flipping logic
    # at the call site.
    _ORDER_BY_VIRTUAL_EXPRESSIONS: ClassVar[Mapping[str, str]] = MappingProxyType(
        {
            "loss_top_W": "COALESCE(loss_t4_W, loss_t3_W, loss_t2_W, loss_t1_W)",
            "temp_top_C": "COALESCE(temp_t4_C, temp_t3_C, temp_t2_C, temp_t1_C)",
        },
    )

    def top_candidates(
        self,
        run_id: str,
        *,
        n: int = 50,
        order_by: str = "loss_top_W",
    ) -> list[CandidateRow]:
        """Top-``n`` candidates ordered by the given column (ascending).

        ``order_by`` accepts:

        - **Real columns** — any of
          :attr:`_ORDER_BY_REAL_COLUMNS` (per-tier loss / temp /
          cost / L). Use these when you want to rank on a specific
          tier's number (e.g. ``"loss_t1_W"`` to keep Tier-1's
          analytical ranking even after deeper tiers ran).
        - **Virtual columns** —
          ``"loss_top_W"`` / ``"temp_top_C"`` COALESCE down the
          tier ladder so a candidate that reached Tier 4 sorts by
          its Tier-4 number, while a Tier-1-only candidate sorts by
          Tier 1 — single sort, no mode-flipping logic at the call
          site. **This is the right default for surfacing the
          "best" Top-N to the user**: the table never shows a
          stale Tier-1 number when a deeper tier has refined it.

        Anything else raises ``ValueError`` to prevent SQL
        injection.
        """
        if order_by in self._ORDER_BY_REAL_COLUMNS:
            order_expr = order_by
            null_filter = order_by
        elif order_by in self._ORDER_BY_VIRTUAL_EXPRESSIONS:
            order_expr = self._ORDER_BY_VIRTUAL_EXPRESSIONS[order_by]
            null_filter = order_expr
        else:
            raise ValueError(f"Unsupported order_by column: {order_by!r}")
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM candidates WHERE run_id = ? "
                f"AND {null_filter} IS NOT NULL "
                f"ORDER BY {order_expr} ASC LIMIT ?",
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
        temp_t2_C=_safe_get(row, "temp_t2_C"),
        saturation_t2=_int_to_bool(row["saturation_t2"]),
        L_t3_uH=row["L_t3_uH"],
        Bpk_t3_T=row["Bpk_t3_T"],
        loss_t3_W=_safe_get(row, "loss_t3_W"),
        temp_t3_C=_safe_get(row, "temp_t3_C"),
        L_t4_uH=row["L_t4_uH"],
        loss_t4_W=_safe_get(row, "loss_t4_W"),
        temp_t4_C=_safe_get(row, "temp_t4_C"),
        notes=json.loads(row["notes"]) if row["notes"] else None,
    )


def _safe_get(row: sqlite3.Row, key: str) -> Any:
    """Defensive column read — returns ``None`` when the column
    is absent from the row (older stores that haven't seen the
    migration yet on this connection)."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _bool_to_int(value: Optional[bool]) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


def _int_to_bool(value: Optional[int]) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)
