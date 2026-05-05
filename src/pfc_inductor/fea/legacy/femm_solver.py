"""Subprocess wrapper around xfemm/FEMM."""
from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pfc_inductor.fea.probe import find_femm_binary
from pfc_inductor.fea.models import FEMMNotAvailable, FEMMSolveError


@dataclass
class SolveOutput:
    binary: str
    stdout: str
    stderr: str
    return_code: int
    elapsed_s: float
    fem_path: Path
    results_path: Path


def solve_lua(
    lua_path: Path,
    fem_path: Path,
    results_path: Path,
    timeout_s: int = 90,
    cwd: Optional[Path] = None,
) -> SolveOutput:
    """Invoke FEMM in batch mode on the supplied Lua script.

    Raises FEMMNotAvailable if no binary is detected.
    Raises FEMMSolveError on non-zero exit, missing results file, or timeout.
    """
    binary = find_femm_binary()
    if binary is None:
        raise FEMMNotAvailable("No FEMM/xfemm binary found on PATH")
    cwd = cwd or lua_path.parent
    cmd = [binary, "-lua", str(lua_path)]
    started = time.monotonic()
    try:
        cp = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise FEMMSolveError(
            f"FEMM solve timed out after {timeout_s}s "
            f"(stdout: {e.stdout!r}, stderr: {e.stderr!r})"
        ) from e
    elapsed = time.monotonic() - started
    if cp.returncode != 0:
        raise FEMMSolveError(
            f"FEMM exited {cp.returncode}.\n"
            f"stderr: {cp.stderr[-500:]}\nstdout: {cp.stdout[-500:]}"
        )
    if not results_path.exists():
        raise FEMMSolveError(
            f"Solver finished without writing the expected results file: "
            f"{results_path}\n"
            f"stdout: {cp.stdout[-500:]}\nstderr: {cp.stderr[-500:]}"
        )
    return SolveOutput(
        binary=binary, stdout=cp.stdout, stderr=cp.stderr,
        return_code=cp.returncode, elapsed_s=elapsed,
        fem_path=fem_path, results_path=results_path,
    )
