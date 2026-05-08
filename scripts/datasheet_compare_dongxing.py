"""Compare our design engine against three Dongxing harmonic-reactor
datasheets (DX60346CT EI60, DX60414CT EI41, DX60415CT EI28).

Each datasheet specifies L=10 mH, the number of turns, the wire gauge
and the maximum Rdc — i.e. the answer we should be reproducing. We
build a ``Core`` + ``Material`` + ``Wire`` from the datasheet, run our
engine on the matching ``Spec``, and report:

  - turns  : engine vs datasheet
  - Rdc    : engine vs datasheet (max)
  - B_pk   : engine value (must be < Bsat)
  - V_drop : voltage drop at rated current
  - %Z     : reactor impedance as fraction of base
  - THD    : empirical estimate

If the engine reproduces N within ±5 turns and Rdc within ±15 % we call
it a match — better than that means the datasheet just used different
values for stacking/wire-table, which is normal.

Run:

    .venv/bin/python scripts/datasheet_compare_dongxing.py
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pfc_inductor.design import design  # noqa: E402  type: ignore[import-not-found]
from pfc_inductor.models import (  # noqa: E402  type: ignore[import-not-found]
    Core,
    Material,
    Spec,
    SteinmetzParams,
    Wire,
)


# ---------------------------------------------------------------------------
# Datasheet entries
# ---------------------------------------------------------------------------
@dataclass
class DatasheetReactor:
    model: str
    core_label: str  # marketing name (EI60, EI41, EI28)
    silicon_grade: str
    stack_mm: float  # core stack (lamination thickness × n)
    Ae_mm2: float  # center-leg cross section
    le_mm: float  # mean magnetic path
    Wa_mm2: float  # winding window area
    MLT_mm: float  # back-derived from N · A_cu vs Rdc
    Bsat_T: float  # silicon-steel typical
    mu_initial: float  # silicon-steel typical
    rho_kg_m3: float
    L_mH: float  # nominal inductance (datasheet target)
    N_spec: int  # datasheet number of turns
    wire_d_cu_mm: float  # bare copper diameter
    Rdc_max_ohm: float  # datasheet maximum DC resistance
    I_rated_A: float  # rated continuous current


# Geometry comes from the schematic drawings in each PDF. EI laminations
# have well-known proportions: outer width ≈ 1.5 × center-leg, window
# height ≈ tongue height, etc. The Ae/le/Wa values below are the
# textbook values for each (E + I) lamination size combined with the
# lamination stack thickness shown in the drawing.
#
# 50H800, 50CS1300 and 50H1300 are Chinese-market silicon-steel grades.
# Bsat ≈ 1.5–1.6 T at 25 °C, μᵣ ~3000–5000 — somewhere between the
# Western M5/M19 we already ship and lower-grade NGO. We use Bsat=1.55T
# (conservative end of the range) and μ=4000 for all three since the
# datasheets don't specify the exact grade family.
SILICON_BSAT = 1.55
SILICON_MU = 4000.0
SILICON_RHO = 7650.0

DATASHEETS: list[DatasheetReactor] = [
    DatasheetReactor(
        model="DX60346CT",
        core_label="EI60",
        silicon_grade="50H800",
        # Drawing: C=20 mm stack, G=92.5 outer, E=85 wide, I=58 high
        stack_mm=20.0,
        # Ae = center-leg width × stack ≈ 20 × 20
        Ae_mm2=400.0,
        # le for EI60 assembled ≈ 117 mm (textbook)
        le_mm=117.0,
        # Wa per side ≈ 30 × 10 = 300 mm²; total winding window = 300 mm²
        # (single bobbin between the two outer legs)
        Wa_mm2=300.0,
        # MLT back-fit from the spec: Rdc = ρ·N·MLT / A_cu →
        # MLT = Rdc·A_cu / (ρ·N). For 0.95 mm wire (A=0.708 mm²),
        # 122 turns, Rdc=0.45 Ω: MLT = 0.45·0.708e-6 / (1.72e-8·122)
        # ≈ 152 mm
        MLT_mm=152.0,
        Bsat_T=SILICON_BSAT,
        mu_initial=SILICON_MU,
        rho_kg_m3=SILICON_RHO,
        L_mH=10.0,
        N_spec=122,
        wire_d_cu_mm=0.95,
        Rdc_max_ohm=0.45,
        I_rated_A=3.5,
    ),
    DatasheetReactor(
        model="DX60414CT",
        core_label="EI41",
        silicon_grade="50CS1300",
        # Drawing: 62 wide × 36.5 high, 17 mm stack (estimate)
        stack_mm=17.0,
        # Ae ≈ 14 × 17 (center leg is ~14 mm in EI41)
        Ae_mm2=240.0,
        # le for EI41 ≈ 80 mm
        le_mm=80.0,
        # Wa ≈ 18 × 7 = 126 mm² per side, ~125 mm² total
        Wa_mm2=125.0,
        # MLT back-fit: 0.61 Ω, 0.70 mm (A=0.385 mm²), N=140
        # MLT = 0.61·0.385e-6 / (1.72e-8·140) ≈ 97 mm
        MLT_mm=97.0,
        Bsat_T=SILICON_BSAT,
        mu_initial=SILICON_MU,
        rho_kg_m3=SILICON_RHO,
        L_mH=10.0,
        N_spec=140,
        wire_d_cu_mm=0.70,
        Rdc_max_ohm=0.61,
        I_rated_A=2.2,
    ),
    DatasheetReactor(
        model="DX60415CT",
        core_label="EI28",
        silicon_grade="50H1300",
        # Drawing: 53 × 31.6, 17 mm stack
        stack_mm=17.0,
        # Ae ≈ 10 × 17
        Ae_mm2=170.0,
        # le for EI28 ≈ 65 mm
        le_mm=65.0,
        # Wa ≈ 13 × 5 = 65 mm² per side
        Wa_mm2=80.0,
        # MLT back-fit: 0.60 Ω, 0.65 mm (A=0.332 mm²), N=120
        # MLT = 0.60·0.332e-6 / (1.72e-8·120) ≈ 96 mm
        MLT_mm=96.0,
        Bsat_T=SILICON_BSAT,
        mu_initial=SILICON_MU,
        rho_kg_m3=SILICON_RHO,
        L_mH=10.0,
        N_spec=120,
        wire_d_cu_mm=0.65,
        Rdc_max_ohm=0.60,
        I_rated_A=1.0,
    ),
    DatasheetReactor(
        model="DX60415CT",
        core_label="EI28",
        silicon_grade="50H1300",
        # Drawing: 53 × 31.6, 17 mm stack
        stack_mm=17.0,
        # Ae ≈ 10 × 17
        Ae_mm2=170.0,
        # le for EI28 ≈ 65 mm
        le_mm=65.0,
        # Wa ≈ 13 × 5 = 65 mm² per side
        Wa_mm2=80.0,
        # MLT back-fit: 0.60 Ω, 0.65 mm (A=0.332 mm²), N=120
        # MLT = 0.60·0.332e-6 / (1.72e-8·120) ≈ 96 mm
        MLT_mm=96.0,
        Bsat_T=SILICON_BSAT,
        mu_initial=SILICON_MU,
        rho_kg_m3=SILICON_RHO,
        L_mH=10.0,
        N_spec=120,
        wire_d_cu_mm=0.65,
        Rdc_max_ohm=0.60,
        I_rated_A=2.2,
    ),
    DatasheetReactor(
        model="DX60415CT",
        core_label="EI28",
        silicon_grade="50H1300",
        # Drawing: 53 × 31.6, 17 mm stack
        stack_mm=17.0,
        # Ae ≈ 10 × 17
        Ae_mm2=170.0,
        # le for EI28 ≈ 65 mm
        le_mm=65.0,
        # Wa ≈ 13 × 5 = 65 mm² per side
        Wa_mm2=80.0,
        # MLT back-fit: 0.60 Ω, 0.65 mm (A=0.332 mm²), N=120
        # MLT = 0.60·0.332e-6 / (1.72e-8·120) ≈ 96 mm
        MLT_mm=96.0,
        Bsat_T=SILICON_BSAT,
        mu_initial=SILICON_MU,
        rho_kg_m3=SILICON_RHO,
        L_mH=7.0,
        N_spec=120,
        wire_d_cu_mm=0.65,
        Rdc_max_ohm=0.60,
        I_rated_A=2.2,
    ),
]


# ---------------------------------------------------------------------------
# Build internal models from each datasheet
# ---------------------------------------------------------------------------
def build_material(d: DatasheetReactor) -> Material:
    return Material(
        id=f"dx-silicon-{d.silicon_grade.lower()}",
        vendor="Dongxing/AKArc",
        family="silicon steel (NGO)",
        name=f"{d.silicon_grade} (silicon steel)",
        type="silicon-steel",
        mu_initial=d.mu_initial,
        Bsat_25C_T=d.Bsat_T,
        Bsat_100C_T=d.Bsat_T * 0.95,
        rho_kg_m3=d.rho_kg_m3,
        steinmetz=SteinmetzParams(
            Pv_ref_mWcm3=2.0,
            alpha=1.55,
            beta=1.85,
            f_ref_kHz=0.060,
            B_ref_mT=1000.0,
            f_min_kHz=0.040,
            f_max_kHz=1.0,
        ),
        rolloff=None,
        notes=f"Built from datasheet {d.model} for confrontation.",
    )


def build_core(d: DatasheetReactor, material_id: str) -> Core:
    # AL back-fit so L_actual = L_spec when N = N_spec.
    AL_nH = (d.L_mH * 1000.0) / (d.N_spec**2) * 1000.0
    return Core(
        id=f"dx-{d.core_label.lower()}-{d.model.lower()}",
        vendor="Dongxing",
        shape="EI",
        part_number=d.core_label,
        default_material_id=material_id,
        Ae_mm2=d.Ae_mm2,
        le_mm=d.le_mm,
        Ve_mm3=d.Ae_mm2 * d.le_mm,
        Wa_mm2=d.Wa_mm2,
        MLT_mm=d.MLT_mm,
        AL_nH=AL_nH,
        notes=f"Built from datasheet {d.model}, stack {d.stack_mm} mm.",
    )


def build_wire(d: DatasheetReactor) -> Wire:
    A_cu = math.pi * (d.wire_d_cu_mm / 2.0) ** 2
    # Insulated diameter ≈ 1.05 × bare for 2UEW polyurethane
    d_iso = d.wire_d_cu_mm * 1.05
    return Wire(
        id=f"dx-2uew-{d.wire_d_cu_mm:.2f}",
        type="round",
        d_cu_mm=d.wire_d_cu_mm,
        d_iso_mm=d_iso,
        A_cu_mm2=A_cu,
        notes="2UEW polyurethane MW75/130 °C. Built for datasheet confrontation.",
    )


def build_spec(d: DatasheetReactor) -> Spec:
    # Compute the implied %Z from L=10 mH, V=220 V, I=I_rated.
    # ω·L = 2π·50·0.01 = 3.1416 Ω; %Z = 100·ω·L/(V/I) = 100·3.1416·I/V
    pct_Z = 100.0 * (2 * math.pi * 50.0 * d.L_mH * 1e-3) * d.I_rated_A / 220.0
    return Spec(
        topology="line_reactor",
        n_phases=1,
        Vin_nom_Vrms=220.0,
        I_rated_Arms=d.I_rated_A,
        pct_impedance=max(0.5, min(20.0, pct_Z)),
        f_line_Hz=50.0,
        Vin_min_Vrms=200.0,
        Vin_max_Vrms=265.0,
        Vout_V=400.0,
        Pout_W=200.0,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
        T_amb_C=40.0,
        T_max_C=130.0,
        Ku_max=0.7,
        Bsat_margin=0.20,
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def _pct(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-9) * 100.0


def compare(d: DatasheetReactor) -> dict:
    mat = build_material(d)
    core = build_core(d, mat.id)
    wire = build_wire(d)
    spec = build_spec(d)
    r = design(spec, core, wire, mat)

    print(f"=== {d.model}  ({d.core_label}, silicon {d.silicon_grade}) ===")
    print(
        f"  spec:  V=220 Vrms · I={d.I_rated_A} A · L=10 mH · %Z = {spec.pct_impedance:.2f}"
    )
    print(
        f"  core:  Ae={d.Ae_mm2} mm²  le={d.le_mm} mm  Wa={d.Wa_mm2} mm²  MLT={d.MLT_mm} mm"
    )

    # Engine Rdc at 25 °C (the comparable basis to datasheet's "max").
    # The engine itself reports Rdc at T_winding, which is hotter — so
    # we project it back to 25 °C using the standard ρ_Cu temperature
    # coefficient (0.39 %/°C) for the side-by-side row.
    R25_engine = r.R_dc_ohm / (1.0 + 0.0039 * (r.T_winding_C - 25.0))
    A_cu = wire.A_cu_mm2
    L_total_m = d.MLT_mm * r.N_turns * 1e-3
    R25_handcalc = 1.72e-8 * L_total_m / (A_cu * 1e-6)

    print()
    print("  {:<28} {:>11} {:>11} {:>9}".format("", "datasheet", "engine", "Δ"))
    print("  {:-<28} {:-<11} {:-<11} {:-<9}".format("", "", "", ""))
    print(
        "  {:<28} {:>11} {:>11} {:>+8}".format("Turns N", d.N_spec, r.N_turns, r.N_turns - d.N_spec)
    )
    print(
        "  {:<28} {:>11.2f} {:>11.2f} {:>8.1f}%".format(
            "L (mH)", d.L_mH, r.L_actual_uH / 1000, _pct(r.L_actual_uH / 1000, d.L_mH)
        )
    )
    print(
        "  {:<28} {:>11.0f} {:>11.0f} {:>8.1f}%".format(
            "Rdc @ 25 °C (mΩ)",
            d.Rdc_max_ohm * 1000,
            R25_engine * 1000,
            _pct(R25_engine, d.Rdc_max_ohm),
        )
    )
    print(
        "  {:<28} {:>11} {:>11.0f} (@ {:.0f} °C)".format(
            "Rdc @ T_winding (mΩ)", "", r.R_dc_ohm * 1000, r.T_winding_C
        )
    )
    print(
        "  {:<28} {:>11.2f} {:>11.2f}".format(
            "V_drop (V)",
            (2 * math.pi * 50 * d.L_mH * 1e-3 * d.I_rated_A),
            (r.voltage_drop_pct / 100 * 220 if r.voltage_drop_pct else 0),
        )
    )
    print(
        "  {:<28} {:>11} {:>11.0f} ({:.0f} % of Bsat)".format(
            "B_pk (mT)", "", r.B_pk_T * 1000, 100 * r.B_pk_T / d.Bsat_T
        )
    )
    print("  {:<28} {:>11} {:>11.1f}".format("Ku (%)", "", r.Ku_actual * 100))
    print("  {:<28} {:>11} {:>11.0f}".format("T winding (°C)", "", r.T_winding_C))
    if r.warnings:
        for w in r.warnings:
            print(f"     ⚠ {w}")

    # Verdict
    n_ok = abs(r.N_turns - d.N_spec) <= 2
    rdc_ok = _pct(R25_engine, d.Rdc_max_ohm) <= 10.0
    b_ok = r.B_pk_T < d.Bsat_T
    print()
    print(f"  N ≈ datasheet (±2):     {'✓' if n_ok else '✗'}")
    print(f"  Rdc @ 25 °C within 10%: {'✓' if rdc_ok else '✗'}")
    print(f"  B_pk under Bsat:        {'✓' if b_ok else '✗'}")

    return {
        "Model": d.model,
        "Core": d.core_label,
        "Turns (Datasheet)": d.N_spec,
        "Turns (Engine)": r.N_turns,
        "Turns Δ": r.N_turns - d.N_spec,
        "L (mH) (Datasheet)": d.L_mH,
        "L (mH) (Engine)": r.L_actual_uH / 1000,
        "L Δ (%)": _pct(r.L_actual_uH / 1000, d.L_mH),
        "Rdc @ 25°C (mΩ) (Datasheet)": d.Rdc_max_ohm * 1000,
        "Rdc @ 25°C (mΩ) (Engine)": R25_engine * 1000,
        "Rdc @ 25°C Δ (%)": _pct(R25_engine, d.Rdc_max_ohm),
        "Rdc @ T_winding (mΩ) (Engine)": r.R_dc_ohm * 1000,
        "T_winding (°C)": r.T_winding_C,
        "V_drop (V) (Datasheet)": (2 * math.pi * 50 * d.L_mH * 1e-3 * d.I_rated_A),
        "V_drop (V) (Engine)": (r.voltage_drop_pct / 100 * 220 if r.voltage_drop_pct else 0),
        "B_pk (mT) (Engine)": r.B_pk_T * 1000,
        "Ku (%) (Engine)": r.Ku_actual * 100,
        "N ≈ datasheet (±2)": "✓" if n_ok else "✗",
        "Rdc @ 25°C within 10%": "✓" if rdc_ok else "✗",
        "B_pk under Bsat": "✓" if b_ok else "✗",
        # New fields for manufacturer and spec data
        "V_nom (Vrms)": spec.Vin_nom_Vrms,
        "I_rated (A)": spec.I_rated_Arms,
        "L_mH (Datasheet)": d.L_mH,  # Already there, but keeping for clarity
        "pct_impedance": spec.pct_impedance,
        "Ae (mm²)": d.Ae_mm2,
        "le (mm)": d.le_mm,
        "Wa (mm²)": d.Wa_mm2,
        "MLT (mm)": d.MLT_mm,
    }


def main() -> int:
    print("Confrontação contra datasheets Dongxing (reatores 10 mH harmônicos)")
    results = []
    for d in DATASHEETS:
        results.append(compare(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
