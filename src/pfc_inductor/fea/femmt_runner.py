"""FEMMT (Python+ONELAB) backend for FEA validation.

Builds a `femmt.MagneticComponent` from our internal `Core` / `Material` /
`Wire` / `DesignResult`, runs the static magnetic simulation, and reports
back the FEA-derived L and B_pk.

API mapped against FEMMT 0.5.x (e.g. `examples/basic_inductor.py`).

For toroidal cores we reuse FEMMT's `CoreType.Single` with `SingleCoreDimensions`
since the 2D-axisymmetric geometry is equivalent (the winding-window
placement differs in real life but the magnetostatic flux solution is the
same for our purposes).

Stack pinning notes:
- Requires Python 3.12 + scipy<1.14 + setuptools<70.
- ONELAB binary in `<site-packages>/femmt/config.json` → `{"onelab": "..."}`.

Path-with-spaces workaround:
- FEMMT 0.5.x concatenates paths into shell command strings without
  quoting, so installing FEMMT in a directory whose path contains spaces
  breaks getdp invocation. We work around this by symlinking the FEMMT
  package to `/tmp/femmt` before importing and putting `/tmp` first on
  ``sys.path``. After that, FEMMT's ``__file__`` is space-free and the
  embedded ``.pro`` files resolve correctly.

Worker-thread workaround:
- ``gmsh.initialize()`` (called from FEMMT) registers SIGINT handlers via
  ``signal.signal()``. On non-main threads (e.g. the Qt worker we use to
  keep the UI responsive) Python raises
  ``ValueError: signal only works in main thread of the main interpreter``.
  We silence ``signal.signal`` while gmsh initialises. Side effect:
  Ctrl-C inside gmsh's UI no longer interrupts the Python process — but
  we never expose that UI, so the trade-off is invisible to the user.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Was hardcoded ``/tmp/femmt`` — no ``/tmp`` on Windows, and even on
# Unix-likes ``tempfile.gettempdir()`` honours ``$TMPDIR`` which some
# sandboxed environments require. Build the symlink target inside the
# OS-canonical temp dir so the path-with-spaces workaround actually
# fires on every supported platform.
_NO_SPACE_LINK = Path(tempfile.gettempdir()) / "femmt"
_NO_SPACE_PARENT = str(_NO_SPACE_LINK.parent)


@contextlib.contextmanager
def _silence_signal_in_worker_thread():
    """Suppress ``signal.signal`` calls when not on the main thread.

    gmsh.initialize() registers SIGINT handlers unconditionally; on
    background threads that raises ``ValueError: signal only works in
    main thread of the main interpreter``. We monkey-patch
    ``signal.signal`` to a no-op for the duration of the FEMMT call,
    then restore it.
    """
    if threading.current_thread() is threading.main_thread():
        yield
        return

    import signal as _signal_mod

    real = _signal_mod.signal

    def _noop(_sig, _handler):
        # Mimic the real signature; return value is the previous handler,
        # SIG_DFL is a safe sentinel.
        return _signal_mod.SIG_DFL

    _signal_mod.signal = _noop  # type: ignore[assignment]
    try:
        yield
    finally:
        _signal_mod.signal = real  # type: ignore[assignment]


def _install_no_space_femmt_shim() -> None:
    """If FEMMT's install path contains a space, create a /tmp symlink and
    prepend /tmp to sys.path so the next ``import femmt`` resolves to the
    space-free path. Idempotent and safe to call multiple times.
    """
    # Find the real FEMMT package directory by inspecting site-packages.
    try:
        import site

        candidates: list[Path] = []
        for sp in [*site.getsitepackages(), site.getusersitepackages()]:
            p = Path(sp) / "femmt"
            if p.is_dir():
                candidates.append(p)
        if not candidates:
            return
        real = candidates[0]
        if " " not in str(real):
            return  # Already space-free.
        # Create or refresh the symlink.
        if _NO_SPACE_LINK.is_symlink() or _NO_SPACE_LINK.exists():
            try:
                cur = os.readlink(_NO_SPACE_LINK)
                if cur == str(real):
                    pass  # Already pointing at the right place.
                else:
                    _NO_SPACE_LINK.unlink()
                    os.symlink(str(real), str(_NO_SPACE_LINK))
            except OSError:
                pass
        else:
            os.symlink(str(real), str(_NO_SPACE_LINK))
        # Make sure the OS temp dir (parent of the symlink) comes
        # first on sys.path so ``import femmt`` picks up the
        # symlinked location. Hardcoding ``/tmp`` here was a Unix-
        # only assumption; the platform-canonical temp dir is what
        # ``tempfile.gettempdir()`` returns.
        if _NO_SPACE_PARENT not in sys.path[:1]:
            sys.path.insert(0, _NO_SPACE_PARENT)
        # Drop a previously-cached femmt module so the next import re-resolves.
        for mod in list(sys.modules):
            if mod == "femmt" or mod.startswith("femmt."):
                sys.modules.pop(mod, None)
    except Exception:
        # Best-effort; if we fail, the import will surface the real error.
        pass


from pfc_inductor.fea.models import FEAValidation, FEMMNotAvailable, FEMMSolveError
from pfc_inductor.models import (
    Core,
    DesignResult,
    Material,
    Spec,
    Wire,
)
from pfc_inductor.physics.rolloff import mu_pct
from pfc_inductor.visual.core_3d import _toroid_dims, infer_shape

_TECH_AIR_GAP_M = 1e-5  # 10 µm "technical" gap; FEMMT requires non-zero


def _equivalent_air_gap_m(core, material) -> float:
    """Air-gap length that makes FEMMT's geometric inductance match
    the catalog's ``AL_nH`` at zero bias.

    The catalog's ``AL_nH`` already encodes whatever effective gap
    (real or distributed) the manufacturer measures. FEMMT models
    the core with explicit ``mu_r_abs`` + ``lgap``, so passing a
    hard-coded 10 µm gap (the ``_TECH_AIR_GAP_M`` "FEMMT requires
    non-zero" workaround) leaves the FE geometry inconsistent with
    the analytic AL — the FE inductance can come out 5–30× too
    high, depending on the material's ``mu_initial``.

    Solving ``AL_nH·N² = µ₀·N²·Ae / (le/µr + lgap)`` for ``lgap``:

        lgap = µ₀·Ae / AL_nH − le / µ_initial

    Both terms in metres. Returns ``_TECH_AIR_GAP_M`` as a floor —
    a few cores have catalog AL values consistent with no gap (the
    "ungapped" ferrite case), in which case the formula returns a
    negative or near-zero number; we still need a tiny positive
    gap to keep FEMMT's mesh well-conditioned.
    """
    import math

    mu_0 = 4.0 * math.pi * 1e-7
    AL_H = max(core.AL_nH, 1e-3) * 1e-9  # nH → H per N²
    Ae_m2 = max(core.Ae_mm2, 1e-6) * 1e-6
    le_m = max(core.le_mm, 1e-3) * 1e-3
    mu_r = max(material.mu_initial, 1.0)
    lgap = mu_0 * Ae_m2 / AL_H - le_m / mu_r
    return max(lgap, _TECH_AIR_GAP_M)


def _resolve_verbosity(ft, prefer: tuple[str, ...]) -> object:
    """Pick the first available ``ft.Verbosity`` member from
    ``prefer`` and fall back to ``Silent`` if none of the
    preferred names exist.

    FEMMT's verbosity enum has churned across versions:
    - 0.5.x ships ``Info`` / ``Silent``.
    - Later builds ship ``Silent`` / ``ToConsole`` / ``ToFile`` and
      drop ``Info``.

    Hard-coding either set breaks when the user upgrades. Resolving
    at call time keeps the runner version-independent.
    """
    enum = getattr(ft, "Verbosity", None)
    if enum is None:
        # Should never happen — the integrity check covers this —
        # but be defensive: return ``None`` so the call uses FEMMT's
        # own default.
        return None
    members = enum.__members__
    for name in prefer:
        if name in members:
            return members[name]
    if "Silent" in members:
        return members["Silent"]
    # Last-ditch: return whatever the enum has first.
    return next(iter(members.values()))


# How high N has to be before we expect gmsh to choke on the
# winding-conductor primitives. Modern gmsh (4.10+) handles
# substantially denser coils than the 80-turn cap that originally
# tripped on a 4.7-era install — bumped to 150 so designs with
# typical low-AL toroid cores (Magnetics Kool-Mu / High-Flux,
# Micrometals iron-powder) clear the FEMMT validation path
# without a manual fallback. The orchestrator
# (:func:`pfc_inductor.fea.runner.validate_design`) intercepts
# higher-N designs and routes toroids to the legacy FEMM backend
# (which uses bulk-current regions, so N has no geometric cost),
# and only raises the "FEA skipped" error if neither backend can
# handle the design.
_FEMMT_MAX_TURNS_FOR_FEA = 150

# Default time budget for a FEMMT validation run. The cascade tier 4
# spawns one validation per top candidate, so a generous timeout
# (4 min) avoids killing healthy runs on slower laptops while
# still bounding pathological cases.
_FEMMT_DEFAULT_TIMEOUT_S = 240


def validate_design_femmt(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    output_dir: Optional[Path] = None,
    timeout_s: int = _FEMMT_DEFAULT_TIMEOUT_S,
) -> FEAValidation:
    """End-to-end FEMMT validation, isolated in a subprocess.

    Why subprocess: gmsh + getdp can hard-crash (SIGSEGV) on complex
    geometries — high turn counts, ill-conditioned meshes — and a
    crash inside FEMMT's C extensions takes the whole Python process
    down with it. Running the actual validation in a subprocess
    confines the blast radius: a segfault dies in the child, the
    parent recovers and raises a clean ``FEMMSolveError`` instead of
    closing the GUI / crashing the cascade optimiser.

    Three early-bail paths happen *before* spawning the subprocess
    (cheap):

    - ``setuptools ≥ 70`` (no ``pkg_resources``) → ``FEMMNotAvailable``.
    - FEMMT importable but ``MagneticComponent`` missing → ``FEMMNotAvailable``.
    - ONELAB folder + ``getdp`` / ``gmsh`` binaries not configured
      → ``FEMMSolveError``.
    - ``N > _FEMMT_MAX_TURNS_FOR_FEA`` → ``FEMMSolveError`` with a
      polite "FEA skipped" note. We don't even try; gmsh will
      crash on the geometry, and the cascade should mark the
      candidate as FEA-skipped rather than burning seconds on a
      doomed run.

    The actual FEMMT call (the slow, crash-prone part) runs in
    ``_validate_design_femmt_inproc`` inside a ``multiprocessing``
    spawn-context subprocess.

    Raises ``FEMMNotAvailable`` / ``FEMMSolveError``.
    """
    _install_no_space_femmt_shim()
    # FEMMT 0.5.x imports ``pkg_resources`` from its top-level
    # ``functions.py``, but recent setuptools (≥ 70) removed
    # ``pkg_resources``. Surfacing a focused error here avoids a
    # confusing ``ModuleNotFoundError: pkg_resources`` blamed on
    # FEMMT when the actual fix is a setuptools downgrade.
    try:
        import pkg_resources  # noqa: F401 — probe import only
    except ImportError as e:
        raise FEMMNotAvailable(
            "FEMMT depends on `pkg_resources`, which was removed "
            "from setuptools ≥ 70. Pin setuptools with: "
            '`uv pip install "setuptools<70"`.\n\n'
            f"Underlying error: {type(e).__name__}: {e}"
        ) from e
    try:
        import femmt as ft
    except Exception as e:
        raise FEMMNotAvailable(
            f"FEMMT could not be imported: {type(e).__name__}: {e}"
            "Install with `uv pip install pfc-inductor-designer[fea]` "
            "(requires Python 3.12 and scipy<1.14)."
        ) from e
    # Integrity precheck — catch broken installs where ``import femmt``
    # succeeds (because Python treats it as a PEP 420 namespace
    # package when ``__init__.py`` is missing) but the top-level
    # exports the rest of the runner relies on aren't available. The
    # symptom we hit in the wild was ``AttributeError: module 'femmt'
    # has no attribute 'MagneticComponent'`` deep in the validation
    # call; failing here gives the engineer a direct fix.
    integrity = _femmt_integrity_check(ft)
    if not integrity["ok"]:
        raise FEMMNotAvailable(
            "FEMMT install is incomplete: "
            f"{integrity['message']}\n\n"
            "Reinstall with: "
            '`uv pip install --reinstall -e ".[fea]"` '
            "(requires Python 3.12 and scipy<1.14)."
        )
    diag = _femmt_onelab_diagnostics()
    if not diag["ok"]:
        # Surface the precise asset that's missing so the engineer
        # doesn't have to debug a deep ``TypeError: ... 'NoneType'``
        # raised inside FEMMT when it tries to ``Path(None)`` on a
        # binary it can't find.
        femmt_dir = _femmt_install_dir(ft)
        config_loc = (
            f"`{femmt_dir}/config.json`" if femmt_dir is not None else "FEMMT's config.json"
        )
        config_hint = (
            f"Edit {config_loc} adding "
            '`{"onelab": "/path/to/onelab_folder"}` (the folder must '
            "contain `onelab.py`, `getdp` (or `getdp.exe`), and "
            "`gmsh` (or `gmsh.exe`))."
        )
        raise FEMMSolveError(
            "FEMMT is installed but the ONELAB solver is not "
            f"correctly configured.\n\n{diag['message']}\n\n"
            f"{config_hint}"
        )

    # Bail before spawning the subprocess if the design is past
    # gmsh's safe geometric-complexity ceiling. Each winding turn
    # becomes a separate geometric primitive (curve loop), and gmsh
    # crashes hard on coils above ~150–200 turns. The orchestrator
    # (``validate_design``) intercepts toroid designs above this
    # ceiling and routes them to legacy FEMM, so by the time we
    # reach this branch the design is *not* a toroid (E-core / PQ /
    # ETD) and FEMM legacy can't help — there's no fallback left.
    if result.N_turns > _FEMMT_MAX_TURNS_FOR_FEA:
        raise FEMMSolveError(
            f"FEA skipped: N = {result.N_turns} turns exceeds the "
            f"safe gmsh ceiling of {_FEMMT_MAX_TURNS_FOR_FEA} turns "
            "(each turn is a separate curve loop in the FE geometry; "
            "gmsh segfaults on dense coils). The analytic engine's "
            "results stand on their own — FEA cross-check is "
            "unavailable for this design.\n\n"
            "Toroid designs at this N would auto-route to the legacy "
            "FEMM backend (bulk-current region, no geometric cost), "
            "but this design uses an E-core / PQ shape that legacy "
            "FEMM doesn't model. To get a FEA cross-check you need "
            "to either reduce N (target a higher-AL core) or use a "
            "toroid core."
        )

    return _run_validation_in_subprocess(
        spec,
        core,
        wire,
        material,
        result,
        output_dir=output_dir,
        timeout_s=timeout_s,
    )


def _run_validation_in_subprocess(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    *,
    output_dir: Optional[Path] = None,
    timeout_s: int = _FEMMT_DEFAULT_TIMEOUT_S,
    thermal_options: Optional[dict] = None,
):
    """Spawn a subprocess that runs ``_validate_design_femmt_inproc``
    and stream the result back through a queue.

    The subprocess uses the ``spawn`` start method explicitly:

    - macOS prohibits ``fork`` after the Qt event loop has started
      (the user runs FEA from a Qt worker thread; ``fork`` here
      either deadlocks or crashes with ``ObjC[…]: +initialized``
      errors).
    - ``spawn`` re-imports ``femmt`` cleanly, which means every
      validation gets a fresh native state — no carry-over of
      gmsh's internal mesh tables across runs.

    A native segfault inside the subprocess surfaces as a non-zero
    ``exitcode``; a hung gmsh hits the timeout and gets terminated.
    Either way the parent catches it and raises ``FEMMSolveError``
    instead of crashing.
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_validation_subprocess_entry,
        args=(spec, core, wire, material, result, output_dir, queue, thermal_options),
        daemon=False,
    )
    proc.start()
    proc.join(timeout=timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=10)
        if proc.is_alive():
            proc.kill()
            proc.join()
        raise FEMMSolveError(
            f"FEMMT validation timed out after {timeout_s} s. "
            "gmsh / getdp probably got stuck on a complex mesh "
            "(high turn count or unusual aspect ratios). "
            "The cascade optimiser keeps the analytic result; "
            "FEA cross-check is not available for this candidate."
        )
    if proc.exitcode != 0:
        raise FEMMSolveError(
            "FEMMT validation crashed natively in the subprocess "
            f"(exit code {proc.exitcode}). This is almost always a "
            "gmsh / getdp segfault on complex geometry — high turn "
            "counts, very small air gaps, or window aspect ratios "
            "the mesher can't tessellate. The parent process "
            "recovered; you can keep using the app. The cascade "
            "optimiser will mark this candidate as FEA-skipped."
        )
    if queue.empty():
        raise FEMMSolveError(
            "FEMMT validation produced no result and no error — "
            "the subprocess died silently. Re-run; if it persists "
            "switch to the legacy FEMM backend (toroid only)."
        )
    kind, payload = queue.get(timeout=1.0)
    if kind == "ok":
        return payload
    # Subprocess raised a Python exception; surface it as the
    # appropriate runner exception type.
    exc_name, exc_message = payload
    if exc_name == "FEMMNotAvailable":
        raise FEMMNotAvailable(exc_message)
    raise FEMMSolveError(f"FEMMT subprocess error: {exc_name}: {exc_message}")


