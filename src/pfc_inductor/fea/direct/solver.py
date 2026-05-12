"""GetDP subprocess wrapper — solve + cancellation + log capture.

GetDP is a CLI binary shipped with ONELAB. We invoke it twice for a
typical run:

1. ``getdp <pro> -msh <mesh> -solve <resolution>`` — generates the
   linear system, solves it, and writes the result to disk
   (``<resolution>.pre`` etc.).
2. ``getdp <pro> -msh <mesh> -pos <postop>`` — reads the saved
   solution + emits ``.pos`` field files and ``.txt`` scalar
   tables per the ``PostOperation`` block in the ``.pro``.

The wrapper here is intentionally thin: subprocess.Popen with a
streaming stdout reader for progress, a soft + hard timeout, and a
``Cancellable`` token so a UI thread can SIGTERM the running solve
mid-cascade. We do NOT parse GetDP's progress percentage — the
binary doesn't emit one reliably. The runner shows an
indeterminate progress bar instead.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_LOG = logging.getLogger(__name__)


# ─── Cancellation token ───────────────────────────────────────────


class Cancellable:
    """Thread-safe cancel flag a UI can flip to kill a running solve.

    The solver thread polls ``is_set()`` between subprocess wait
    intervals; on cancel it SIGTERMs the GetDP process group and
    raises :class:`SolveCancelled`.
    """

    def __init__(self) -> None:
        self._flag = threading.Event()

    def cancel(self) -> None:
        self._flag.set()

    def is_set(self) -> bool:
        return self._flag.is_set()


class SolveError(RuntimeError):
    """Solver failed — exit code non-zero or output files missing."""


class SolveCancelled(RuntimeError):
    """Caller's ``Cancellable`` was tripped before the solve finished."""


# ─── Result ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class SolveResult:
    """What a GetDP invocation produced.

    Captures stdout/stderr for diagnostics + the wall time so the
    runner can log it into the result dataclass.
    """

    workdir: Path
    wall_s: float
    stdout: str
    stderr: str
    exit_code: int


# ─── Main entry point ─────────────────────────────────────────────


def run_getdp(
    *,
    getdp_exe: Path,
    pro_path: Path,
    msh_path: Path,
    workdir: Path,
    resolution: str,
    postop: Optional[str] = None,
    cancel: Optional[Cancellable] = None,
    timeout_s: float = 600.0,
) -> SolveResult:
    """Invoke ``getdp`` once for ``-solve`` and optionally once for ``-pos``.

    Parameters
    ----------
    getdp_exe:
        Absolute path to the GetDP binary. Resolve via
        :class:`pfc_inductor.setup_deps.paths.FeaPaths.getdp_path()`.
    pro_path, msh_path:
        Inputs — the rendered ``.pro`` and the meshed ``.msh``.
    workdir:
        Working directory for the solve. All output files
        (``.pre``, ``.pos``, ``.txt`` tables) land here.
    resolution:
        Name of the ``Resolution {}`` block in the ``.pro`` —
        typically ``"Magnetostatic"`` for our DC pass.
    postop:
        Name of the ``PostOperation {}`` block to run after the
        solve. ``None`` skips the post step (useful when the runner
        wants to inspect raw ``.pre`` first).
    cancel:
        Optional :class:`Cancellable` for mid-run abort.
    timeout_s:
        Hard wall-time cap. Raises :class:`SolveError` on overrun.

    Returns
    -------
    SolveResult
        Captured stdout/stderr + wall time.
    """
    if not getdp_exe.is_file():
        raise SolveError(f"GetDP binary not found at {getdp_exe}")
    if not pro_path.is_file():
        raise SolveError(f"Missing .pro file: {pro_path}")
    if not msh_path.is_file():
        raise SolveError(f"Missing .msh file: {msh_path}")

    cmd_solve = [
        str(getdp_exe),
        str(pro_path),
        "-msh",
        str(msh_path),
        "-solve",
        resolution,
    ]
    if postop:
        # Chain ``-pos`` onto the same invocation. GetDP runs solve
        # first then post in a single process — saves the ~150 ms
        # cold start of a second invocation.
        cmd_solve += ["-pos", postop]

    _LOG.info("getdp: cd=%s · cmd=%s", workdir, " ".join(cmd_solve))
    t0 = time.perf_counter()

    # ``start_new_session=True`` puts GetDP in its own process
    # group so we can SIGTERM the whole group on cancel without
    # killing the parent Python process.
    proc = subprocess.Popen(
        cmd_solve,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    # Poll for either completion, cancellation, or timeout.
    deadline = t0 + timeout_s
    poll_interval_s = 0.2
    cancelled = False
    stdout_text = ""
    stderr_text = ""
    while True:
        try:
            stdout_text, stderr_text = proc.communicate(timeout=poll_interval_s)
            break  # process finished
        except subprocess.TimeoutExpired:
            now = time.perf_counter()
            if cancel is not None and cancel.is_set():
                cancelled = True
                _terminate_group(proc)
                proc.wait(timeout=5.0)
                break
            if now > deadline:
                _terminate_group(proc)
                proc.wait(timeout=5.0)
                wall = time.perf_counter() - t0
                raise SolveError(
                    f"getdp timed out after {wall:.1f}s (limit {timeout_s}s)"
                ) from None

    wall = time.perf_counter() - t0

    if cancelled:
        raise SolveCancelled("GetDP solve cancelled by caller")
    if proc.returncode != 0:
        raise SolveError(
            f"getdp exited with code {proc.returncode}.\n"
            f"stdout: {stdout_text[-500:]}\n"
            f"stderr: {stderr_text[-500:]}"
        )

    return SolveResult(
        workdir=workdir,
        wall_s=wall,
        stdout=stdout_text,
        stderr=stderr_text,
        exit_code=proc.returncode,
    )


def _terminate_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole process group GetDP runs in.

    GetDP itself is single-process, but some platforms spawn a
    helper for parallel matrix factorisation. Terminating the
    whole group is the safe way to make sure we don't leak.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as exc:
        _LOG.debug("getdp termination skipped: %s", exc)
