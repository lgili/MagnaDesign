#!/usr/bin/env python3
"""Generate every screenshot the LaTeX presentation references.

Output goes into ``presentation/figures/``. The harness constructs
three reference designs (Boost PFC 1.5 kW, Line Reactor 22 kW,
Flyback 65 W) as proper Pydantic models, populates the matching
UI widgets, and grabs PNGs of each.

Run:
    python presentation/scripts/build_screenshots.py
or:
    make -C presentation screenshots

The harness runs Qt offscreen (``QT_QPA_PLATFORM=offscreen``), so
no display is required — works in CI / headless servers.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Repo layout: presentation/scripts/build_screenshots.py →
# resolve src/ for imports.
HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent.parent
SRC = ROOT / "src"
FIGS = HERE.parent.parent / "figures"
sys.path.insert(0, str(SRC))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget  # noqa: E402

# Pydantic models.
from pfc_inductor.models.core import Core  # noqa: E402
from pfc_inductor.models.material import Material, SteinmetzParams  # noqa: E402
from pfc_inductor.models.result import DesignResult, LossBreakdown  # noqa: E402
from pfc_inductor.models.spec import Spec  # noqa: E402
from pfc_inductor.models.wire import Wire  # noqa: E402

# Chart widgets.
from pfc_inductor.fea.models import FEAValidation  # noqa: E402
from pfc_inductor.ui.widgets.fea_bh_loop import (  # noqa: E402
    BHLoopChart, BHLoopPayload,
)
from pfc_inductor.ui.widgets.fea_geometry_view import (  # noqa: E402
    GeometryPayload, GeometryView,
)
from pfc_inductor.ui.widgets.fea_swept_chart import (  # noqa: E402
    SweptFEAChart, SweptFEAPayload,
)
from pfc_inductor.ui.widgets.harmonic_spectrum_chart import (  # noqa: E402
    HarmonicSpectrumChart, HarmonicSpectrumPayload,
)
from pfc_inductor.ui.widgets.loss_stacked_bar import (  # noqa: E402
    LossBreakdownPayload, LossStackedBar,
)
from pfc_inductor.ui.widgets.phase_overlay_chart import (  # noqa: E402
    PhaseOverlayChart, PhaseOverlayPayload,
)


# ---------------------------------------------------------------
# Reference designs — three real-world examples.
# ---------------------------------------------------------------
@dataclass
class RefDesign:
    """Complete model bundle for one demonstration design."""
    spec: Spec
    core: Core
    wire: Wire
    material: Material
    result: DesignResult
    label: str


def design_boost_1500w() -> RefDesign:
    """Universal-input boost PFC, 1.5 kW, 100 kHz.

    Reference: TI UCC28019 application note + Magnetics Kool-Mu
    77439A7 toroid, AWG 16 solid wire. Typical server-PSU /
    industrial-drive front-end. Operating point at low-line
    (85 V) for the worst-case I_pk.
    """
    spec = Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vin_nom_Vrms=110,
        f_line_Hz=60, Vout_V=400, Pout_W=1500, eta=0.96,
        f_sw_kHz=100,
    )
    core = Core(
        id="0077439A7", vendor="Magnetics", shape="toroid",
        part_number="0077439A7", default_material_id="60_KoolMu",
        OD_mm=39.9, ID_mm=24.0, HT_mm=14.5,
        Ae_mm2=107.2, le_mm=98.4, Ve_mm3=10550, Wa_mm2=452,
        MLT_mm=58.0, AL_nH=135, lgap_mm=0.0,
    )
    wire = Wire(
        id="AWG16", type="round", awg=16, d_cu_mm=1.291,
        d_iso_mm=1.46, A_cu_mm2=1.31,
    )
    mat = Material(
        id="60_KoolMu", vendor="Magnetics", family="KoolMu",
        name="60 Kool-Mu", type="powder",
        mu_initial=60, Bsat_25C_T=1.0, Bsat_100C_T=0.95,
        steinmetz=SteinmetzParams(
            Pv_ref_mWcm3=380, f_ref_kHz=100, B_ref_mT=100,
            alpha=1.5, beta=2.4,
        ),
    )
    # Synthesise waveforms over half a line cycle.
    N = 200
    t_arr = [k / N * 0.5 / 60.0 for k in range(N)]
    iL = [16.6 * math.sin(2 * math.pi * 60 * t) for t in t_arr]
    B = [0.32 * math.sin(2 * math.pi * 60 * t) for t in t_arr]
    result = DesignResult(
        L_required_uH=400, L_actual_uH=406, N_turns=55,
        I_line_pk_A=16.6, I_line_rms_A=11.7,
        I_ripple_pk_pk_A=2.8, I_pk_max_A=18.0, I_rms_total_A=11.9,
        H_dc_peak_Oe=145, mu_pct_at_peak=58,
        B_pk_T=0.32, B_sat_limit_T=0.95, sat_margin_pct=66,
        R_dc_ohm=0.058, R_ac_ohm=0.064,
        losses=LossBreakdown(
            P_cu_dc_W=1.10, P_cu_ac_W=0.55,
            P_core_line_W=1.20, P_core_ripple_W=0.30,
        ),
        T_rise_C=18, T_winding_C=68, Ku_actual=0.42, Ku_max=0.6,
        converged=True, warnings=[], notes="",
        waveform_t_s=t_arr, waveform_iL_A=iL, waveform_B_T=B,
    )
    return RefDesign(spec=spec, core=core, wire=wire, material=mat,
                     result=result, label="Boost PFC 1.5 kW")


def design_line_reactor_22kw() -> RefDesign:
    """3-phase line reactor for a 22 kW VFD input.

    Reference: ABB MCB-32 / Schaffner FN3220 class — 3 %
    impedance at 60 Hz, M19 silicon-steel E-I core, ~ 250
    turns AWG 12 solid. The classic IEC 61000-3-2 compliance
    inductor for industrial drives.
    """
    spec = Spec(
        topology="line_reactor",
        Vin_min_Vrms=380, Vin_max_Vrms=420, Vin_nom_Vrms=400,
        f_line_Hz=60, Vout_V=540, Pout_W=22000, eta=0.97,
        f_sw_kHz=10, n_phases=3,
    )
    # Custom toroid synthesised to match the analytical L target;
    # real silicon-steel cores are E-I but we model toroid for
    # the dispatch demo (FEMM legacy).
    core = Core(
        id="MS-330", vendor="Magnetics", shape="toroid",
        part_number="MS-330-100", default_material_id="M19_SiSteel",
        OD_mm=104, ID_mm=66, HT_mm=33,
        Ae_mm2=625, le_mm=265, Ve_mm3=166000, Wa_mm2=3420,
        MLT_mm=140, AL_nH=12, lgap_mm=0.0,
    )
    wire = Wire(
        id="AWG12", type="round", awg=12, d_cu_mm=2.05,
        d_iso_mm=2.30, A_cu_mm2=3.31,
    )
    mat = Material(
        id="M19_SiSteel", vendor="Generic", family="SiliconSteel",
        name="M19 0.35 mm", type="silicon-steel",
        mu_initial=4500, Bsat_25C_T=1.85, Bsat_100C_T=1.75,
        steinmetz=SteinmetzParams(
            Pv_ref_mWcm3=2.5, f_ref_kHz=0.06, B_ref_mT=1500,
            alpha=1.6, beta=2.0,
        ),
    )
    # Triangular saturating waveform — characteristic of LC
    # filter output current shape.
    N = 200
    t_arr = [k / N * (1.0 / 60.0) for k in range(N)]
    iL = [32.0 * math.sin(2 * math.pi * 60 * t) for t in t_arr]
    B = [1.20 * math.sin(2 * math.pi * 60 * t) for t in t_arr]
    result = DesignResult(
        L_required_uH=2500, L_actual_uH=2580, N_turns=250,
        I_line_pk_A=45.2, I_line_rms_A=32.0,
        I_ripple_pk_pk_A=0, I_pk_max_A=45.2, I_rms_total_A=32.0,
        H_dc_peak_Oe=420, mu_pct_at_peak=85,
        B_pk_T=1.20, B_sat_limit_T=1.75, sat_margin_pct=31,
        R_dc_ohm=0.080, R_ac_ohm=0.090,
        losses=LossBreakdown(
            P_cu_dc_W=82, P_cu_ac_W=4,
            P_core_line_W=21, P_core_ripple_W=0,
        ),
        T_rise_C=42, T_winding_C=82, Ku_actual=0.46, Ku_max=0.6,
        converged=True, warnings=[], notes="",
        waveform_t_s=t_arr, waveform_iL_A=iL, waveform_B_T=B,
        thd_estimate_pct=24.0, voltage_drop_pct=2.8,
    )
    return RefDesign(spec=spec, core=core, wire=wire, material=mat,
                     result=result, label="Line reactor 22 kW")


def design_flyback_65w() -> RefDesign:
    """Universal-input flyback DCM 65 W (laptop-adapter class).

    Reference: TI UCC28911 EVM + a PQ20/16 N97 ferrite core.
    Coupled-pair primary 42 turns / secondary 12 turns,
    n = 3.5. DCM at full load.
    """
    spec = Spec(
        topology="flyback",
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vin_nom_Vrms=230,
        f_line_Hz=60, Vout_V=19, Pout_W=65, eta=0.92,
        f_sw_kHz=65,
    )
    core = Core(
        id="PQ20-16", vendor="TDK", shape="pq",
        part_number="PQ20/16", default_material_id="N97",
        OD_mm=20.5, ID_mm=0, HT_mm=16.2,
        Ae_mm2=62.6, le_mm=37.6, Ve_mm3=2354, Wa_mm2=33,
        MLT_mm=42, AL_nH=2900, lgap_mm=0.40,
    )
    wire = Wire(
        id="AWG24", type="round", awg=24, d_cu_mm=0.511,
        d_iso_mm=0.59, A_cu_mm2=0.205,
    )
    mat = Material(
        id="N97", vendor="TDK/EPCOS", family="Ferrite",
        name="N97 Ferrite", type="ferrite",
        mu_initial=2300, Bsat_25C_T=0.49, Bsat_100C_T=0.39,
        steinmetz=SteinmetzParams(
            Pv_ref_mWcm3=420, f_ref_kHz=100, B_ref_mT=200,
            alpha=1.4, beta=2.6,
        ),
    )
    N = 200
    Tsw = 1.0 / 65000.0
    t_arr = [k / N * Tsw for k in range(N)]
    # Triangular DCM primary current
    iL = []
    for t in t_arr:
        tau = (t % Tsw) / Tsw
        if tau < 0.45:
            iL.append(4.2 * (tau / 0.45))
        elif tau < 0.85:
            iL.append(4.2 * (1 - (tau - 0.45) / 0.40))
        else:
            iL.append(0.0)
    # DCM B(t) follows i_p
    B_pk = 0.28
    B = [B_pk * (i / 4.2) for i in iL]
    result = DesignResult(
        L_required_uH=350, L_actual_uH=358, N_turns=42,
        I_line_pk_A=4.2, I_line_rms_A=1.6,
        I_ripple_pk_pk_A=4.2, I_pk_max_A=4.2, I_rms_total_A=1.6,
        H_dc_peak_Oe=88, mu_pct_at_peak=92,
        B_pk_T=0.28, B_sat_limit_T=0.39, sat_margin_pct=28,
        R_dc_ohm=0.32, R_ac_ohm=0.40,
        losses=LossBreakdown(
            P_cu_dc_W=0.85, P_cu_ac_W=0.35,
            P_core_line_W=0.0, P_core_ripple_W=0.65,
        ),
        T_rise_C=22, T_winding_C=72, Ku_actual=0.38, Ku_max=0.5,
        converged=True, warnings=[], notes="",
        waveform_t_s=t_arr, waveform_iL_A=iL, waveform_B_T=B,
        Lp_actual_uH=358, Np_turns=42, Ns_turns=12,
        Ip_peak_A=4.2, Ip_rms_A=1.6, Is_peak_A=14.7, Is_rms_A=4.5,
    )
    return RefDesign(spec=spec, core=core, wire=wire, material=mat,
                     result=result, label="Flyback 65 W")


# ---------------------------------------------------------------
# Render helpers.
# ---------------------------------------------------------------
def _grab(widget, path: Path, w: int, h: int) -> None:
    """Set widget to a fixed size, force layout, and grab PNG."""
    widget.resize(w, h)
    widget.show()
    QApplication.processEvents()
    pix = widget.grab()
    pix.save(str(path))
    widget.hide()


def render_geometry(d: RefDesign, out: Path) -> None:
    g = GeometryView()
    g.show_payload(GeometryPayload.from_models(d.core, d.wire, d.result))
    _grab(g, out, 760, 480)


def render_bh_curve(d: RefDesign, out: Path) -> None:
    bh = BHLoopChart()
    bh.show_payload(BHLoopPayload.from_models(
        d.material, d.result, hot=True,
    ))
    _grab(bh, out, 800, 460)


def render_swept_chart(d: RefDesign, out: Path) -> None:
    """Synthesised swept-FEA result anchored on the design's
    operating point. Not a real solve; for the slide deck the
    rolloff shape is what we want to show."""
    sc = SweptFEAChart()
    L0 = d.result.L_actual_uH
    Ipk = d.result.I_line_pk_A
    Bpk = d.result.B_pk_T
    Bsat = d.material.Bsat_100C_T
    n = 5
    currents = tuple(Ipk * (k + 0.5) / n for k in range(n))
    # Synthetic rolloff: L drops to 0.55·L₀ at peak.
    L_uH = tuple(L0 * (1 - 0.45 * (I / Ipk) ** 1.4) for I in currents)
    B_T = tuple(min(Bpk * (I / Ipk) ** 0.85, Bsat * 0.95) for I in currents)
    sc.show_payload(SweptFEAPayload(
        currents_A=currents, L_uH=L_uH, B_T=B_T,
        operating_point_A=Ipk, Bsat_T=Bsat, Bsat_margin=0.2,
        n_points=n, backend="femmt",
    ))
    _grab(sc, out, 880, 500)


def render_loss_bar(d: RefDesign, out: Path,
                     thermal_limit_W: float = 6.0) -> None:
    lb = LossStackedBar()
    lb.show_payload(LossBreakdownPayload.from_result(
        d.result, thermal_limit_W=thermal_limit_W,
    ))
    _grab(lb, out, 880, 200)


def render_harmonics(out: Path, *, with_choke: bool, label: str) -> None:
    """Synthesised harmonics demonstrating the line-reactor effect."""
    hs = HarmonicSpectrumChart()
    if with_choke:
        # 22 kW VFD with line reactor — green / amber palette
        orders = (1, 3, 5, 7, 9, 11, 13, 15)
        amps = (32.0, 0.0, 1.6, 0.95, 0.0, 0.45, 0.30, 0.22)
    else:
        orders = (1, 3, 5, 7, 9, 11, 13, 15)
        amps = (32.0, 0.0, 9.5, 5.5, 0.0, 1.8, 1.0, 0.65)
    hs.show_payload(HarmonicSpectrumPayload(
        orders=orders, amplitudes_A=amps,
        iec_class="A", P_in_W=22000,
        f_line_Hz=60, topology_name=label,
    ))
    _grab(hs, out, 900, 480)


def render_phase_overlay(d: RefDesign, out: Path) -> None:
    p = PhaseOverlayChart()
    p.show_payload(PhaseOverlayPayload(
        n_phases=2, I_avg_per_phase_A=d.result.I_line_rms_A / 2,
        delta_iL_pp_A=d.result.I_ripple_pk_pk_A,
        fsw_Hz=d.spec.f_sw_kHz * 1000.0,
        duty=0.55,
    ))
    _grab(p, out, 900, 480)


def render_analise_page(d: RefDesign, out: Path,
                         w: int = 1280, h: int = 2400) -> None:
    """Full AnalisePage screenshot — the most visually striking
    one for the talk. Wraps in a window so the chrome paints."""
    from pfc_inductor.ui.workspace.analise_page import AnalisePage

    page = AnalisePage()
    page.update_from_design(
        d.result, d.spec, d.core, d.wire, d.material,
    )
    win = QMainWindow()
    container = QWidget()
    v = QVBoxLayout(container)
    v.setContentsMargins(0, 0, 0, 0)
    v.addWidget(page)
    win.setCentralWidget(container)
    win.resize(w, h)
    win.show()
    QApplication.processEvents()
    win.grab().save(str(out))
    win.hide()


# ---------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------
def main() -> None:
    FIGS.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    boost = design_boost_1500w()
    reactor = design_line_reactor_22kw()
    flyback = design_flyback_65w()

    # ── Example 1: Boost PFC 1.5 kW ──
    print("[boost-1.5kW]")
    render_geometry(boost,   FIGS / "example1_geometry.png")
    render_bh_curve(boost,   FIGS / "example1_bh_curve.png")
    render_loss_bar(boost,   FIGS / "example1_loss_stacked.png", 6.0)
    render_swept_chart(boost, FIGS / "example1_fea_swept.png")
    render_analise_page(boost, FIGS / "example1_analise_overview.png")

    # ── Example 2: Line reactor 22 kW ──
    print("[line-reactor-22kW]")
    render_harmonics(FIGS / "example2_harmonics.png",
                     with_choke=True, label="With line reactor")
    render_harmonics(FIGS / "example2_harmonics_no_choke.png",
                     with_choke=False, label="No choke")
    render_harmonics(FIGS / "example2_harmonics_with_choke.png",
                     with_choke=True, label="With choke")
    render_geometry(reactor, FIGS / "example2_geometry.png")
    render_bh_curve(reactor, FIGS / "example2_bh_curve.png")

    # ── Example 3: Flyback 65 W ──
    print("[flyback-65W]")
    render_geometry(flyback, FIGS / "example3_geometry.png")
    render_bh_curve(flyback, FIGS / "example3_bh_curve.png")
    render_loss_bar(flyback, FIGS / "example3_loss_stacked.png", 3.0)
    render_swept_chart(flyback, FIGS / "example3_fea_swept.png")

    # ── Reused prior screenshots from /tmp ──
    # The session generated several FEA-dialog and gallery shots
    # that fit the talk verbatim; copy them into figures/.
    reuses = {
        "/tmp/fea_alltabs_summary.png":   "example1_fea_summary.png",
        "/tmp/fea_alltabs_geometry.png":  "feature_fea_dialog_full.png",
        "/tmp/fea_alltabs_bh.png":        "example3_fea_bh.png",
        "/tmp/fea_gallery_v3.png":        "feature_gallery.png",
        "/tmp/fea_lightbox_v3.png":       "feature_lightbox.png",
        "/tmp/test_magb_render.png":      "example1_fea_field_heatmap.png",
        "/tmp/fea_demo_dir/e_m/results/fields/Magb_centerline.png":
            "example1_fea_field_centerline.png",
        "/tmp/analise_interleaved.png":   "feature_analise_interleaved.png",
        "/tmp/analise_line_reactor.png":  "feature_analise_linereactor.png",
        "/tmp/dash_po_card.png":          "feature_phase_overlay_card.png",
        "/tmp/dash_hs_card.png":          "feature_harmonic_card.png",
    }
    for src, name in reuses.items():
        s = Path(src)
        if s.exists():
            shutil.copy(s, FIGS / name)
            print(f"[copied] {s.name} → {name}")

    # ── Placeholders for screens that need a live app run ──
    # (cascade page, compare dialog, export, 3D viewer, spec
    # drawer). For these, a small text-only PDF is emitted so
    # the LaTeX includes don't error out — the user can replace
    # them with real screenshots as they become available.
    placeholders = [
        ("example1_spec.png",         "Spec drawer — Boost PFC 1.5 kW"),
        ("example1_formas_onda.png",  "Waveform card — i_L(t) and B(t)"),
        ("example2_spec.png",         "Spec drawer — Line reactor 3φ 22 kW"),
        ("example2_fea_dispatch.png", "FEA auto-fallback log (FEMMT → FEMM legacy)"),
        ("example3_spec.png",         "Spec drawer — Flyback 65 W"),
        ("example3_formas_onda.png",  "Waveform card — primary + secondary"),
        ("example3_fea_summary.png",  "FEA Summary tab — flyback"),
        ("feature_otimizador_pareto.png", "Pareto front — 1000+ candidates"),
        ("feature_cascade.png",       "Cascade optimiser — Top-N table"),
        ("feature_compare.png",       "Compare designs side-by-side"),
        ("feature_export.png",        "Datasheet HTML export"),
        ("feature_3d.png",            "Qt3D ortographic view"),
        ("logo-placeholder.pdf",      "MagnaDesign"),
    ]
    for name, label in placeholders:
        out = FIGS / name
        if out.exists():
            continue
        _emit_placeholder(out, label)

    print(f"\nDone. {sum(1 for _ in FIGS.iterdir())} files in figures/.")


def _emit_placeholder(out: Path, label: str) -> None:
    """Render a clean placeholder image with centered text. Used
    when a real screenshot isn't available yet so the slide deck
    builds end-to-end."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
    fig.patch.set_facecolor("#F9FAFB")
    ax.set_facecolor("#F9FAFB")
    ax.set_axis_off()
    ax.text(
        0.5, 0.55, "[ screenshot pendente ]",
        ha="center", va="center", fontsize=14,
        color="#6B7280",
        transform=ax.transAxes,
    )
    ax.text(
        0.5, 0.40, label,
        ha="center", va="center", fontsize=11,
        color="#1F2937",
        transform=ax.transAxes,
    )
    ax.text(
        0.5, 0.30,
        "Substitua este arquivo por um print real do app.",
        ha="center", va="center", fontsize=8,
        color="#9CA3AF",
        transform=ax.transAxes,
    )
    fig.tight_layout()
    if out.suffix == ".pdf":
        fig.savefig(str(out), bbox_inches="tight",
                    facecolor=fig.get_facecolor())
    else:
        fig.savefig(str(out), bbox_inches="tight",
                    facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