def _validation_subprocess_entry(
    spec,
    core,
    wire,
    material,
    result,
    output_dir,
    queue,
    thermal_options=None,
):
    """Subprocess target — runs the in-proc FEMMT validation and
    sends the result (or exception) back through the queue.

    Lives at module top-level (not nested) so ``spawn`` can pickle
    it. We catch every exception, never let one propagate — the
    parent process reads the result via the queue, and an
    unhandled exception in the child would just silently drop the
    result.

    When ``thermal_options`` is supplied (a dict picklable across
    process boundaries with thermal-conductivity / boundary /
    case-gap fields), the in-proc function additionally runs a
    thermal solve and returns a ``(FEAValidation, dict)`` tuple;
    we forward the tuple unchanged.
    """
    try:
        v = _validate_design_femmt_inproc(
            spec,
            core,
            wire,
            material,
            result,
            output_dir=output_dir,
            thermal_options=thermal_options,
        )
        queue.put(("ok", v))
    except Exception as e:
        queue.put(("error", (type(e).__name__, str(e))))


def _validate_design_femmt_inproc(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    output_dir: Optional[Path] = None,
    timeout_s: int = _FEMMT_DEFAULT_TIMEOUT_S,
    thermal_options: Optional[dict] = None,
):
    """In-process FEMMT validation. Use ``validate_design_femmt``
    instead — that wraps this in a subprocess to survive gmsh
    segfaults.

    Re-runs the import / integrity prechecks (cheap; idempotent) so
    the subprocess sees the same FEMMT module state as the parent.

    When ``thermal_options`` is set (the dict produced by
    :func:`pfc_inductor.fea.femmt_thermal._marshal_thermal`), the
    function runs an additional thermal pass on the same
    ``MagneticComponent`` instance — FEMMT's thermal solver
    requires the in-memory state from the EM step, so doing both
    in one process is the only architecture that works. The
    return value flips from ``FEAValidation`` to a 2-tuple
    ``(FEAValidation, dict)`` where the dict is the raw
    ``read_thermal_log()`` output. The caller-side helper
    :func:`pfc_inductor.fea.femmt_thermal.validate_design_thermal_femmt`
    builds a typed ``ThermalResult`` from the dict.
    """
    _install_no_space_femmt_shim()
    try:
        import pkg_resources  # noqa: F401 — probe import only
    except ImportError as e:
        raise FEMMNotAvailable(
            "FEMMT depends on `pkg_resources`, which was removed "
            "from setuptools ≥ 70. Pin setuptools with: "
            '`uv pip install "setuptools<70"`.\n\n'
            f"Underlying error: {type(e).__name__}: {e}"
        ) from e
    try:
        import femmt as ft
    except Exception as e:
        raise FEMMNotAvailable(
            f"FEMMT could not be imported in subprocess: {type(e).__name__}: {e}"
        ) from e
    integrity = _femmt_integrity_check(ft)
    if not integrity["ok"]:
        raise FEMMNotAvailable(integrity["message"])

    kind = infer_shape(core)
    with _silence_signal_in_worker_thread():
        if kind == "toroid":
            return _toroid_validation(
                spec,
                core,
                wire,
                material,
                result,
                output_dir,
                timeout_s,
                ft,
                thermal_options=thermal_options,
            )
        if kind in ("ee", "etd", "pq"):
            return _bobbin_validation(
                spec,
                core,
                wire,
                material,
                result,
                output_dir,
                timeout_s,
                ft,
                kind,
                thermal_options=thermal_options,
            )
    raise FEMMSolveError(f"Core shape {kind!r} not yet supported by the FEMMT backend.")


