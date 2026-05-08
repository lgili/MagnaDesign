"""Manufacturing-spec export — vendor-quotable PDF + Excel.

This module turns the engine's nominal output into the artefacts
a magnetics-vendor (Pulse, Würth, TDK-EPC, custom-wind shops)
needs to **quote and produce** the part. The customer-facing
datasheet (``report/pdf_report.py``) answers a different
question: it describes the design's electrical behaviour for the
engineer who specified it. Without the manufacturing spec, every
prototype hand-off blocks the supplier-RFQ workflow on a one-off
Word document.

Public API
----------

- :func:`plan_winding` → :class:`WindingPlan`
  (turns / layer × layers, fill factor, layer warnings).
- :func:`pick_insulation_class` → ``"B"`` / ``"F"`` / ``"H"``
  (per IEC 60085).
- :func:`build_acceptance_tests` → ``list[AcceptanceTest]`` —
  one row per row of the FAT plan.
- :func:`write_mfg_spec_pdf` (lazy import) — ReportLab PDF.
- :func:`write_mfg_spec_xlsx` (lazy import) — openpyxl XLSX.

The top-level entry point :func:`build_mfg_spec` packages the
above and returns a :class:`MfgSpec` dataclass; both writers
consume that single payload so a CLI invocation is a one-liner
chain.
"""
from __future__ import annotations

from pfc_inductor.manufacturing.acceptance import (
    AcceptanceTest,
    build_acceptance_tests,
)
from pfc_inductor.manufacturing.insulation_stack import (
    InsulationClass,
    INSULATION_CLASSES,
    hipot_voltage_V,
    pick_insulation_class,
)
from pfc_inductor.manufacturing.spec import MfgSpec, build_mfg_spec
from pfc_inductor.manufacturing.winding_layout import (
    LayerPlan,
    WindingPlan,
    plan_winding,
)

__all__ = [
    "AcceptanceTest",
    "build_acceptance_tests",
    "build_mfg_spec",
    "INSULATION_CLASSES",
    "hipot_voltage_V",
    "InsulationClass",
    "LayerPlan",
    "MfgSpec",
    "pick_insulation_class",
    "plan_winding",
    "WindingPlan",
]
