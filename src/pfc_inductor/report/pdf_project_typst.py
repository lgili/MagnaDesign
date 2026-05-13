"""Engineering project report — Typst backend.

A complete rewrite of :mod:`pfc_inductor.report.pdf_project` using the
:func:`pfc_inductor.report.typst_runtime.compile_to_pdf` pipeline. The
output is reference-grade engineering typography: proper math
rendering, kerned body text, table headers that repeat across pages,
and a layout that doesn't fight you on widow/orphan control.

The semantic content matches the engineer's request: every equation
the design engine actually evaluates is surfaced in three lines —
symbolic form, the same equation with the project's values
substituted, and the computed result. Nothing is hidden. The
engineer can trace any final number back to the textbook formula
that produced it.

Public API mirrors the legacy ReportLab module:

    generate_project_report_typst(
        spec, core, material, wire, result,
        output_path,
        designer=..., revision="A", project_id=None,
    ) -> Path

Topology coverage in this first cut: boost-CCM (the user's primary
target for PFC compressor-inverter designs). Other topologies fall
back to the legacy ReportLab module via :func:`generate_project_report`
when ``use_typst=True`` is not the default for them.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Optional

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import copper as cp
from pfc_inductor.physics import core_loss as cl
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.physics import thermal as th
from pfc_inductor.report.typst_runtime import compile_to_pdf

MU_0 = rf.MU_0  # 4π × 10⁻⁷ T·m/A
RHO_CU_20 = 1.724e-8  # Ω·m


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_project_report_typst(
    spec: Spec,
    core: Core,
    material: Material,
    wire: Wire,
    result: DesignResult,
    output_path: Path | str,
    *,
    designer: str = "—",
    revision: str = "A",
    project_id: Optional[str] = None,
) -> Path:
    """Render the engineering project report via Typst and write it
    to ``output_path``.

    See module docstring for the contract.
    """
    typst_source = _render_template(
        spec=spec,
        core=core,
        material=material,
        wire=wire,
        result=result,
        designer=designer,
        revision=revision,
        project_id=project_id or _hash_project_id(spec, core, material),
    )
    return compile_to_pdf(typst_source, output_path)


# ---------------------------------------------------------------------------
# Template rendering — single Typst source, fully self-contained
# ---------------------------------------------------------------------------
def _render_template(
    *,
    spec: Spec,
    core: Core,
    material: Material,
    wire: Wire,
    result: DesignResult,
    designer: str,
    revision: str,
    project_id: str,
) -> str:
    ctx = _compute_context(spec, core, material, wire, result)
    ctx.update(
        designer=_esc(designer),
        revision=_esc(revision),
        project_id=_esc(project_id),
        date_iso=datetime.now().strftime("%Y-%m-%d"),
        topology_label=_esc(_topology_label(spec.topology)),
        spec=spec,
    )
    return _TEMPLATE.format(**ctx)


def _topology_label(t: str) -> str:
    return {
        "boost_ccm": "Boost-PFC CCM (active)",
        "interleaved_boost_pfc": "Interleaved boost-PFC CCM (active)",
        "passive_choke": "Passive PFC choke",
        "line_reactor": "Line reactor (1φ / 3φ)",
        "buck_ccm": "Buck CCM (DC-DC step-down)",
        "flyback": "Flyback (isolated DC-DC)",
    }.get(t, t)


def _hash_project_id(spec: Spec, core: Core, material: Material) -> str:
    """Stable 8-char id derived from spec + selection — same as the
    datasheet uses so the two artefacts cross-reference."""
    import hashlib

    key = f"{spec.topology}|{spec.Pout_W:.0f}|{core.id}|{material.id}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8].upper()


# ---------------------------------------------------------------------------
# Intermediate values — every number the engine touched, computed once.
# ---------------------------------------------------------------------------
def _compute_context(
    spec: Spec, core: Core, material: Material, wire: Wire, result: DesignResult
) -> dict:
    """Recompute the intermediate values the engine produced so the
    template can render every step of the derivation with consistent
    numbers — symbolic equation → values substituted → result."""
    # ── Operating point (boost-CCM math; mirrors topology.boost_ccm) ──
    Vin_min = spec.Vin_min_Vrms
    Vin_pk = math.sqrt(2.0) * Vin_min
    Pin = spec.Pout_W / spec.eta
    I_in_pk = math.sqrt(2.0) * Pin / Vin_min
    I_in_rms = Pin / Vin_min  # line-fundamental RMS (excludes ripple)
    fsw_Hz = spec.f_sw_kHz * 1000.0
    Tsw_us = 1e6 / fsw_Hz
    delta_I_target = (spec.ripple_pct / 100.0) * I_in_pk
    L_req_uH = result.L_required_uH
    L_actual_uH = result.L_actual_uH
    N = result.N_turns

    # Duty at sine-peak of low line: d(t) = 1 - Vin_pk·|sin|/Vout.
    D_at_peak = max(0.0, min(1.0, 1.0 - Vin_pk / spec.Vout_V))
    D_at_zero_cross = 1.0  # vin → 0, ripple → 0
    # Worst-case ripple: vin = Vout/2 → ΔI_pp_max = Vout / (4·L·fsw)
    delta_I_worst = spec.Vout_V / (4.0 * L_actual_uH * 1e-6 * fsw_Hz)

    # ── Magnetic ──
    # H at peak DC bias (Oe & A/m forms).
    H_pk_Oe = rf.H_from_NI(N, I_in_pk, core.le_mm, units="Oe")
    H_pk_Am = rf.H_from_NI(N, I_in_pk, core.le_mm, units="A/m")
    mu_pct = result.mu_pct_at_peak  # rolloff value (1.0 for ferrite)
    B_pk_mT = result.B_pk_T * 1000.0
    B_sat_25_mT = material.Bsat_25C_T * 1000.0
    B_sat_100_mT = material.Bsat_100C_T * 1000.0
    B_limit_mT = result.B_sat_limit_T * 1000.0
    sat_margin = result.sat_margin_pct
    gap_mm = result.gap_actual_mm or 0.0
    is_ferrite = material.rolloff is None

    # AL at the operating point (effective, after rolloff or gap).
    Ae_m2 = core.Ae_mm2 * 1e-6
    le_m = core.le_mm * 1e-3
    mu_r = max(float(getattr(material, "mu_initial", 0.0) or 1.0), 1.0)
    if is_ferrite and gap_mm > 0:
        l_eff_m = le_m / mu_r + gap_mm * 1e-3
        AL_eff_nH = (MU_0 * Ae_m2 / l_eff_m) * 1e9
    else:
        AL_eff_nH = core.AL_nH * mu_pct

    # ── Winding & resistance ──
    A_cu_total_mm2 = wire.A_cu_mm2 * (wire.n_strands or 1)
    Ku_actual = result.Ku_actual
    Ku_max = result.Ku_max
    MLT_mm = core.MLT_mm
    l_wire_m = N * MLT_mm * 1e-3
    T_w = result.T_winding_C
    rho_at_T = RHO_CU_20 * (1.0 + 0.00393 * (T_w - 20.0))
    R_dc_mOhm = result.R_dc_ohm * 1000.0
    R_ac_mOhm = result.R_ac_ohm * 1000.0
    F_R = (result.R_ac_ohm / result.R_dc_ohm) if result.R_dc_ohm > 0 else 1.0

    # Estimated layer count for the Dowell calc.
    layers = cp.estimate_layers(N, wire, core.Wa_mm2)

    # ── Losses ──
    L = result.losses
    I_rms_total = result.I_rms_total_A
    # Approximate ripple RMS (the engine stored it implicitly via wf).
    I_ripple_rms = math.sqrt(max(I_rms_total**2 - I_in_rms**2, 0.0))

    # Steinmetz line-band check (informational; engine output is the truth).
    s = material.steinmetz
    P_v_line_mW = cl.steinmetz_volumetric_mWcm3(material, spec.f_line_Hz / 1000.0, B_pk_mT)

    # ── Thermal ──
    A_surf_cm2 = th.surface_area_m2(core) * 1e4

    return dict(
        # Spec/operating-point
        Vin_min=_fmt(Vin_min, 1),
        Vin_pk=_fmt(Vin_pk, 1),
        Vout=_fmt(spec.Vout_V, 1),
        Pout=_fmt(spec.Pout_W, 0),
        Pin=_fmt(Pin, 1),
        eta=_fmt(spec.eta * 100.0, 1),
        fsw_kHz=_fmt(spec.f_sw_kHz, 1),
        Tsw_us=_fmt(Tsw_us, 2),
        fline=_fmt(spec.f_line_Hz, 0),
        ripple_pct=_fmt(spec.ripple_pct, 1),
        T_amb=_fmt(spec.T_amb_C, 1),
        T_max=_fmt(spec.T_max_C, 1),
        Ku_max_pct=_fmt(Ku_max * 100.0, 1),
        Bsat_margin_pct=_fmt(spec.Bsat_margin * 100.0, 1),
        I_in_pk=_fmt(I_in_pk, 2),
        I_in_rms=_fmt(I_in_rms, 2),
        I_rms_total=_fmt(I_rms_total, 2),
        I_pk_total=_fmt(result.I_pk_max_A, 2),
        I_ripple_rms=_fmt(I_ripple_rms, 3),
        delta_I_target=_fmt(delta_I_target, 2),
        delta_I_worst=_fmt(delta_I_worst, 2),
        D_at_peak=_fmt(D_at_peak * 100.0, 1),
        D_at_zero_cross=_fmt(D_at_zero_cross * 100.0, 0),
        # Inductor
        N=N,
        L_req=_fmt(L_req_uH, 0),
        L_actual=_fmt(L_actual_uH, 0),
        L_actual_mH=_fmt(L_actual_uH / 1000.0, 3),
        AL_nominal=_fmt(core.AL_nH, 0),
        AL_eff=_fmt(AL_eff_nH, 1),
        mu_pct=_fmt(mu_pct * 100.0, 1),
        mu_r=_fmt(mu_r, 0),
        # Geometry
        core_id=_esc(core.id),
        core_part=_esc(core.part_number),
        core_vendor=_esc(core.vendor),
        core_shape=_esc(core.shape),
        Ae_mm2=_fmt(core.Ae_mm2, 1),
        Ae_cm2=_fmt(core.Ae_mm2 / 100.0, 3),
        Wa_mm2=_fmt(core.Wa_mm2, 1),
        le_mm=_fmt(core.le_mm, 1),
        Ve_mm3=_fmt(core.Ve_mm3, 0),
        Ve_cm3=_fmt(core.Ve_mm3 / 1000.0, 2),
        MLT_mm=_fmt(MLT_mm, 1),
        OD_mm=_fmt(core.OD_mm) if core.OD_mm else "—",
        ID_mm=_fmt(core.ID_mm) if core.ID_mm else "—",
        HT_mm=_fmt(core.HT_mm) if core.HT_mm else "—",
        # Magnetic
        H_pk_Oe=_fmt(H_pk_Oe, 0),
        H_pk_Am=_fmt(H_pk_Am, 0),
        B_pk_mT=_fmt(B_pk_mT, 0),
        B_sat_25_mT=_fmt(B_sat_25_mT, 0),
        B_sat_100_mT=_fmt(B_sat_100_mT, 0),
        B_limit_mT=_fmt(B_limit_mT, 0),
        sat_margin_pct=_fmt(sat_margin, 1),
        gap_mm=_fmt(gap_mm, 3) if gap_mm > 0 else "—",
        gap_status=("calculado pelo engine" if gap_mm > 0 else "núcleo de pó (gap distribuído)"),
        # Material
        mat_id=_esc(material.id),
        mat_name=_esc(material.name),
        mat_vendor=_esc(material.vendor),
        is_ferrite=is_ferrite,
        steinmetz_alpha=_fmt(s.alpha, 3),
        steinmetz_beta=_fmt(s.beta, 3),
        steinmetz_Pv_ref=_fmt(s.Pv_ref_mWcm3, 1),
        steinmetz_f_ref=_fmt(s.f_ref_kHz, 0),
        steinmetz_B_ref=_fmt(s.B_ref_mT, 0),
        steinmetz_f_min=_fmt(s.f_min_kHz, 0),
        # Wire
        wire_id=_esc(wire.id),
        wire_type=_esc(wire.type),
        wire_awg=str(wire.awg) if wire.awg is not None else "—",
        wire_d_mm=_fmt(wire.outer_diameter_mm(), 3),
        wire_d_cu_mm=_fmt(wire.d_cu_mm, 3) if wire.d_cu_mm else "—",
        wire_A_cu_mm2=_fmt(wire.A_cu_mm2, 4),
        wire_n_strands=str(wire.n_strands) if wire.n_strands else "1",
        A_cu_total_mm2=_fmt(A_cu_total_mm2, 4),
        l_wire_m=_fmt(l_wire_m, 2),
        Ku_actual_pct=_fmt(Ku_actual * 100.0, 1),
        layers=layers,
        # Resistance
        rho_at_T=_fmt_sci(rho_at_T, 3),
        rho_20=_fmt_sci(RHO_CU_20, 3),
        R_dc_mOhm=_fmt(R_dc_mOhm, 1),
        R_ac_mOhm=_fmt(R_ac_mOhm, 1),
        F_R=_fmt(F_R, 3),
        # Losses
        P_cu_dc=_fmt(L.P_cu_dc_W, 3),
        P_cu_ac=_fmt(L.P_cu_ac_W, 3),
        P_cu_tot=_fmt(L.P_cu_total_W, 3),
        P_core_line=_fmt(L.P_core_line_W, 3),
        P_core_ripple=_fmt(L.P_core_ripple_W, 3),
        P_core_tot=_fmt(L.P_core_total_W, 3),
        P_total=_fmt(L.P_total_W, 2),
        eta_inductor=_fmt(
            (1.0 - L.P_total_W / max(spec.Pout_W, 1.0)) * 100.0, 3
        ),
        P_v_line_mW=_fmt(P_v_line_mW, 3),
        # Thermal
        T_winding=_fmt(T_w, 1),
        T_rise=_fmt(result.T_rise_C, 1),
        A_surf_cm2=_fmt(A_surf_cm2, 1),
        A_surf_m2=_fmt(A_surf_cm2 / 1e4, 5),
        h_conv=12,
        # Verification status
        ok_B="✓" if result.B_pk_T <= result.B_sat_limit_T else "✗",
        ok_Ku="✓" if result.Ku_actual <= result.Ku_max else "✗",
        ok_T="✓" if result.T_winding_C <= spec.T_max_C else "✗",
        feasible="VIÁVEL" if result.is_feasible() else "REVER",
        feasible_color="#2C7A3F" if result.is_feasible() else "#B8302B",
        # Warnings list (joined)
        warnings_block=_render_warnings(result.warnings),
        # Misc
        date_iso="",  # filled by caller
        designer="",
        revision="",
        project_id="",
        topology_label="",
    )


def _render_warnings(warnings: list[str]) -> str:
    if not warnings:
        return "Sem avisos. Design dentro de todas as margens do spec."
    bullets = "\n".join(f"  - {_esc(w)}" for w in warnings)
    return bullets


def _fmt(v: float | None, digits: int = 1) -> str:
    """Plain decimal — no thousands separator. Typst math parses
    spaces inside numbers as implicit multiplication, so ``2 138.7``
    becomes ``2 * 138.7``. Keep ``digits`` modest and the values fit
    on one line."""
    if v is None:
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{digits}f}"


def _fmt_sci(v: float, digits: int = 3) -> str:
    if not math.isfinite(v):
        return "—"
    s = f"{v:.{digits}e}"
    mantissa, exp = s.split("e")
    return f"{mantissa} × 10^({int(exp)})"


def _esc(s) -> str:
    """Minimal escaping for Typst's content blocks — backslash and
    quote are the two that bite in raw strings."""
    if s is None:
        return ""
    s = str(s)
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("#", "\\#")
        .replace("@", "\\@")
    )


# ---------------------------------------------------------------------------
# Master Typst template — covers boost-CCM end-to-end with every equation
# the engine evaluates. Placeholders are ``{name}`` style ``str.format``.
# Curly braces that are literally Typst syntax are doubled as ``{{`` / ``}}``.
# ---------------------------------------------------------------------------
_TEMPLATE = r"""
#set document(
  title: "Relatório de Projeto — Indutor PFC",
  author: "MagnaDesign",
)

