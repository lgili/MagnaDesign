"""``MfgSpec`` — the package the writers consume.

Bundles every piece a vendor needs into one dataclass so the
PDF and Excel writers see identical inputs:

- Project metadata (name, designer, revision, date).
- Selection (material, core, wire) — verbatim from the project.
- Engine result (the nominal numbers).
- Winding plan (per-layer breakdown).
- Insulation class (thermal class + tape stack-up).
- Hi-pot voltage (per IEC 61558).
- Acceptance test plan rows.

Build the pack with :func:`build_mfg_spec`; pass the result to
:func:`write_mfg_spec_pdf` (lazy import) or
:func:`write_mfg_spec_xlsx` (lazy import). Each writer is
self-contained so the heavy ``reportlab`` / ``openpyxl``
imports stay out of the import path of consumers that only need
the engineering payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from pfc_inductor.manufacturing.acceptance import (
    AcceptanceTest,
    build_acceptance_tests,
)
from pfc_inductor.manufacturing.insulation_stack import (
    InsulationClass,
    hipot_voltage_V,
    pick_insulation_class,
)
from pfc_inductor.manufacturing.winding_layout import (
    WindingPlan,
    plan_winding,
)
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


@dataclass(frozen=True)
class MfgSpec:
    """The vendor-quotable manufacturing specification."""

    project_name: str
    designer: str
    revision: str
    date_iso: str

    spec: Spec
    core: Core
    wire: Wire
    material: Material
    result: DesignResult

    winding: WindingPlan
    insulation: InsulationClass
    hipot_V: float
    acceptance_tests: tuple[AcceptanceTest, ...]

    notes: tuple[str, ...] = field(default_factory=tuple)


def build_mfg_spec(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    project_name: str = "—",
    designer: str = "—",
    revision: str = "A.0",
    notes: Optional[tuple[str, ...]] = None,
) -> MfgSpec:
    """Bundle every input into one :class:`MfgSpec`.

    Pure function — does no IO and doesn't import the writers.
    The caller picks PDF, XLSX, or both with a one-liner each.
    """
    winding = plan_winding(core=core, wire=wire, n_turns=int(result.N_turns))

    insulation = pick_insulation_class(T_winding_C=result.T_winding_C)

    work_v = _working_voltage_V(spec)
    hipot = hipot_voltage_V(work_v)

    atp = build_acceptance_tests(
        spec=spec,
        core=core,
        wire=wire,
        material=material,
        result=result,
    )

    aggregated_notes: tuple[str, ...] = (notes or ()) + winding.warnings

    return MfgSpec(
        project_name=project_name,
        designer=designer,
        revision=revision,
        date_iso=datetime.now(UTC).date().isoformat(),
        spec=spec,
        core=core,
        wire=wire,
        material=material,
        result=result,
        winding=winding,
        insulation=insulation,
        hipot_V=hipot,
        acceptance_tests=tuple(atp),
        notes=aggregated_notes,
    )


def _working_voltage_V(spec: Spec) -> float:
    topology = (spec.topology or "").lower()
    if topology == "buck_ccm":
        return float(
            getattr(spec, "Vin_dc_V", None)
            or getattr(spec, "Vin_dc_max_V", None)
            or getattr(spec, "Vin_nom_Vrms", None)
            or 0.0
        )
    vmax = float(getattr(spec, "Vin_max_Vrms", None) or 0.0)
    if vmax > 0:
        return vmax * (2**0.5)
    return float(getattr(spec, "Vin_nom_Vrms", None) or 0.0) * (2**0.5)