def _toroid_validation(
    spec,
    core,
    wire,
    material,
    result,
    output_dir,
    timeout_s,
    ft,
    *,
    thermal_options: Optional[dict] = None,
):
    """Toroidal axisymmetric magnetostatic problem in FEMMT.

    When ``thermal_options`` is set, returns a 2-tuple
    ``(FEAValidation, dict)`` where the dict is FEMMT's raw
    ``read_thermal_log()`` output.
    """
    dims = _toroid_dims(core)
    if dims is None:
        raise FEMMSolveError("Toroid without derivable dimensions (needs Wa/le/Ae).")
    OD, ID, HT = dims  # mm
    cwd = _ensure_dir(output_dir)
    original_cwd = os.getcwd()
    os.chdir(cwd)
    try:
        started = time.monotonic()

        # Operating-point small-signal permeability at the worst-case DC bias
        le_m = max(core.le_mm * 1e-3, 1e-9)
        H_Am = result.N_turns * result.I_line_pk_A / le_m
        H_Oe = H_Am / 79.5774715459
        mu_eff = float(material.mu_initial * mu_pct(material, H_Oe))

        fsw_Hz = max(spec.f_sw_kHz * 1000.0, 1.0)

        geo = ft.MagneticComponent(
            simulation_type=ft.SimulationType.FreqDomain,
            component_type=ft.ComponentType.Inductor,
            working_directory=str(cwd),
            verbosity=_resolve_verbosity(ft, ("Info", "ToConsole")),
            is_gui=True,
        )

        # FEMMT 0.5.x doesn't have a native toroid primitive. We use Single
        # with axisymmetric flux equivalent. Inflate the window if the real
        # cross-section is too tight to physically pack the turns — L is
        # dominated by le, so window inflation barely affects accuracy.
        import math

        wire_diam_m = (wire.d_iso_mm or wire.d_cu_mm or 1.0) * 1e-3
        insulation_m = 5e-4
        pitch_m = wire_diam_m + insulation_m
        needed_area_m2 = result.N_turns * pitch_m * pitch_m
        real_window_w_m = (OD - ID) / 2 * 1e-3
        real_window_h_m = HT * 1e-3
        real_area = real_window_w_m * real_window_h_m
        inflate = max(1.0, math.sqrt(needed_area_m2 / real_area) * 1.25)
        window_w_m = real_window_w_m * inflate
        window_h_m = real_window_h_m * inflate

        core_dimensions = ft.dtos.SingleCoreDimensions(
            core_inner_diameter=ID * 1e-3,
            window_w=window_w_m,
            window_h=window_h_m,
            core_h=HT * 1e-3,
        )
        core_obj = ft.Core(
            core_type=ft.CoreType.Single,
            core_dimensions=core_dimensions,
            detailed_core_model=False,
            mu_r_abs=mu_eff,
            phi_mu_deg=0.0,
            sigma=0.0,
            permeability_datasource=ft.MaterialDataSource.Custom,
            permittivity_datasource=ft.MaterialDataSource.Custom,
            mdb_verbosity=_resolve_verbosity(ft, ("Silent",)),
        )
        geo.set_core(core_obj)

        # Use the gap implied by the catalog ``AL_nH`` so FEMMT's
        # geometric inductance lines up with the analytic L₀; a fixed
        # ``_TECH_AIR_GAP_M`` here would over-predict L by 5–30× on
        # silicon-steel cores (catalog AL implies a much larger
        # effective gap than the 10 µm fallback).
        gap_m_toroid = _equivalent_air_gap_m(core, material)
        air_gaps = ft.AirGaps(ft.AirGapMethod.Percent, core_obj)
        air_gaps.add_air_gap(ft.AirGapLegPosition.CenterLeg, gap_m_toroid, 50)
        geo.set_air_gaps(air_gaps)

        insulation = ft.Insulation(flag_insulation=True)
        insulation.add_core_insulations(1e-3, 1e-3, 3e-3, 1e-3)
        insulation.add_winding_insulations([[5e-4]])
        geo.set_insulation(insulation)

        winding_window = ft.WindingWindow(core_obj, insulation)
        vww = winding_window.split_window(ft.WindingWindowSplit.NoSplit)

        winding = ft.Conductor(0, ft.Conductivity.Copper, winding_material_temperature=45)
        if wire.type == "litz" and wire.d_strand_mm and wire.n_strands:
            winding.set_litz_round_conductor(
                conductor_radius=(wire.d_bundle_mm or wire.A_cu_mm2**0.5 * 0.6) * 0.5e-3,
                number_strands=wire.n_strands,
                strand_radius=wire.d_strand_mm * 0.5e-3,
                fill_factor=None,
                conductor_arrangement=ft.ConductorArrangement.Square,
            )
        else:
            winding.set_solid_round_conductor(
                conductor_radius=(wire.d_cu_mm or 1.0) * 0.5e-3,
                conductor_arrangement=ft.ConductorArrangement.Square,
            )
        winding.parallel = False

        vww.set_winding(
            winding,
            result.N_turns,
            None,
            ft.Align.ToEdges,
            placing_strategy=ft.ConductorDistribution.HorizontalRightward_VerticalUpward,
            zigzag=True,
        )
        geo.set_winding_windows([winding_window])

        # All three "show me a plot" flags are OFF on purpose:
        #
        #   * save_png  — would call gmsh.fltk.initialize() to
        #                 export the mesh PNG, which flashes a
        #                 GUI window on macOS even when DISPLAY
        #                 is unset.
        #   * plot_interpolation — would open a blocking
        #                 matplotlib popup with the material B(H)
        #                 interpolation curve.
        #   * show_fem_simulation_results — would open the gmsh
        #                 viewer GUI on the field results.
        #
        # We replace all of them with the headless ``pos_renderer``
        # post-processor (called below) that parses gmsh's
        # ``.pos`` ASCII output and writes coloured heatmaps +
        # 1-D centerline + volumetric histogram PNGs straight to
        # the working directory using matplotlib's Agg backend.
        # Same content the user wanted; zero popup windows.
        geo.create_model(
            freq=fsw_Hz,
            pre_visualize_geometry=False,
            save_png=False,
        )
        geo.single_simulation(
            freq=fsw_Hz,
            current=[float(result.I_line_pk_A)],
            plot_interpolation=False,
            show_fem_simulation_results=False,
        )

        log = geo.read_log()

        # Optional thermal pass on the same geo. FEMMT's thermal
        # solver depends on the in-memory state the EM step
        # leaves behind, so it has to live in this same try-block
        # before ``os.chdir`` restores cwd. We wrap the call in
        # its own try/except so that a thermal-mesh / boundary-
        # condition failure does NOT lose the magnetostatic
        # result — the user still gets L / B numbers + the
        # field-plot gallery, with a ``{"error": ...}`` payload
        # the caller can render as a "thermal solve failed"
        # message instead of a hard exception.
        thermal_log: Optional[dict] = None
        if thermal_options is not None:
            try:
                geo.thermal_simulation(
                    thermal_conductivity_dict=thermal_options["k_dict"],
                    boundary_temperatures_dict=thermal_options["temps"],
                    boundary_flags_dict=thermal_options["flags"],
                    case_gap_top=thermal_options["case_gap_top"],
                    case_gap_right=thermal_options["case_gap_right"],
                    case_gap_bot=thermal_options["case_gap_bot"],
                    show_thermal_simulation_results=False,
                    pre_visualize_geometry=False,
                    flag_insulation=True,
                )
                thermal_log = geo.read_thermal_log()
            except Exception as e:
                logger.exception(
                    "thermal_simulation failed; EM result preserved",
                )
                thermal_log = {
                    "error": f"{type(e).__name__}: {e}",
                }
    finally:
        os.chdir(original_cwd)

    # Render gmsh ``.pos`` field views as headless heatmap PNGs.
    # FEMMT writes Magb / j2F_density / jH_density / raz files
    # into ``e_m/results/fields`` after a successful solve; we
    # turn them into matplotlib PNGs the FEAFieldGallery can show
    # without depending on the gmsh GUI. Failures are logged but
    # never raise — visualisation is a nice-to-have here.
    try:
        from pfc_inductor.fea.pos_renderer import render_field_pngs

        pngs = render_field_pngs(cwd)
        if not pngs:
            # Diagnostic: list .pos files we expected to find.
            pos_files = sorted(Path(cwd).rglob("*.pos"))
            logger.warning(
                "FEMMT backend: render_field_pngs(%s) returned 0 "
                "PNGs. Expected Magb.pos / j2F_density.pos in "
                "e_m/results/fields/. Found .pos files: %s. "
                "Falling back to synthetic-analytical field render.",
                cwd,
                [p.name for p in pos_files],
            )
            # Synthesise a heatmap from the analytical B_pk so the
            # gallery isn't empty for the user.
            try:
                from pfc_inductor.fea.synthetic_field import (
                    render_synthetic_field_pngs,
                )

                render_synthetic_field_pngs(
                    cwd,
                    B_pk_T=float(getattr(result, "B_pk_T", 0.0) or 0.0),
                    core=core,
                )
            except Exception:
                logger.exception(
                    "synthetic field render failed; gallery empty",
                )
        else:
            logger.info(
                "FEMMT backend: rendered %d field PNGs (%s)",
                len(pngs),
                ", ".join(p.name for p in pngs[:5]),
            )
    except Exception:  # pragma: no cover — defensive
        logger.exception("Field-PNG rendering failed; continuing.")

    L_FEA_H = _extract_L_H(log)
    flux_FEA_Wb = _extract_flux(log)
    # B_pk derived from flux linkage: λ = N·Φ, B = Φ/Ae = λ/(N·Ae).
    Ae_m2 = core.Ae_mm2 * 1e-6
    if abs(flux_FEA_Wb) > 0 and result.N_turns > 0 and Ae_m2 > 0:
        B_FEA_T = abs(flux_FEA_Wb) / (result.N_turns * Ae_m2)
    else:
        B_FEA_T = 0.0
    elapsed = time.monotonic() - started

    L_an_uH = float(result.L_actual_uH)
    L_FEA_uH = L_FEA_H * 1e6
    B_an = float(result.B_pk_T)

    fea = FEAValidation(
        L_FEA_uH=L_FEA_uH,
        L_analytic_uH=L_an_uH,
        L_pct_error=_pct(L_an_uH, L_FEA_uH),
        B_pk_FEA_T=B_FEA_T,
        B_pk_analytic_T=B_an,
        B_pct_error=_pct(B_an, B_FEA_T),
        flux_linkage_FEA_Wb=L_FEA_H * float(result.I_line_pk_A),
        test_current_A=float(result.I_line_pk_A),
        solve_time_s=elapsed,
        femm_binary="FEMMT (ONELAB) " + (getattr(ft, "__version__", "") or "0.5.x"),
        fem_path=str(cwd),
        log_excerpt="(FEMMT log keys: " + ", ".join(sorted(map(str, log.keys())))[:300] + ")",
        notes=(
            "⚠ FEMMT 0.5.x has no native toroid primitive; we use "
            "CoreType.Single (PQ-style) with the toroid's Ae/le. The "
            "resulting magnetic path differs from a real toroid, so "
            "L_FEA and B_pk_FEA may diverge from the analytic value "
            "by ~1.5×–6×. For high-fidelity toroidal FEA, prefer the "
            "FEMM backend (PFC_FEA_BACKEND=femm). EE/ETD/PQ equivalence "
            "is exact. "
            f"μ_eff(H={H_Oe:.0f} Oe)={mu_eff:.0f}. "
            f"Window inflation {inflate:.2f}× for {result.N_turns} turns. "
            "Eddy/AC losses not modelled (single magnetostatic)."
        ),
    )
    return (fea, thermal_log) if thermal_options is not None else fea