#set page(
  paper: "a4",
  margin: (top: 22mm, bottom: 22mm, left: 20mm, right: 20mm),
  header: context {{
    if counter(page).get().first() > 1 [
      #set text(size: 8pt, fill: rgb("#777"))
      #grid(
        columns: (1fr, auto),
        align: (left, right),
        [MagnaDesign · Indutor PFC · {project_id}],
        [Rev. {revision} · {date_iso}],
      )
      #line(length: 100%, stroke: 0.4pt + rgb("#bbb"))
    ]
  }},
  footer: context [
    #set text(size: 8pt, fill: rgb("#777"))
    #grid(
      columns: (1fr, auto, 1fr),
      align: (left, center, right),
      [Confidencial — uso interno],
      [Pág. #counter(page).display() / #counter(page).final().first()],
      [{topology_label}],
    )
  ],
)

#set text(font: "New Computer Modern", size: 10.5pt, lang: "pt")
#set par(justify: true, leading: 0.65em, first-line-indent: 0pt)
#show heading.where(level: 1): it => [
  #set text(size: 18pt, weight: "bold", fill: rgb("#1a1a1a"))
  #v(6pt)
  #it.body
  #v(2pt)
  #line(length: 100%, stroke: 0.6pt + rgb("#1a1a1a"))
  #v(4pt)
]
#show heading.where(level: 2): it => [
  #set text(size: 13pt, weight: "bold", fill: rgb("#234"))
  #v(8pt) #it.body #v(2pt)
]
#show heading.where(level: 3): it => [
  #set text(size: 11pt, weight: "bold", fill: rgb("#345"))
  #v(4pt) #it.body
]
#show math.equation: set text(size: 10.5pt)
#set math.equation(numbering: none)
#show table.cell.where(y: 0): set text(weight: "bold")

