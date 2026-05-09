"""Coupled magnetostatic + thermal FEA via FEMMT.

The headline magnetostatic validation in :mod:`femmt_runner` returns
``L`` and ``B_pk`` numbers. This module adds the **thermal** pass
that runs immediately after, reading the ohmic + core-loss density
fields the magnetostatic step wrote and propagating them through
the inductor's material stack to a steady-state temperature
distribution.

Why a separate module:

    The magnetostatic + thermal sequence requires extra inputs
    the cold call doesn't need (thermal conductivities per region,
    case geometry, boundary temperatures). Bundling them in
    :class:`ThermalOptions` keeps the cheap magnetostatic-only
    path uncluttered while exposing a typed surface the UI
    + CLI can drive.

What the user gets:

    A :class:`ThermalResult` carrying peak / average / per-
    region temperatures plus the path to the gmsh
    ``temperature.pos`` field which the :mod:`pos_renderer`
    headless post-processor turns into a coloured heatmap PNG
    the FEA gallery picks up automatically.

The thermal solve adds roughly 10–25 s on top of the
magnetostatic pass on typical PFC inductors (PQ40 / 30 mm
toroid). It re-uses the same gmsh subprocess, so the cost is
purely the additional finite-element solve.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pfc_inductor.fea.models import FEMMNotAvailable, FEMMSolveError
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Material-keyed thermal conductivities.
# ---------------------------------------------------------------------------
# k [W/(m·K)] — typical engineering values. Sources:
#   ferrite        — TDK / EPCOS / Ferroxcube datasheets, 4–6 W/m·K
#   silicon-steel  — M19 / M27 / 3.5% Si laminations, 22–30 W/m·K
#   powder cores   — Magnetics Kool-Mu / High-Flux, 18–25 W/m·K
#   nanocrystalline— Vitroperm 500 F class, 8–12 W/m·K
#   amorphous      — Metglas 2605SA1 / 2705M, 11–13 W/m·K
#
# We pick mid-range defaults so the heatmap is representative;
# users that need ±5 % accuracy override the dict before solving.
_MATERIAL_K_W_M_K: dict[str, float] = {
    "ferrite":          5.0,
    "silicon-steel":   25.0,
    "powder":          20.0,
    "nanocrystalline": 10.0,
    "amorphous":       12.0,
}

# Universal physical constants — every solve uses these.
_K_AIR = 0.026         # still air at 40 °C
_K_COPPER = 400.0      # pure Cu at 25 °C
_K_INSULATION = 0.42   # typical polyethylene wire insulation
_K_AIR_GAP = 180.0     # FEMMT example uses AlN-style high-k for
                       # the air gap region — represents an
                       # epoxy-potted gap, not loose air. Realistic
                       # for production PFC inductors.

# Default case (potting / housing) thermal conductivity. Epoxy
# encapsulant — typical value across vendors. The 1.54 W/m·K
# sample from the FEMMT example matches this.
_K_CASE = 1.54


@dataclass
class ThermalOptions:
    """Inputs for the thermal solve. All fields have sensible
    defaults so the caller only overrides what they care about.
    """

    T_ambient_C: float = 40.0
    """Boundary temperature applied as a Dirichlet condition on
    every active boundary side. Defaults to the project's
    typical ambient (40 °C, ~1 m above floor in a cabinet)."""

    case_gap_top_m: float = 0.002
    case_gap_right_m: float = 0.0025
    case_gap_bot_m: float = 0.002
    """Distance from the core to the modelled case boundary in
    metres. Setting these too small clips the thermal volume and
    inflates the peak temperature; too large adds solve time
    without changing the answer. 2–3 mm matches typical
    enclosed-PFC mechanical practice."""

    k_overrides_W_m_K: dict[str, float] = field(default_factory=dict)
    """Optional overrides for the conductivity-by-key dict
    (``"core"``, ``"winding"``, ``"insulation"``, ``"case"``,
    ``"air"``, ``"air_gaps"``). Empty by default — the runner
    fills sensible values from the material type."""

    boundary_active: dict[str, bool] = field(default_factory=dict)
    """Per-side boundary on/off map. Empty defaults to "all
    active" (Dirichlet at ``T_ambient_C`` on every side except
    the symmetry top, which is Neumann zero-flux)."""


@dataclass(frozen=True)
class ThermalResult:
    """Outcome of a thermal solve."""

    T_peak_C: float
    """Maximum temperature reached anywhere in the model."""
    T_winding_avg_C: float
    """Average temperature in the winding region — the number
    that compares directly against the analytical ΔT estimate."""
    T_core_avg_C: float
    """Average temperature in the core region."""
    T_ambient_C: float
    """Boundary temperature used in the solve (echoed back so
    the caller can compute ΔT_winding without re-passing it)."""
    rise_winding_C: float
    """Convenience: ``T_winding_avg_C - T_ambient_C``."""
    rise_core_C: float
    """Convenience: ``T_core_avg_C - T_ambient_C``."""
    fem_path: str
    """Working directory where ``temperature.pos`` lives."""
    solve_time_s: float
    notes: str = ""

    @property
    def passed_thermal_budget(self) -> bool:
        r"""Crude pass/fail vs.\ a 105 °C winding ceiling — typical
        for class B insulation / standard magnet-wire enamel."""
        return self.T_winding_avg_C < 105.0


def _resolve_k_dict(
    material: Material, options: ThermalOptions
) -> dict:
    """Build the thermal_conductivity_dict in the exact shape
    FEMMT expects."""
    # Map the material's ``type`` string to a default core k.
    mat_type = (getattr(material, "type", "") or "").lower()
    k_core = _MATERIAL_K_W_M_K.get(mat_type, 5.0)
    k = {
        "air": _K_AIR,
        "case": {
            "top": _K_CASE,
            "top_right": _K_CASE,
            "right": _K_CASE,
            "bot_right": _K_CASE,
            "bot": _K_CASE,
        },
        "core": k_core,
        "winding": _K_COPPER,
        "air_gaps": _K_AIR_GAP,
        "insulation": _K_INSULATION,
    }
    # Apply user overrides.
    for key, value in options.k_overrides_W_m_K.items():
        k[key] = value  # type: ignore[assignment]
    return k


def _resolve_boundaries(
    options: ThermalOptions,
) -> tuple[dict, dict]:
    """Build the boundary-temperature + boundary-flag dicts."""
    sides = (
        "top", "top_right", "right_top", "right",
        "right_bottom", "bottom_right", "bottom",
    )
    temps = {f"value_boundary_{s}": float(options.T_ambient_C) for s in sides}
    # Active flags. Top and top-right are typically convection-
    # bound to ambient (potting cap); the right and bottom sides
    # are the heat-rejection path (heatsink / chassis); the
    # symmetry side stays Neumann (flag=0). Defaulting matches
    # the FEMMT example's "all sides except top" pattern.
    default_flags = {
        "flag_boundary_top": 0,
        "flag_boundary_top_right": 0,
        "flag_boundary_right_top": 1,
        "flag_boundary_right": 1,
        "flag_boundary_right_bottom": 1,
        "flag_boundary_bottom_right": 1,
        "flag_boundary_bottom": 1,
    }
    if options.boundary_active:
        for k, v in options.boundary_active.items():
            default_flags[f"flag_boundary_{k}"] = 1 if v else 0
    return temps, default_flags


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def validate_design_thermal_femmt(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    output_dir: Optional[Path] = None,
    options: Optional[ThermalOptions] = None,
    timeout_s: int = 360,
) -> ThermalResult:
    """Magnetostatic + thermal coupled solve.

    Both passes run in a **single subprocess** on the same
    ``MagneticComponent`` instance — FEMMT's thermal solver
    depends on the EM step's in-memory state, so a "EM in
    subprocess A, thermal in subprocess B" architecture won't
    work. Marshals the thermal options as a plain pickle-safe
    dict, hands it to ``_run_validation_in_subprocess``, and
    receives a ``(FEAValidation, dict)`` tuple.

    The ``temperature.pos`` field that FEMMT writes lands in
    the same ``e_m/results/fields`` folder as the magnetostatic
    ``.pos`` outputs and is rendered as a heatmap PNG by the
    existing :func:`pos_renderer.render_field_pngs` post-pass.

    Raises :class:`FEMMNotAvailable` / :class:`FEMMSolveError`
    on the same conditions the magnetostatic path raises.
    """
    import time

    options = options or ThermalOptions()
    started = time.monotonic()

    from pfc_inductor.fea.femmt_runner import _run_validation_in_subprocess

    # Marshal the thermal options as a flat pickle-safe dict.
    # Booleans + floats only — no FEMMT enum / dataclass refs.
    thermal_payload = {
        "k_dict": _resolve_k_dict(material, options),
        "temps": _resolve_boundaries(options)[0],
        "flags": _resolve_boundaries(options)[1],
        "case_gap_top": float(options.case_gap_top_m),
        "case_gap_right": float(options.case_gap_right_m),
        "case_gap_bot": float(options.case_gap_bot_m),
    }

    payload = _run_validation_in_subprocess(
        spec, core, wire, material, result,
        output_dir=output_dir, timeout_s=timeout_s,
        thermal_options=thermal_payload,
    )
    if not isinstance(payload, tuple) or len(payload) != 2:
        raise FEMMSolveError(
            "Thermal subprocess returned an unexpected payload "
            f"shape: {type(payload).__name__}"
        )
    em, thermal_log = payload
    elapsed = time.monotonic() - started

    # Re-render the .pos files so the new ``temperature.pos``
    # gets a heatmap PNG; the gallery will pick it up. Always
    # runs, even on a thermal failure, because the EM step
    # already wrote magnetostatic field PNGs (or the synthetic
    # fallback did).
    try:
        from pfc_inductor.fea.pos_renderer import render_field_pngs

        render_field_pngs(Path(em.fem_path))
    except Exception:
        logger.exception("Field-PNG re-render after thermal failed.")

    # Two paths from here:
    #
    # 1. ``thermal_log`` is a real FEMMT ``results_thermal.json``
    #    dict — read peak / averages and return a normal result.
    # 2. ``thermal_log`` carries a ``{"error": ...}`` payload
    #    because ``geo.thermal_simulation`` raised inside the
    #    subprocess (mesh / boundary condition / case-gap
    #    issue). We *do not* raise — the EM result is still
    #    valid + the gallery still has its magnetostatic PNGs;
    #    we just surface the failure in the ThermalResult's
    #    ``notes`` so the dialog can show a meaningful message
    #    instead of a hard-stop error popup.
    if thermal_log is None or "error" in (thermal_log or {}):
        err = (thermal_log or {}).get(
            "error", "thermal solver returned no log"
        )
        return ThermalResult(
            T_peak_C=0.0,
            T_winding_avg_C=0.0,
            T_core_avg_C=0.0,
            T_ambient_C=options.T_ambient_C,
            rise_winding_C=0.0,
            rise_core_C=0.0,
            fem_path=str(em.fem_path),
            solve_time_s=elapsed,
            notes=(
                "Thermal solve failed: " + err + ". The "
                "magnetostatic L / B numbers and the field-plot "
                "gallery are still valid; only the temperature "
                "fields are missing."
            ),
        )

    # Extract scalars from FEMMT's ``results_thermal.json``.
    # Real schema (verified against femmt 0.5.x's
    # ``thermal_simulation.run_thermal``): the JSON has
    # ``core_parts`` and ``windings`` top-level keys, each a
    # dict of region-name → ``{min, max, mean}`` plus a
    # synthetic ``"total"`` aggregate the solver appends. The
    # earlier path ``temperatures.{max,winding_average,
    # core_average}`` produced 0.0 across the board because
    # those keys don't exist in the file FEMMT actually writes.
    T_w_avg = float(_dig(thermal_log, ["windings", "total", "mean"],
                          default=0.0))
    T_c_avg = float(_dig(thermal_log, ["core_parts", "total", "mean"],
                          default=0.0))
    T_w_max = float(_dig(thermal_log, ["windings", "total", "max"],
                          default=0.0))
    T_c_max = float(_dig(thermal_log, ["core_parts", "total", "max"],
                          default=0.0))
    T_peak = max(T_w_max, T_c_max)

    return ThermalResult(
        T_peak_C=T_peak,
        T_winding_avg_C=T_w_avg,
        T_core_avg_C=T_c_avg,
        T_ambient_C=options.T_ambient_C,
        rise_winding_C=max(T_w_avg - options.T_ambient_C, 0.0),
        rise_core_C=max(T_c_avg - options.T_ambient_C, 0.0),
        fem_path=str(em.fem_path),
        solve_time_s=elapsed,
        notes=(
            "Steady-state thermal solve from the magnetostatic loss "
            "file (single-subprocess architecture). Use "
            "ThermalOptions to override material k or boundary "
            "temperatures."
        ),
    )


def _dig(d: dict, path: list[str], default=None):
    """Defensive dotted-key lookup."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is default:
            return default
    return cur if cur is not None else default