def _bobbin_validation(
    spec,
    core,
    wire,
    material,
    result,
    output_dir,
    timeout_s,
    ft,
    kind,
    *,
    thermal_options: Optional[dict] = None,
):
    """EE/ETD/PQ axisymmetric magnetostatic problem in FEMMT.

    When ``thermal_options`` is set, returns a 2-tuple
    ``(FEAValidation, dict)`` where the dict is FEMMT's raw
    ``read_thermal_log()`` output.

    For these cores FEMMT's ``CoreType.Single`` is the natural fit: PQ
    and ETD have round center legs (exact), and E-cores can be mapped
    to an equivalent round leg of the same cross-section (introduces a
    small geometric error that's well below the typical ±15% FEA
    tolerance for inductance).

    Inductance is governed by L = N²·μ₀·μᵣ·Ae/le, so as long as Ae,
    le and the air gap are honoured, the FEA result should track the
    analytic value within a few percent for ungapped cores and ~10%
    for gapped ones (where fringing matters).
    """
    import math

    Ae_m2 = max(core.Ae_mm2 * 1e-6, 1e-12)
    le_m = max(core.le_mm * 1e-3, 1e-9)
    HT_m = max((core.HT_mm or 0.0) * 1e-3, 0.0)
    Wa_m2 = max(core.Wa_mm2 * 1e-6, 0.0)

    # Equivalent round center leg with the same cross-section. PQ/ETD
    # already have a round leg so this is exact; EE/EI/PQ-like get an
    # area-equivalent cylinder.
    core_inner_diameter_m = 2.0 * math.sqrt(Ae_m2 / math.pi)

    # Geometry mapping. FEMMT computes le from the axisymmetric model:
    #     le_femmt ≈ 2*(window_h + window_w) + center_leg_diameter
    # Match it to our datasheet le by solving the quadratic
    #     window_w + window_h = (le_m - core_inner_diameter_m) / 2
    #     window_w * window_h = Wa_m2
    # which gives a sensible aspect ratio without inflating le.
    if Wa_m2 > 0:
        S = (le_m - core_inner_diameter_m) / 2.0
        disc = S * S - 4.0 * Wa_m2
        if S > 0 and disc >= 0:
            sqrt_disc = math.sqrt(disc)
            # Take the smaller root for window_w (typical bobbin: tall+narrow).
            window_w_m = (S - sqrt_disc) / 2.0
            window_h_m = (S + sqrt_disc) / 2.0
            if window_w_m <= 0 or window_h_m <= 0:
                window_w_m = math.sqrt(Wa_m2 / 2.0)
                window_h_m = 2.0 * window_w_m
        else:
            # Wa too large for the requested le — fall back to 1:2 aspect.
            window_w_m = math.sqrt(Wa_m2 / 2.0)
            window_h_m = 2.0 * window_w_m
    else:
        window_w_m = 5e-3
        window_h_m = 1e-2

    # Inflate the window if the requested turns can't physically fit;
    # FEA accuracy of L is dominated by Ae/le, the window only needs
    # to hold the conductor cross-section. The 1.6× safety factor
    # accounts for FEMMT's stricter "ToEdges" packing checker.
    wire_diam_m = (wire.d_iso_mm or wire.d_cu_mm or 1.0) * 1e-3
    insulation_m = 5e-4
    pitch_m = wire_diam_m + insulation_m
    needed_area_m2 = result.N_turns * pitch_m * pitch_m
    real_area = window_w_m * window_h_m
    if real_area > 0:
        inflate = max(1.0, math.sqrt(needed_area_m2 / real_area) * 1.60)
    else:
        inflate = 1.0
    window_w_m *= inflate
    window_h_m *= inflate

    # Also widen the window if it is narrower than a single conductor
    # column — FEMMT places turns in vertical columns of width
    # 2*conductor_radius, so window_w must accommodate at least one.
    min_window_w = pitch_m * 2.5
    if window_w_m < min_window_w:
        scale = min_window_w / window_w_m
        window_w_m *= scale
        window_h_m *= scale

    # Total core height: respect HT when known, else compute from
    # window_h plus typical center-post thickness.
    if HT_m > 0:
        core_h_m = max(HT_m * inflate, window_h_m + core_inner_diameter_m * 0.5)
    else:
        core_h_m = window_h_m + core_inner_diameter_m * 0.6

    # Operating-point small-signal permeability at the worst-case DC bias.
    H_Am = result.N_turns * result.I_line_pk_A / le_m
    H_Oe = H_Am / 79.5774715459
    mu_eff = float(material.mu_initial * mu_pct(material, H_Oe))

    fsw_Hz = max(spec.f_sw_kHz * 1000.0, 1.0)
    cwd = _ensure_dir(output_dir)
    original_cwd = os.getcwd()
    os.chdir(cwd)
    try:
        started = time.monotonic()

        geo = ft.MagneticComponent(
            simulation_type=ft.SimulationType.FreqDomain,
            component_type=ft.ComponentType.Inductor,
            working_directory=str(cwd),
            verbosity=_resolve_verbosity(ft, ("Info", "ToConsole")),
            is_gui=True,
        )

        core_dimensions = ft.dtos.SingleCoreDimensions(
            core_inner_diameter=core_inner_diameter_m,
            window_w=window_w_m,
            window_h=window_h_m,
            core_h=core_h_m,
        )
        core_obj = ft.Core(
            core_type=ft.CoreType.Single,
            core_dimensions=core_dimensions,
            detailed_core_model=False,
            mu_r_abs=mu_eff,
            phi_mu_deg=0.0,
            sigma=0.0,
            permeability_datasource=ft.MaterialDataSource.Custom,
            permittivity_datasource=ft.MaterialDataSource.Custom,
            mdb_verbosity=_resolve_verbosity(ft, ("Silent",)),
        )
        geo.set_core(core_obj)

        # Pick the gap that keeps FEMMT consistent with the catalog
        # AL. Two cases:
        #
        # 1. ``core.lgap_mm`` is explicitly published — use it. The
        #    AL_nH was measured against that real gap, so geometry +
        #    µr + lgap reproduce the same number in FEMMT.
        # 2. ``core.lgap_mm`` is zero (Dongxing EI28 and many other
        #    silicon-steel laminations ship as "no published gap").
        #    A fixed 10 µm here mismatches the catalog AL by 5–30×;
        #    back-solve the equivalent gap from AL_nH instead.
        if core.lgap_mm and core.lgap_mm > 0:
            gap_m = core.lgap_mm * 1e-3
            gap_origin = "catalog lgap_mm"
        else:
            gap_m = _equivalent_air_gap_m(core, material)
            gap_origin = "back-solved from AL_nH"
        gap_m = max(gap_m, _TECH_AIR_GAP_M)
        air_gaps = ft.AirGaps(ft.AirGapMethod.Percent, core_obj)
        air_gaps.add_air_gap(ft.AirGapLegPosition.CenterLeg, gap_m, 50)
        geo.set_air_gaps(air_gaps)

        insulation = ft.Insulation(flag_insulation=True)
        insulation.add_core_insulations(1e-3, 1e-3, 3e-3, 1e-3)
        insulation.add_winding_insulations([[5e-4]])
        geo.set_insulation(insulation)

        winding_window = ft.WindingWindow(core_obj, insulation)
        vww = winding_window.split_window(ft.WindingWindowSplit.NoSplit)

        winding = ft.Conductor(0, ft.Conductivity.Copper, winding_material_temperature=45)
        if wire.type == "litz" and wire.d_strand_mm and wire.n_strands:
            winding.set_litz_round_conductor(
                conductor_radius=(wire.d_bundle_mm or wire.A_cu_mm2**0.5 * 0.6) * 0.5e-3,
                number_strands=wire.n_strands,
                strand_radius=wire.d_strand_mm * 0.5e-3,
                fill_factor=None,
                conductor_arrangement=ft.ConductorArrangement.Square,
            )
        else:
            winding.set_solid_round_conductor(
                conductor_radius=(wire.d_cu_mm or 1.0) * 0.5e-3,
                conductor_arrangement=ft.ConductorArrangement.Square,
            )
        winding.parallel = False

        vww.set_winding(
            winding,
            result.N_turns,
            None,
            ft.Align.ToEdges,
            placing_strategy=ft.ConductorDistribution.HorizontalRightward_VerticalUpward,
            zigzag=True,
        )
        geo.set_winding_windows([winding_window])

        # All "show me a plot" flags OFF — see toroid path above
        # for the full rationale. The headless ``pos_renderer``
        # call after the solve produces every visualisation we
        # actually want (B-field heatmap, 1-D centerline,
        # volumetric histogram, loss density), without ever
        # opening a popup window.
        geo.create_model(
            freq=fsw_Hz,
            pre_visualize_geometry=False,
            save_png=False,
        )
        geo.single_simulation(
            freq=fsw_Hz,
            current=[float(result.I_line_pk_A)],
            plot_interpolation=False,
            show_fem_simulation_results=False,
        )

        log = geo.read_log()

        # Optional thermal pass on the same geo (same rationale
        # + same lenient error handling as the toroid path).
        thermal_log: Optional[dict] = None
        if thermal_options is not None:
            try:
                geo.thermal_simulation(
                    thermal_conductivity_dict=thermal_options["k_dict"],
                    boundary_temperatures_dict=thermal_options["temps"],
                    boundary_flags_dict=thermal_options["flags"],
                    case_gap_top=thermal_options["case_gap_top"],
                    case_gap_right=thermal_options["case_gap_right"],
                    case_gap_bot=thermal_options["case_gap_bot"],
                    show_thermal_simulation_results=False,
                    pre_visualize_geometry=False,
                    flag_insulation=True,
                )
                thermal_log = geo.read_thermal_log()
            except Exception as e:
                logger.exception(
                    "thermal_simulation failed; EM result preserved",
                )
                thermal_log = {"error": f"{type(e).__name__}: {e}"}
    finally:
        os.chdir(original_cwd)

    # Render gmsh ``.pos`` field views as PNG heatmaps (see toroid
    # path above for rationale).
    try:
        from pfc_inductor.fea.pos_renderer import render_field_pngs

        render_field_pngs(cwd)
    except Exception:  # pragma: no cover
        logger.exception("Field-PNG rendering failed; continuing.")

    L_FEA_H = _extract_L_H(log)
    flux_FEA_Wb = _extract_flux(log)
    if abs(flux_FEA_Wb) > 0 and result.N_turns > 0 and Ae_m2 > 0:
        B_FEA_T = abs(flux_FEA_Wb) / (result.N_turns * Ae_m2)
    else:
        B_FEA_T = 0.0
    elapsed = time.monotonic() - started

    L_an_uH = float(result.L_actual_uH)
    L_FEA_uH = L_FEA_H * 1e6
    B_an = float(result.B_pk_T)

    notes_geom = (
        f"FEMMT CoreType.Single mapeado para shape {kind.upper()}: "
        f"d_centro={core_inner_diameter_m * 1e3:.2f} mm "
        f"(eq. round leg), janela {window_w_m * 1e3:.1f}×{window_h_m * 1e3:.1f} mm "
        f"(inflate {inflate:.2f}×). gap={gap_m * 1e3:.3f} mm "
        f"({gap_origin}). μ_eff(H={H_Oe:.0f} Oe)={mu_eff:.0f}."
    )

    fea = FEAValidation(
        L_FEA_uH=L_FEA_uH,
        L_analytic_uH=L_an_uH,
        L_pct_error=_pct(L_an_uH, L_FEA_uH),
        B_pk_FEA_T=B_FEA_T,
        B_pk_analytic_T=B_an,
        B_pct_error=_pct(B_an, B_FEA_T),
        flux_linkage_FEA_Wb=L_FEA_H * float(result.I_line_pk_A),
        test_current_A=float(result.I_line_pk_A),
        solve_time_s=elapsed,
        femm_binary="FEMMT (ONELAB) " + (getattr(ft, "__version__", "") or "0.5.x"),
        fem_path=str(cwd),
        log_excerpt="(FEMMT log keys: " + ", ".join(sorted(map(str, log.keys())))[:300] + ")",
        notes=(
            notes_geom + " "
            "Eddy/AC losses not modelled (single magnetostatic). "
            "For EE/ETD/PQ the geometric equivalence is exact in PQ/ETD "
            "(round centre leg) and approximate in EE (area-equivalent)."
        ),
    )
    return (fea, thermal_log) if thermal_options is not None else fea