// ────────────────────────────────────────────────────────────────────
// Cover
// ────────────────────────────────────────────────────────────────────
#v(2cm)
#align(center)[
  #text(size: 9pt, fill: rgb("#888"))[MagnaDesign · Engineering Report]
  #v(0.6cm)
  #text(size: 26pt, weight: "bold")[Projeto de indutor PFC]
  #v(0.2cm)
  #text(size: 13pt, fill: rgb("#345"))[{topology_label}]
  #v(2.5cm)

  #block(
    width: 12cm,
    inset: 12pt,
    stroke: 0.5pt + rgb("#cccccc"),
    radius: 4pt,
  )[
    #set align(left)
    #set text(size: 10pt)
    #grid(
      columns: (auto, 1fr),
      column-gutter: 1.2cm,
      row-gutter: 6pt,
      [*Projeto*], [{designer}],
      [*Identificador*], [`{project_id}`],
      [*Revisão*], [{revision}],
      [*Data*], [{date_iso}],
      [*Topologia*], [{topology_label}],
      [*Potência de saída*], [{Pout} W],
      [*Tensão de entrada*], [{Vin_min}--265 V#sub[rms]],
      [*Tensão de barramento*], [{Vout} V],
      [*Frequência de chaveamento*], [{fsw_kHz} kHz],
    )
  ]
  #v(1cm)
  #text(size: 9pt, fill: rgb("#555"))[
    Este documento descreve cada passo do dimensionamento — equação,
    valores substituídos e resultado — pra que o engenheiro possa
    auditar e reproduzir o cálculo. Toda a matemática mostrada aqui é
    a mesma que o engine MagnaDesign executou.
  ]
]
#pagebreak()

