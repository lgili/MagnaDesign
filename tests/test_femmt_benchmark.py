"""FEMMT side-by-side benchmark — Phase 2.0 of the FEA replacement.

Loads ``tests/benchmarks/cores.yaml`` and runs both backends
(direct + FEMMT) on each curated case. Asserts that the direct
backend lands within the per-case tolerance of FEMMT.

These tests are **slow** (3–10 s of FEMMT solve time per case
plus a few seconds for our direct backend). They're marked
``@pytest.mark.slow`` and only run in CI when explicitly
requested with ``-m slow`` or on the weekly cron schedule.

The tolerances in cores.yaml are intentionally loose at Phase
2.0 start (50–80 % on L_dc) — they encode the current
calibration envelope. Each later Phase tightens them as the
formulation matures. By Phase 5.1 every case is at ≤ 5 %.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_DEFAULTS = {
    "wire_id": "AWG18",
    "tolerance": {"L_dc_pct": 50, "B_pk_pct": 30},
}


def _load_benchmark_cases() -> list[dict[str, Any]]:
    """Read the cores.yaml file and produce a list of test inputs."""
    path = Path(__file__).parent / "benchmarks" / "cores.yaml"
    with path.open() as fh:
        data = yaml.safe_load(fh)
    cases: list[dict[str, Any]] = []
    for raw in data.get("benchmarks", []):
        case = dict(_DEFAULTS)
        case.update(raw)
        if "tolerance" in raw:
            tol = dict(_DEFAULTS["tolerance"])
            tol.update(raw["tolerance"])
            case["tolerance"] = tol
        cases.append(case)
    return cases


@pytest.fixture(scope="module")
def catalogs():
    """Load all three catalogs once for the whole benchmark run.

    Each is ~10 ms; doing it per-test would add 30 ms × N tests
    overhead and isn't necessary — the catalogs are immutable
    during a CI run.
    """
    from pfc_inductor.data_loader import load_cores, load_materials, load_wires

    return {
        "materials": load_materials(),
        "cores": load_cores(),
        "wires": load_wires(),
    }


@pytest.mark.slow
@pytest.mark.parametrize("case", _load_benchmark_cases(), ids=lambda c: c["id"])
def test_direct_vs_femmt_inductance(case: dict[str, Any], catalogs: dict[str, list]) -> None:
    """Assert direct backend lands within tolerance of FEMMT on L_dc.

    Phase 2.0 acceptance: the test framework runs end-to-end and
    each case has a recorded FEMMT number to compare against. The
    tolerance gates encode the current envelope (loose at 50–80 %).
    Phase 2.1+ tightens them.

    A failure here either means the direct backend regressed OR
    FEMMT itself produced a different number on the same input
    (e.g. ONELAB version drift, MaterialDataSource enum change).
    Either case requires investigation — never silently widen the
    tolerance to make the test pass.
    """
    from pfc_inductor.design import design
    from pfc_inductor.fea.direct.calibration import compare_backends
    from pfc_inductor.models import Spec

    materials = catalogs["materials"]
    cores = catalogs["cores"]
    wires = catalogs["wires"]

    core = next(c for c in cores if c.id == case["core_id"])
    material_id = case.get("material_id") or core.default_material_id
    material = next(m for m in materials if m.id == material_id)
    wire_id = case["wire_id"]
    wire = next(w for w in wires if wire_id in w.id)

    spec = Spec(**case["spec"])
    result = design(spec, core, wire, material)

    with tempfile.TemporaryDirectory() as td:
        report = compare_backends(
            core=core,
            material=material,
            wire=wire,
            n_turns=result.N_turns,
            current_A=float(result.I_line_pk_A),
            spec=spec,
            design_result=result,
            workdir_root=Path(td),
            include_femmt=True,
            include_direct=True,
            include_analytical=False,
        )

    femmt = report.femmt
    direct = report.direct
    assert femmt is not None, "FEMMT outcome missing"
    assert direct is not None, "Direct outcome missing"

    # Print full report for easy human inspection when the test runs.
    # pytest captures stdout but shows it on failure.
    print(f"\n[{case['id']}]\n{report}")

    if femmt.error:
        pytest.skip(f"FEMMT unavailable for this case: {femmt.error}")
    if direct.error:
        pytest.fail(f"Direct backend failed on {case['id']}: {direct.error}")

    assert femmt.L_dc_uH is not None, f"FEMMT didn't return L_dc on {case['id']}"
    assert direct.L_dc_uH is not None, f"Direct didn't return L_dc on {case['id']}"

    L_tol_pct = float(case["tolerance"]["L_dc_pct"])
    diff_pct = abs(direct.L_dc_uH - femmt.L_dc_uH) / femmt.L_dc_uH * 100.0
    assert diff_pct <= L_tol_pct, (
        f"[{case['id']}] L_dc out of tolerance: "
        f"direct={direct.L_dc_uH:.1f} μH vs femmt={femmt.L_dc_uH:.1f} μH "
        f"(|Δ|={diff_pct:.1f} % > {L_tol_pct:.0f} %)"
    )

    if direct.B_pk_T is not None and femmt.B_pk_T is not None and femmt.B_pk_T > 0:
        B_tol_pct = float(case["tolerance"]["B_pk_pct"])
        Bdiff_pct = abs(direct.B_pk_T - femmt.B_pk_T) / femmt.B_pk_T * 100.0
        assert Bdiff_pct <= B_tol_pct, (
            f"[{case['id']}] B_pk out of tolerance: "
            f"direct={direct.B_pk_T:.3f} T vs femmt={femmt.B_pk_T:.3f} T "
            f"(|Δ|={Bdiff_pct:.1f} % > {B_tol_pct:.0f} %)"
        )


def test_benchmark_yaml_loads():
    """Sanity: benchmark file exists, parses, has at least one case
    with all required fields.
    """
    cases = _load_benchmark_cases()
    assert len(cases) >= 1, "No benchmark cases defined"
    for case in cases:
        assert "id" in case
        assert "core_id" in case
        assert "spec" in case
        assert "tolerance" in case
        assert "L_dc_pct" in case["tolerance"]