def _femmt_integrity_check(femmt_module) -> dict:
    """Verify the FEMMT install is complete enough to drive a
    validation run.

    PEP 420 namespace packages let ``import femmt`` succeed even
    when ``__init__.py`` is missing (or corrupted), so the deeper
    failure is a generic ``AttributeError: module 'femmt' has no
    attribute 'MagneticComponent'`` 4+ frames into the runner. We
    catch that up-front by checking for the top-level exports the
    runner actually uses:

    - ``MagneticComponent`` — the entry-point class.
    - ``CoreType``, ``ComponentType``, ``Verbosity`` — enums the
      runner constructs.
    - ``dtos`` — submodule that holds ``SingleCoreDimensions``.

    Returns ``{ok: bool, missing: list[str], message: str}``.
    """
    required = (
        "MagneticComponent",
        "CoreType",
        "ComponentType",
        "Verbosity",
        "Conductor",
        "Insulation",
        "WindingWindow",
        "AirGaps",
        "dtos",
    )
    missing = [name for name in required if not hasattr(femmt_module, name)]
    out: dict = {"ok": not missing, "missing": missing, "message": ""}
    if missing:
        install_dir = _femmt_install_dir(femmt_module)
        loc = f" at {install_dir}" if install_dir is not None else ""
        # Probable cause: namespace package (no __init__.py present).
        # Spell that out so the user knows what to look for if a
        # straight reinstall doesn't fix it.
        ns_hint = (
            " (Python is treating `femmt` as a namespace package — "
            "the install probably lost its `__init__.py`)"
            if getattr(femmt_module, "__file__", None) is None
            else ""
        )
        out["message"] = (
            f"FEMMT module{loc} is missing required top-level "
            f"attributes: {', '.join(missing)}{ns_hint}."
        )
    return out