// ────────────────────────────────────────────────────────────────────
// 1. Spec
// ────────────────────────────────────────────────────────────────────
= 1. Especificação de entrada

A especificação fixada pelo usuário define a janela de operação
contra a qual o engine dimensiona o indutor. O caso de pior corrente
ocorre na tensão de entrada mínima ($V_(i n,m i n)$), e o caso de
pior ripple ocorre na tensão de saída sobre o indutor, em torno do
ponto $v_(i n)(t) = V_(o u t)/2$.

#table(
  columns: (auto, 1fr, auto),
  align: (left, left, right),
  stroke: (x, y) => if y == 0 {{
    (bottom: 0.7pt)
  }} else {{
    (bottom: 0.2pt + rgb("#ddd"))
  }},
  inset: (x: 6pt, y: 5pt),
  table.header[Variável][Descrição][Valor],
  [$V_(i n,m i n)$], [Tensão AC mínima (worst case corrente)], [{Vin_min} V#sub[rms]],
  [$V_(o u t)$], [Tensão de barramento DC], [{Vout} V],
  [$P_(o u t)$], [Potência de saída], [{Pout} W],
  [$eta$], [Eficiência assumida], [{eta} %],
  [$f_(s w)$], [Frequência de chaveamento], [{fsw_kHz} kHz],
  [$f_(l i n e)$], [Frequência da rede], [{fline} Hz],
  [$Delta I_(r i p)$], [Ripple alvo (% do pico de linha)], [{ripple_pct} %],
  [$T_(a m b)$], [Temperatura ambiente], [{T_amb} °C],
  [$T_(m a x)$], [Temperatura máx. do enrolamento], [{T_max} °C],
  [$K_(u,m a x)$], [Preenchimento máximo da janela], [{Ku_max_pct} %],
  [margem $B_(s a t)$], [Margem aplicada sobre $B_(s a t)$], [{Bsat_margin_pct} %],
)

== 1.1. Ponto de operação no pior caso

A corrente de entrada do PFC é forçada a seguir a forma de onda da
tensão de entrada (lei do controle PFC), produzindo um envelope
retificado de meia onda na frequência da rede com ripple de
chaveamento sobreposto.

$ I_(i n,p k) = sqrt(2) dot P_(i n)/V_(i n,m i n) = sqrt(2) dot ({Pout}/({eta}\\% dot {Vin_min}\\,V)) = {I_in_pk} thin "A" $

$ I_(i n,r m s) = P_(i n)/V_(i n,m i n) = {Pout}/({eta}\\% dot {Vin_min}\\,V) = {I_in_rms} thin "A" $

$ V_(i n,p k) = sqrt(2) dot V_(i n,m i n) = sqrt(2) dot {Vin_min}\\,V = {Vin_pk} thin "V" $

O ciclo de trabalho varia ao longo do semiciclo: $d(t) = 1 - V_(i n,p k)\\,|sin omega t|/V_(o u t)$.
No pico da senóide: $d_(p k) = 1 - V_(i n,p k)/V_(o u t) = {D_at_peak}\\,%$.
No cruzamento por zero: $d arrow 100\\,%$.

// ────────────────────────────────────────────────────────────────────
// 2. Indutância requerida
// ────────────────────────────────────────────────────────────────────
= 2. Indutância requerida

O ripple pico-a-pico do indutor varia ao longo do ciclo de rede e
atinge seu máximo quando $v_(i n)(t) = V_(o u t)/2$
(Erickson & Maksimovic, Cap. 18):

$ Delta i_(L,p p,m a x) = V_(o u t)/(4 dot L dot f_(s w)) $

Para limitar esse pico a uma fração $Delta I_(r i p)/100$ do pico de
linha $I_(i n,p k)$, isolamos $L$:

$ L_(min) = V_(o u t)/(4 dot f_(s w) dot Delta I_(r i p,A)) = {Vout}/(4 dot {fsw_kHz}\\,"kHz" dot {delta_I_target}\\,"A") = {L_req} thin mu"H" $

onde $Delta I_(r i p,A) = (Delta I_(r i p)\\,%) dot I_(i n,p k) = {delta_I_target}\\,"A"$ é o ripple alvo.

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Resultado:* $L_(min) = {L_req} thin mu"H"$
  — indutância mínima que o engine usa como alvo do solver.
  Ripple pico-a-pico atendido: $Delta i_(L,p p,m a x) = {delta_I_worst}\\,"A"$ no pior caso.
]

// ────────────────────────────────────────────────────────────────────
// 3. Núcleo + material escolhidos
// ────────────────────────────────────────────────────────────────────
= 3. Componentes selecionados

== 3.1. Núcleo

#table(
  columns: (auto, 1fr),
  align: (left, left),
  stroke: (x, y) => if y == 0 {{ (bottom: 0.7pt) }} else {{ (bottom: 0.2pt + rgb("#ddd")) }},
  inset: (x: 6pt, y: 4pt),
  table.header[Parâmetro][Valor],
  [Identificador], [`{core_id}`],
  [Fornecedor / part-number], [{core_vendor} / {core_part}],
  [Formato], [{core_shape}],
  [$A_e$ — área magnética], [{Ae_mm2} mm² = {Ae_cm2} cm²],
  [$W_a$ — janela], [{Wa_mm2} mm²],
  [$l_e$ — caminho magnético], [{le_mm} mm],
  [$V_e$ — volume efetivo], [{Ve_mm3} mm³ = {Ve_cm3} cm³],
  [MLT — comprimento médio por volta], [{MLT_mm} mm],
  [$A_L$ nominal (do catálogo)], [{AL_nominal} nH/N²],
  [Dimensões externas (toroide)], [OD = {OD_mm} mm · ID = {ID_mm} mm · HT = {HT_mm} mm],
)

== 3.2. Material magnético