def _femmt_install_dir(femmt_module) -> Optional[Path]:
    """Resolve FEMMT's install directory in a way that survives the
    quirks we've seen in the wild.

    Three fallback paths, tried in order:

    1. ``femmt.__file__`` — the regular case for a normal install.
    2. ``femmt.__path__[0]`` — works for namespace packages and for
       installs where ``__init__.py`` doesn't set ``__file__`` (we
       hit this with at least one editable / wheel-install combo).
    3. ``importlib.util.find_spec(...).submodule_search_locations``
       — last-resort lookup that consults ``sys.path`` directly.

    Returns ``None`` only when all three resolve to nothing —
    extremely unusual; means FEMMT imported successfully but Python
    can't tell where from.
    """
    file_attr = getattr(femmt_module, "__file__", None)
    if file_attr:
        try:
            return Path(file_attr).parent
        except (TypeError, ValueError):
            pass
    path_attr = getattr(femmt_module, "__path__", None)
    if path_attr:
        try:
            entries = list(path_attr)
            if entries:
                return Path(entries[0])
        except (TypeError, ValueError):
            pass
    try:
        import importlib.util

        spec = importlib.util.find_spec(femmt_module.__name__)
        if spec and spec.submodule_search_locations:
            for loc in spec.submodule_search_locations:
                if loc:
                    return Path(loc)
    except Exception:
        pass
    return None