#table(
  columns: (auto, 1fr),
  align: (left, left),
  stroke: (x, y) => if y == 0 {{ (bottom: 0.7pt) }} else {{ (bottom: 0.2pt + rgb("#ddd")) }},
  inset: (x: 6pt, y: 4pt),
  table.header[Parâmetro][Valor],
  [Identificador / fornecedor], [`{mat_id}` · {mat_vendor}],
  [Família], [{mat_name}],
  [Permeabilidade inicial $mu_r$], [{mu_r}],
  [$B_(s a t)$ a 25 °C], [{B_sat_25_mT} mT],
  [$B_(s a t)$ a 100 °C], [{B_sat_100_mT} mT],
  [Steinmetz $alpha$], [{steinmetz_alpha}],
  [Steinmetz $beta$], [{steinmetz_beta}],
  [Steinmetz $P_(v,r e f)$ \@ ($f_(r e f)$, $B_(r e f)$)], [{steinmetz_Pv_ref} mW/cm³ \@ ({steinmetz_f_ref} kHz, {steinmetz_B_ref} mT)],
  [$f_(m i n)$ válida do modelo de perdas], [{steinmetz_f_min} kHz],
)

== 3.3. Fio

#table(
  columns: (auto, 1fr),
  align: (left, left),
  stroke: (x, y) => if y == 0 {{ (bottom: 0.7pt) }} else {{ (bottom: 0.2pt + rgb("#ddd")) }},
  inset: (x: 6pt, y: 4pt),
  table.header[Parâmetro][Valor],
  [Identificador / tipo], [`{wire_id}` · {wire_type}],
  [AWG], [{wire_awg}],
  [Diâmetro externo (com isolação)], [{wire_d_mm} mm],
  [Diâmetro do cobre], [{wire_d_cu_mm} mm],
  [Área de cobre (por condutor)], [{wire_A_cu_mm2} mm²],
  [Fios em paralelo (litz / strands)], [{wire_n_strands}],
  [Área total de cobre], [{A_cu_total_mm2} mm²],
)

// ────────────────────────────────────────────────────────────────────
// 4. Solução do número de voltas + entreferro
// ────────────────────────────────────────────────────────────────────
= 4. Voltas, $A_L$ efetivo e entreferro

A indutância de um indutor enrolado em núcleo magnético é
$L = N² dot A_L$, onde $A_L$ depende do material e do estado de
saturação. O engine resolve em duas trilhas distintas dependendo do
tipo do material:

== 4.1. Resolução do entreferro

A escolha do núcleo influencia o cálculo: núcleos de pó (Magnetics
Kool-Mu, High-Flux, Sendust) têm gap distribuído implícito no
material — $A_L$ catálogo é o efetivo e a saturação é tratada via
curva de roll-off $mu(H)$. Núcleos de ferrite ($mu_r$ alto, sem
roll-off) precisam de um entreferro explícito calculado a partir do
balanço de energia magnética.

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Status do gap:* {gap_status}. \
  *Valor utilizado:* $l_(g a p) = {gap_mm}$ mm.
]

Para o caso ferrite (com $mu_r approx {mu_r}$), o engine impõe a
restrição de saturação:

$ N_(min,s a t) = ceil((L dot I_(p k))/(B_(s a t)^* dot A_e)) $

onde $B_(s a t)^* = B_(s a t)(100\\,°"C") dot (1 - "margem") = {B_limit_mT}$ mT.
Substituindo:

$ N_(min,s a t) = ceil(({L_actual}\\,mu"H" dot {I_in_pk}\\,"A")/({B_limit_mT}\\,"mT" dot {Ae_mm2}\\,"mm"^2)) approx {N} thick "voltas" $

Com $N$ definido, o entreferro fica:

$ l_(g a p) = (N^2 dot mu_0 dot A_e)/L - l_e/mu_r $

E o $A_L$ efetivo é:

$ A_L^("eff") = (mu_0 dot A_e)/(l_e/mu_r + l_(g a p)) = {AL_eff} thin "nH"\\/N^2 $

== 4.2. Indutância resultante

$ L_("real") = N² dot A_L^("eff") dot mu(H) = {N}^2 dot {AL_eff}\\,"nH" dot {mu_pct}\\,% = {L_actual} thin mu"H" $

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Resultado:* $N = {N}$ voltas · $L_("real") = {L_actual} thin mu"H"$
  ({L_actual_mH} mH) vs. requerido $L_(m i n) = {L_req}$ µH.
]

// ────────────────────────────────────────────────────────────────────
// 5. Fluxo magnético e saturação
// ────────────────────────────────────────────────────────────────────
= 5. Densidade de fluxo e saturação

O campo $H$ no pico de corrente de linha:

$ H_(p k) = (N dot I_(i n,p k))/l_e = ({N} dot {I_in_pk}\\,"A")/{le_mm}\\,"mm" = {H_pk_Am} thin "A/m" = {H_pk_Oe} thin "Oe" $

A densidade de fluxo magnético no núcleo no pico da onda:

$ B_(p k) = (L dot I_(i n,p k))/(N dot A_e) = ({L_actual_mH}\\,"mH" dot {I_in_pk}\\,"A")/({N} dot {Ae_mm2}\\,"mm"^2) = {B_pk_mT} thin "mT" $

Comparando com a margem de saturação:

#table(
  columns: (auto, 1fr, auto, auto),
  align: (left, left, right, center),
  stroke: (x, y) => if y == 0 {{ (bottom: 0.7pt) }} else {{ (bottom: 0.2pt + rgb("#ddd")) }},
  inset: (x: 6pt, y: 4pt),
  table.header[Métrica][Definição][Valor][Status],
  [$B_(p k)$], [Pico de fluxo computado], [{B_pk_mT} mT], [—],
  [$B_(s a t)^*$], [Limite = $B_(s a t)(100\\,°"C") dot (1 - "margem")$], [{B_limit_mT} mT], [—],
  [Margem], [$(B_(s a t)^* - B_(p k))/B_(s a t)^*$], [{sat_margin_pct} %], [{ok_B}],
)

// ────────────────────────────────────────────────────────────────────
// 6. Preenchimento de janela
// ────────────────────────────────────────────────────────────────────
= 6. Janela e fabricabilidade

A área total de cobre ocupada pelo enrolamento:

$ A_("cobre,tot") = N dot A_("cu,fio") dot n_("strands") = {N} dot {wire_A_cu_mm2}\\,"mm"^2 dot {wire_n_strands} = {A_cu_total_mm2} thin "mm"^2 $

O preenchimento da janela:

$ K_u = A_("cobre,tot") / W_a = {A_cu_total_mm2}\\,"mm"^2 / {Wa_mm2}\\,"mm"^2 = {Ku_actual_pct}\\,% $

#table(
  columns: (auto, 1fr, auto, auto),
  align: (left, left, right, center),
  stroke: (x, y) => if y == 0 {{ (bottom: 0.7pt) }} else {{ (bottom: 0.2pt + rgb("#ddd")) }},
  inset: (x: 6pt, y: 4pt),
  table.header[Métrica][Definição][Valor][Status],
  [$K_u$], [Preenchimento atual], [{Ku_actual_pct} %], [{ok_Ku}],
  [$K_(u,m a x)$], [Limite (spec)], [{Ku_max_pct} %], [—],
  [Camadas estimadas], [Pra cálculo Dowell], [{layers}], [—],
  [Comprimento total de fio], [$l_("fio") = N dot "MLT"$], [{l_wire_m} m], [—],
)

// ────────────────────────────────────────────────────────────────────
// 7. Resistência DC + AC
// ────────────────────────────────────────────────────────────────────
= 7. Resistência e perdas no cobre

== 7.1. Resistência DC

A resistividade do cobre cresce com a temperatura segundo o
coeficiente $alpha_(C u) = 3,93 dot 10^(-3)$/°C:

$ rho_(C u)(T) = rho_(C u,20) dot (1 + alpha_(C u) dot (T - 20)) $

Avaliada em $T = T_("enrolamento") = {T_winding}$ °C:

$ rho_(C u)({T_winding}\\,°"C") = {rho_20}\\,Omega dot "m" dot (1 + 0{{,}}00393 dot ({T_winding} - 20)) = {rho_at_T}\\,Omega dot "m" $

$ R_("dc") = (rho_(C u) dot N dot "MLT")/A_("cu,fio") = ({rho_at_T}\\,Omega"·m" dot {N} dot {MLT_mm}\\,"mm")/{wire_A_cu_mm2}\\,"mm"^2 = {R_dc_mOhm} thin "mΩ" $

== 7.2. Resistência AC (Dowell)

Em $f_(s w) = {fsw_kHz}$ kHz, o efeito pelicular e a proximidade
entre voltas elevam $R_("ac")$ acima de $R_("dc")$. O fator de
correção $F_R$ vem do modelo de Dowell para condutor redondo
(ou Litz, quando aplicável) com a contagem de camadas estimada.

$ R_("ac") = R_("dc") dot F_R("camadas"={layers}, f={fsw_kHz}\\,"kHz", T={T_winding}\\,°"C") $

$ F_R = {F_R} arrow.r R_("ac") = {R_ac_mOhm} thin "mΩ" $

== 7.3. Perdas no cobre

$ P_(C u,d c) = I_("rms,linha")^2 dot R_("dc") = ({I_in_rms}\\,"A")^2 dot {R_dc_mOhm}\\,"mΩ" = {P_cu_dc} thin "W" $

$ P_(C u,a c) = I_("rms,ripple")^2 dot R_("ac") = ({I_ripple_rms}\\,"A")^2 dot {R_ac_mOhm}\\,"mΩ" = {P_cu_ac} thin "W" $

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Total no cobre:* $P_("cobre") = P_(C u,d c) + P_(C u,a c) = {P_cu_tot}$ W
]

// ────────────────────────────────────────────────────────────────────
// 8. Perdas no núcleo
// ────────────────────────────────────────────────────────────────────
= 8. Perdas no núcleo

O modelo de Steinmetz parametriza a perda volumétrica em função da
frequência e da amplitude de fluxo:

$ P_v thin ["mW"\/"cm"^3] = P_(v,r e f) dot (f/f_(r e f))^alpha dot (B/B_(r e f))^beta $

Os coeficientes deste material (do catálogo):
$alpha = {steinmetz_alpha}$,
$beta = {steinmetz_beta}$,
$P_(v,r e f) = {steinmetz_Pv_ref}$ mW/cm³ \@
$(f_(r e f) = {steinmetz_f_ref}$ kHz,
$B_(r e f) = {steinmetz_B_ref}$ mT$)$.