def _femmt_onelab_configured() -> bool:
    """``True`` only when the FEMMT config points at a complete ONELAB
    install — ``onelab.py`` *plus* the ``gmsh`` and ``getdp`` solvers.

    FEMMT internally calls ``shutil.which`` and several ``Path(...)``
    constructions on the resolved binaries; if either is missing the
    failure surfaces as a generic ``TypeError: argument should be a
    str or an os.PathLike object … not 'NoneType'`` deep inside the
    library. Failing the precheck here lets ``validate_design_femmt``
    raise a self-explanatory ``FEMMSolveError`` instead.
    """
    diag = _femmt_onelab_diagnostics()
    return diag["ok"]


def _femmt_onelab_diagnostics() -> dict:
    """Diagnose the FEMMT/ONELAB install. Returns a dict with:

    - ``ok``: True when every required asset is present.
    - ``onelab_dir``: the configured folder path (``None`` if unset).
    - ``missing``: list of asset names that aren't present
      (``"onelab.py"``, ``"gmsh"``, ``"getdp"``).
    - ``message``: short diagnostic string suitable for an error
      hint (empty when ``ok``).

    The check looks for executables under several common names — the
    Linux/macOS install ships them as ``gmsh`` / ``getdp``; some
    Windows builds ship ``.exe`` variants — so a Windows engineer
    with a working install isn't tripped up by a hard-coded suffix.
    """
    out = {
        "ok": False,
        "onelab_dir": None,
        "missing": [],
        "message": "",
    }
    try:
        import femmt

        femmt_dir = _femmt_install_dir(femmt)
        if femmt_dir is None:
            out["message"] = (
                "Could not locate the FEMMT install directory: "
                "`femmt.__file__` and `femmt.__path__` are both "
                "unavailable. Reinstall FEMMT with "
                '`uv pip install --reinstall -e ".[fea]"` and retry.'
            )
            return out
        config_path = femmt_dir / "config.json"
        if not config_path.exists():
            out["message"] = (
                f"FEMMT config.json not found at {config_path}. "
                "Run `magnadesign-setup fea` to bootstrap it."
            )
            return out
        import json

        data = json.loads(config_path.read_text())
        onelab = data.get("onelab")
        if not onelab:
            out["message"] = (
                f"FEMMT {config_path} has no `onelab` key. "
                "Edit it to point at your ONELAB install folder."
            )
            return out
        out["onelab_dir"] = str(onelab)
        # Group "gmsh" and "gmsh.exe" so we mark the asset missing
        # only when *neither* variant is present. ``onelab.py`` is
        # the cross-platform Python entry point and is always
        # required; ``gmsh`` / ``getdp`` ship as platform-specific
        # binaries (``.exe`` on Windows, no extension on macOS / Linux).
        groups = [("onelab.py",), ("gmsh", "gmsh.exe"), ("getdp", "getdp.exe")]
        missing: list[str] = []
        onelab_path = Path(onelab)
        for group in groups:
            if not any((onelab_path / name).exists() for name in group):
                # Report the canonical name (first variant) as missing.
                missing.append(group[0])
        out["missing"] = missing
        if missing:
            out["message"] = (
                f"ONELAB folder {onelab_path} is missing: "
                f"{', '.join(missing)}. The folder must contain "
                "`onelab.py`, `getdp` (or `getdp.exe`), and "
                "`gmsh` (or `gmsh.exe`)."
            )
            return out
        out["ok"] = True
    except Exception as e:
        out["message"] = f"FEMMT config probe failed: {type(e).__name__}: {e}"
    return out