== 8.1. Banda de linha (envelope $2 dot f_("rede")$)

$ P_("núcleo,linha") = P_v(f_("rede"), B_(p k)) dot V_e = {P_core_line} thin "W" $

Quando $f_("rede") < f_(min) = {steinmetz_f_min}$ kHz o modelo é
extrapolado e o engine zera a banda (evita previsão fora da faixa
calibrada).

== 8.2. Banda de chaveamento (iGSE em $Delta B_(p p)(t)$)

A onda triangular em $f_(s w)$ tem amplitude $Delta B_(p p)$ que
varia ao longo do semiciclo de rede. O engine aplica iGSE
(Mühlethaler 2012) sobre o array $Delta B_(p p)(t)$ pra capturar o
efeito não-linear $lr(angle.l B^beta angle.r) >> lr(angle.l B angle.r)^beta$ característico de PFC:

$ P_("núcleo,ripple") = lr(angle.l P_v(f_(s w), Delta B_(p p)(t)\/2) angle.r) dot V_e = {P_core_ripple} thin "W" $

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Total no núcleo:* $P_("núcleo") = P_("linha") + P_("ripple") = {P_core_tot}$ W
]

// ────────────────────────────────────────────────────────────────────
// 9. Balanço térmico
// ────────────────────────────────────────────────────────────────────
= 9. Balanço térmico

O modelo lumped é convecção natural mais radiação, com coeficiente
combinado $h = {h_conv}$ W/m²/K. A área de superfície do indutor
montado:

$ A_("surf") = pi dot O D dot H T + pi dot I D dot H T + 2 dot pi/4 dot (O D^2 - I D^2) = {A_surf_cm2} thin "cm"^2 $

O salto de temperatura é resolvido iterativamente porque $rho_(C u)(T)$
realimenta a perda no cobre:

$ Delta T = (P_("total")(T))/(h dot A_("surf")) thick arrow.r thick T = T_("amb") + Delta T $

Convergência (3-6 iterações típicas):

#table(
  columns: (auto, 1fr, auto),
  align: (left, left, right),
  stroke: (x, y) => if y == 0 {{ (bottom: 0.7pt) }} else {{ (bottom: 0.2pt + rgb("#ddd")) }},
  inset: (x: 6pt, y: 4pt),
  table.header[Métrica][Definição][Valor],
  [$T_("amb")$], [Temperatura ambiente], [{T_amb} °C],
  [$Delta T$], [Subida sobre o ambiente], [{T_rise} K],
  [$T_("enrolamento")$], [Temperatura do enrolamento], [*{T_winding} °C*],
  [$T_("max")$], [Limite do spec], [{T_max} °C],
)

// ────────────────────────────────────────────────────────────────────
// 10. Resumo
// ────────────────────────────────────────────────────────────────────
#pagebreak()
= 10. Resumo do projeto

#block(
  width: 100%,
  inset: 14pt,
  radius: 4pt,
  fill: rgb("#fafbfc"),
  stroke: 0.5pt + rgb("#dee"),
)[
  #set text(size: 11pt)
  *Status global:* #text(fill: rgb("{feasible_color}"), weight: "bold")[{feasible}]

  #v(8pt)
  #grid(
    columns: (1fr, 1fr),
    column-gutter: 1cm,
    row-gutter: 8pt,
    [
      *Magnético*
      - $N$ = {N} voltas
      - $L$ = {L_actual} µH
      - $B_(p k)$ = {B_pk_mT} mT
      - $l_(g a p)$ = {gap_mm} mm
      - $K_u$ = {Ku_actual_pct} %
    ],
    [
      *Térmico + perdas*
      - $T_("enrolamento")$ = {T_winding} °C ($Delta T$ = {T_rise} K)
      - $P_("cobre")$ = {P_cu_tot} W
      - $P_("núcleo")$ = {P_core_tot} W
      - $P_("total")$ = *{P_total} W*
      - $eta_("indutor")$ = {eta_inductor} %
    ],
  )
]

#v(12pt)
== Verificações

#table(
  columns: (auto, 1fr, auto, auto),
  align: (left, left, right, center),
  stroke: (x, y) => if y == 0 {{ (bottom: 0.7pt) }} else {{ (bottom: 0.2pt + rgb("#ddd")) }},
  inset: (x: 6pt, y: 4pt),
  table.header[Critério][Regra][Atingido][Status],
  [Saturação], [$B_(p k) lt.eq B_(s a t)^*$], [{B_pk_mT} mT $lt.eq$ {B_limit_mT} mT], [{ok_B}],
  [Janela], [$K_u lt.eq K_(u,m a x)$], [{Ku_actual_pct} % $lt.eq$ {Ku_max_pct} %], [{ok_Ku}],
  [Térmico], [$T_("enrolamento") lt.eq T_("max")$], [{T_winding} °C $lt.eq$ {T_max} °C], [{ok_T}],
)

== Avisos do engine

#block(inset: (left: 4pt))[
{warnings_block}
]

#v(0.6cm)
#align(right)[
  #set text(size: 8pt, fill: rgb("#888"))
  Gerado por MagnaDesign em {date_iso} · projeto `{project_id}` · revisão {revision}
]
"""