def _ensure_dir(p: Optional[Path]) -> Path:
    if p is None:
        return Path(tempfile.mkdtemp(prefix="pfc_femmt_"))
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _scalar(v) -> float:
    """Reduce FEMMT log values to a real scalar.

    FEMMT stores complex quantities sometimes as ``[re, im]`` lists or as
    ``{"real": ..., "imag": ...}`` dicts. Reduce to magnitude / real.
    """
    if isinstance(v, (list, tuple)):
        if not v:
            return 0.0
        first = v[0]
        if isinstance(first, (list, tuple)) and len(first) == 2:
            re, im = first
            return float((float(re) ** 2 + float(im) ** 2) ** 0.5)
        return _scalar(first)
    if isinstance(v, dict):
        if "real" in v:
            return float(v["real"])
        if "magnitude" in v:
            return float(v["magnitude"])
    return float(v)


def _extract_L_H(log: dict) -> float:
    """FEMMT 0.5.x stores self-inductance under
    ``single_sweeps[0].winding1.flux_over_current`` (H).
    """
    try:
        sweep0 = log["single_sweeps"][0]
        w1 = sweep0.get("winding1") or sweep0.get("winding_1") or {}
        for k in ("flux_over_current", "self_inductance", "L", "inductance"):
            if k in w1:
                return _scalar(w1[k])
        # Fallback: divide flux by current.
        if "flux" in w1 and "I" in w1:
            f = _scalar(w1["flux"])
            i = _scalar(w1["I"])
            if abs(i) > 1e-12:
                return f / i
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    raise FEMMSolveError("Could not extract L from the FEMMT log.")


def _extract_flux(log: dict) -> float:
    """Pull flux linkage λ (Wb·turns) from the FEMMT log."""
    try:
        sweep0 = log["single_sweeps"][0]
        w1 = sweep0.get("winding1") or sweep0.get("winding_1") or {}
        if "flux" in w1:
            return _scalar(w1["flux"])
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return 0.0


def _pct(reference: float, value: float) -> float:
    if abs(reference) < 1e-12:
        return 0.0
    return (value - reference) / reference * 100.0
