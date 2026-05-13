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
    figures = _render_figures(spec, result)
    typst_source = _render_template(
        spec=spec,
        core=core,
        material=material,
        wire=wire,
        result=result,
        designer=designer,
        revision=revision,
        project_id=project_id or _hash_project_id(spec, core, material),
        available_figures=set(figures.keys()),
    )
    return compile_to_pdf(typst_source, output_path, extra_files=figures)


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
    available_figures: set[str] = frozenset(),
) -> str:
    ctx = _compute_context(spec, core, material, wire, result)
    # Per-topology operating-point + required-inductance derivation
    # gets rendered separately and injected at the {topology_body}
    # placeholder. The rest of the template (components, gap,
    # flux, window, losses, thermal, summary) is common to every
    # topology because it operates on the engine's universal
    # outputs (N, B_pk, Ku, R_dc/ac, P_*, T_winding).
    ctx["topology_body"] = _render_topology_body(spec, ctx)
    ctx["figures_block"] = _render_figures_block(available_figures)
    ctx["spec_table"] = _render_spec_table(spec, ctx)
    ctx["cover_summary"] = _render_cover_summary(spec, ctx)
    ctx.update(
        designer=_esc(designer),
        revision=_esc(revision),
        project_id=_esc(project_id),
        date_iso=datetime.now().strftime("%Y-%m-%d"),
        topology_label=_esc(_topology_label(spec.topology)),
        spec=spec,
    )
    return _TEMPLATE.format(**ctx)


def _render_cover_summary(spec: Spec, ctx: dict) -> str:
    """Return the Typst markup for the cover page summary grid."""
    
    # Common fields for all topologies
    fields = {
        "designer": ('*Designer*', '{designer}'),
        "project_id": ('*Identifier*', '`{project_id}`'),
        "revision": ('*Revision*', '{revision}'),
        "date_iso": ('*Date*', '{date_iso}'),
        "topology_label": ('*Topology*', '{topology_label}'),
        "Pout_W": ('*Output power*', '{Pout} W'),
    }

    if spec.topology == "boost_ccm":
        fields.update({
            "Vin_min_Vrms": ('*Input voltage*', '{Vin_min}–265 V#sub[rms]'),
            "Vout_V": ('*Bus voltage*', '{Vout} V'),
            "f_sw_kHz": ('*Switching frequency*', '{fsw_kHz} kHz'),
        })
    elif spec.topology == "passive_choke":
        fields.update({
            "Vin_min_Vrms": ('*Input voltage*', '{Vin_min} V#sub[rms]'),
        })
    elif spec.topology == "line_reactor":
        fields.update({
            "Vin_nom_Vrms": ('*Input voltage*', '{Vin_nom_Vrms} V#sub[rms]'),
            "I_rated_Arms": ('*Rated current*', '{I_rated_Arms} A'),
        })
    elif spec.topology == "buck_ccm":
        fields.update({
            "Vin_dc_V": ('*Input voltage*', '{Vin_dc_V} V'),
            "Vout_V": ('*Bus voltage*', '{Vout} V'),
            "f_sw_kHz": ('*Switching frequency*', '{fsw_kHz} kHz'),
        })
    elif spec.topology == "interleaved_boost_pfc":
        fields.update({
            "Vin_min_Vrms": ('*Input voltage*', '{Vin_min}–265 V#sub[rms]'),
            "Vout_V": ('*Bus voltage*', '{Vout} V'),
            "f_sw_kHz": ('*Switching frequency*', '{fsw_kHz} kHz'),
        })
    elif spec.topology == "flyback":
        fields.update({
            "Vin_dc_V": ('*Input voltage*', '{Vin_dc_V} V'),
            "Vout_V": ('*Bus voltage*', '{Vout} V'),
            "f_sw_kHz": ('*Switching frequency*', '{fsw_kHz} kHz'),
        })

    grid_rows = []
    for key, (label, value_template) in fields.items():
        try:
            value = value_template.format(**ctx)
        except KeyError:
            spec_val = getattr(spec, key, '—')
            value = str(spec_val) if spec_val is not None else '—'
        grid_rows.append(f'      {label}, [{value}],')

    grid_markup = f"""
    #grid(
      columns: (auto, 1fr),
      column-gutter: 1.2cm,
      row-gutter: 6pt,
{chr(10).join(grid_rows)}
    )
"""
    return grid_markup

def _render_spec_table(spec: Spec, ctx: dict) -> str:
    """Return the Typst markup for the input specification table."""
    
    # Common fields for all topologies
    fields = {
        "Pout_W": ('$P_(out)$', "Output power", '{Pout} W'),
        "eta": ('$eta$', "Assumed efficiency", '{eta} %'),
        "T_amb_C": ('$T_(amb)$', "Ambient temperature", '{T_amb} °C'),
        "T_max_C": ('$T_(max)$', "Max. winding temperature", '{T_max} °C'),
        "Ku_max": ('$K_(u,max)$', "Maximum window fill factor", '{Ku_max_pct} %'),
        "Bsat_margin": ('$B_(sat)$ margin', "Margin applied to $B_(sat)$", '{Bsat_margin_pct} %'),
    }

    if spec.topology == "boost_ccm":
        fields.update({
            "Vin_min_Vrms": ('$V_(in,min)$', "Minimum AC voltage (worst-case current)", '{Vin_min} V#sub[rms]'),
            "Vout_V": ('$V_(out)$', "DC bus voltage", '{Vout} V'),
            "f_sw_kHz": ('$f_(sw)$', "Switching frequency", '{fsw_kHz} kHz'),
            "f_line_Hz": ('$f_(line)$', "Line frequency", '{fline} Hz'),
            "ripple_pct": ('$Delta I_(rip)$', "Target ripple (% of line peak)", '{ripple_pct} %'),
        })
    elif spec.topology == "passive_choke":
        fields.update({
            "Vin_min_Vrms": ('$V_(in,min)$', "Minimum AC voltage", '{Vin_min} V#sub[rms]'),
            "f_line_Hz": ('$f_(line)$', "Line frequency", '{fline} Hz'),
        })
    elif spec.topology == "line_reactor":
        fields.update({
            "Vin_nom_Vrms": ('$V_(in,nom)$', "Nominal AC voltage", '{Vin_nom_Vrms} V#sub[rms]'),
            "I_rated_Arms": ('$I_(rated)$', "Rated RMS current", '{I_rated_Arms} A'),
            "f_line_Hz": ('$f_(line)$', "Line frequency", '{fline} Hz'),
            "n_phases": ('$n_(phases)$', "Number of phases", '{n_phases}'),
            "L_req_mH": ('$L_(req)$', "Required inductance", '{L_req_mH} mH'),
        })
    elif spec.topology == "buck_ccm":
        fields.update({
            "Vin_dc_V": ('$V_(in,dc)$', "DC input voltage", '{Vin_dc_V} V'),
            "Vout_V": ('$V_(out)$', "DC bus voltage", '{Vout} V'),
            "f_sw_kHz": ('$f_(sw)$', "Switching frequency", '{fsw_kHz} kHz'),
            "ripple_ratio": ('$r$', "Ripple ratio (ΔI/Iout)", '{ripple_ratio}'),
        })
    elif spec.topology == "interleaved_boost_pfc":
        fields.update({
            "Vin_min_Vrms": ('$V_(in,min)$', "Minimum AC voltage (worst-case current)", '{Vin_min} V#sub[rms]'),
            "Vout_V": ('$V_(out)$', "DC bus voltage", '{Vout} V'),
            "f_sw_kHz": ('$f_(sw)$', "Switching frequency", '{fsw_kHz} kHz'),
            "f_line_Hz": ('$f_(line)$', "Line frequency", '{fline} Hz'),
            "ripple_pct": ('$Delta I_(rip)$', "Target ripple (% of line peak)", '{ripple_pct} %'),
            "n_interleave": ('$n_(interleave)$', "Number of interleaved phases", '{n_interleave}'),
        })
    elif spec.topology == "flyback":
        fields.update({
            "Vin_dc_V": ('$V_(in,dc)$', "DC input voltage", '{Vin_dc_V} V'),
            "Vout_V": ('$V_(out)$', "DC bus voltage", '{Vout} V'),
            "f_sw_kHz": ('$f_(sw)$', "Switching frequency", '{fsw_kHz} kHz'),
            "flyback_mode": ('mode', "Flyback mode", '{flyback_mode}'),
            "turns_ratio_n": ('n', "Turns ratio (Np/Ns)", '{turns_ratio_n}'),
        })
    
    table_rows = [
        "table.header[Variable][Description][Value]"
    ]
    
    for key, (symbol, desc, value_template) in fields.items():
        # Format the value from the context, falling back to the spec attribute
        try:
            value = value_template.format(**ctx)
        except KeyError:
            # Fallback for fields not in context dict, e.g. from the spec itself
            spec_val = getattr(spec, key, '—')
            value = str(spec_val) if spec_val is not None else '—'

        table_rows.append(f'  [{symbol}], [{desc}], [{value}],')

    table_markup = f"""
#table(
  columns: (auto, 1fr, auto),
  align: (left, left, right),
  stroke: (x, y) => if y == 0 {{{{
    (bottom: 0.7pt)
  }}}} else {{{{
    (bottom: 0.2pt + rgb("#ddd"))
  }}}},
  inset: (x: 6pt, y: 5pt),
{chr(10).join(table_rows)}
)
"""
    return table_markup

def _topology_label(t: str) -> str:
    return {
        "boost_ccm": "Boost-PFC CCM (active)",
        "interleaved_boost_pfc": "Interleaved boost-PFC CCM (active)",
        "passive_choke": "Passive PFC choke",
        "line_reactor": "Line reactor (1φ / 3φ)",
        "buck_ccm": "Buck CCM (DC-DC step-down)",
        "flyback": "Flyback (isolated DC-DC)",
    }.get(t, t)


# ---------------------------------------------------------------------------
# Per-topology body — sections 1.1 (operating point) + 2 (L derivation).
# Each function returns a Typst markup string with values substituted
# inline via f-string. The result is concatenated into the master
# template AFTER ``str.format`` runs on the rest, so any literal
# curly braces in Typst syntax (``#if x {{ ... }}``) need no escaping
# at this stage. Bodies stay deliberately free of ``{`` characters
# beyond the f-string substitutions to avoid format collisions
# during the wrapping step.
# ---------------------------------------------------------------------------


def _render_topology_body(spec: Spec, ctx: dict) -> str:
    """Dispatch to the per-topology body renderer."""
    t = spec.topology
    if t == "boost_ccm":
        return _body_boost_ccm(spec, ctx)
    if t == "interleaved_boost_pfc":
        return _body_interleaved_boost_pfc(spec, ctx)
    if t == "buck_ccm":
        return _body_buck_ccm(spec, ctx)
    if t == "flyback":
        return _body_flyback(spec, ctx)
    if t == "line_reactor":
        return _body_line_reactor(spec, ctx)
    if t == "passive_choke":
        return _body_passive_choke(spec, ctx)
    return _body_generic(spec, ctx)


def _body_boost_ccm(spec: Spec, ctx: dict) -> str:
    return rf"""== 1.1. Worst-case operating point

The PFC input current is forced to follow the input voltage waveform
(PFC control law), producing a half-wave rectified envelope at the
line frequency with switching ripple superimposed. The worst-case
current is at $V_(in,min)$ and the worst-case ripple is where
$v_(in)(t) = V_(out)/2$.

$ I_(in,pk) = sqrt(2) dot P_(in)/V_(in,min) = sqrt(2) dot {ctx["Pout"]}/({ctx["eta"]}% dot {ctx["Vin_min"]}) = {ctx["I_in_pk"]} thin "A" $

$ I_(in,rms) = P_(in)/V_(in,min) = {ctx["Pout"]}/({ctx["eta"]}% dot {ctx["Vin_min"]}) = {ctx["I_in_rms"]} thin "A" $

$ V_(in,pk) = sqrt(2) dot V_(in,min) = sqrt(2) dot {ctx["Vin_min"]} = {ctx["Vin_pk"]} thin "V" $

The duty cycle varies throughout the half-cycle:
$d(t) = 1 - V_(in,pk) abs(sin omega t)/V_(out)$. At the sine peak
$d_(pk) = 1 - V_(in,pk)/V_(out) = {ctx["D_at_peak"]}$%. At zero crossing $d arrow 100$%.

= 2. Required inductance

The inductor's peak-to-peak ripple varies throughout the line cycle
and reaches its maximum when $v_(in)(t) = V_(out)/2$
(Erickson & Maksimovic, Ch. 18):

$ Delta i_(L,pp,max) = V_(out)/(4 dot L dot f_(sw)) $

To limit this peak to a fraction $Delta I_(rip)/100$ of the line
peak $I_(in,pk)$, we isolate $L$:

$ L_(min) = V_(out)/(4 dot f_(sw) dot Delta I_(rip,A)) = {ctx["Vout"]}/(4 dot {ctx["fsw_kHz"]} thin "kHz" dot {ctx["delta_I_target"]} thin "A") = {ctx["L_req"]} thin mu"H" $

where $Delta I_(rip,A) = (Delta I_(rip) \%) dot I_(in,pk) = {ctx["delta_I_target"]} thin "A"$ is the target ripple.

#block(fill: rgb("#f6f9fc"), inset: 10pt, radius: 3pt)[
  *Result:* $L_(min) = {ctx["L_req"]} thin mu"H"$ — minimum inductance
  the engine uses as a solver target. Peak-to-peak ripple met:
  $Delta i_(L,pp,max) = {ctx["delta_I_worst"]} thin "A"$ in the worst case.
]
"""


def _body_interleaved_boost_pfc(spec: Spec, ctx: dict) -> str:
    """Per-phase boost CCM with the Hwu-Yau interleaved badge.

    The engine routes each phase through ``boost_ccm.design`` with
    ``Pout = Total/N``; the report mirrors that, plus a note on the
    aggregate input ripple cancellation that justifies the topology.
    """
    n_phase = getattr(spec, "n_interleave", 2)
    return rf"""== 1.1. Operating point (per phase, $N$ = {n_phase})

The converter is composed of {n_phase} parallel boost-CCM stages
switched with a phase shift of $360°\/{n_phase} = {360 / n_phase:.0f}°$.
Each phase is sized as an independent boost CCM with
$P_("out,phase") = P_("out,total")\/N = {ctx["Pout"]} thin "W"\/{n_phase}$.
The aggregate input ripple cancels at points $D in {{{{1\/N, 2\/N, dots,
(N - 1)\/N}}}}$ by Hwu-Yau analysis, appearing at $N dot f_(sw)$
in the residual EMI filter.

$ P_("out,phase") = P_("out")\/N = {ctx["Pout"]}\/{n_phase} = {float(ctx["Pout"]) / n_phase:.0f} thin "W" $

$ I_(in,pk,"phase") = sqrt(2) dot P_("out,phase")/(eta dot V_(in,min)) = {ctx["I_in_pk"]} thin "A" $

= 2. Required inductance (per phase)

Each phase follows Erickson Ch. 18 for boost CCM with maximum ripple at
$v_(in) = V_(out)/2$:

$ L_(min) = V_(out)/(4 dot f_(sw) dot Delta I_(rip,A)) = {ctx["Vout"]}/(4 dot {ctx["fsw_kHz"]} thin "kHz" dot {ctx["delta_I_target"]} thin "A") = {ctx["L_req"]} thin mu"H" $

#block(fill: rgb("#f6f9fc"), inset: 10pt, radius: 3pt)[
  *Result:* the BOM lists *{n_phase}× identical cores*
  with $L_("per phase") = {ctx["L_actual"]} thin mu"H"$. The
  input capacitance/EMI is reduced by a factor of $N$ due to
  ripple cancellation at the common node.
]
"""


def _body_buck_ccm(spec: Spec, ctx: dict) -> str:
    """Buck CCM textbook walk-through.

    Worst-case ripple grows with $V_(in)$ (smaller $D$ → larger
    $1 - D$), so the L sizing happens at $V_(in,max)$. We restate
    the volt-seconds balance, the duty derivation with efficiency
    correction, and the L_min closed form.
    """
    Vin_dc_min = getattr(spec, "Vin_dc_min_V", None) or spec.Vin_min_Vrms
    Vin_dc = getattr(spec, "Vin_dc_V", None) or spec.Vin_nom_Vrms
    Vin_dc_max = getattr(spec, "Vin_dc_max_V", None) or spec.Vin_max_Vrms
    Iout = spec.Pout_W / max(spec.Vout_V, 1.0)
    D_min = spec.Vout_V / max(Vin_dc_max * spec.eta, 1e-9)
    return rf"""== 1.1. Operating point

Buck CCM step-down: the inductor continuously conducts the output
current $I_("out") = P_("out") \/ V_("out")$, with a triangular
ripple superimposed. The worst-case ripple is at $V_(in,max)$
(smaller $D$ → larger $1 - D$).

$ I_("out") = P_("out") / V_("out") = {spec.Pout_W:.0f}/{spec.Vout_V:.1f} = {Iout:.2f} thin "A" $

The voltage ratio (volt-second balance with efficiency
correction, $D = V_("out")/(V_("in") dot eta)$):

$ D_(min) = V_("out")/(V_(in,max) dot eta) = {spec.Vout_V:.1f}/({Vin_dc_max:.1f} dot {spec.eta * 100:.1f}%) = {D_min * 100:.1f}% $

$ T_(sw) = 1/f_(sw) = 1/{spec.f_sw_kHz} thin "kHz" = {1e6 / (spec.f_sw_kHz * 1000):.2f} thin mu"s" $

#table(
  columns: (auto, 1fr, auto),
  align: (left, left, right),
  inset: (x: 6pt, y: 4pt),
  table.header[Symbol][Description][Value],
  [$V_(in,min)$], [DC input voltage (worst-case current)], [{Vin_dc_min:.1f} V],
  [$V_(in)$], [Nominal DC voltage], [{Vin_dc:.1f} V],
  [$V_(in,max)$], [Maximum DC voltage (worst-case ripple)], [{Vin_dc_max:.1f} V],
  [$I_("out")$], [DC output current], [{Iout:.2f} A],
  [$D_(min)$], [Minimum duty cycle (at $V_(in,max)$)], [{D_min * 100:.1f} %],
)

= 2. Required inductance

From volt-second balance, $V_("out") = V_("in") dot D - L dot
(d i_L)/d t$. During the off-time $(1-D) dot T_(sw)$, the
current ripple is:

$ Delta i_(L,pp) = V_("out") dot (1 - D)/(L dot f_(sw)) $

To keep $Delta i_(L,pp) lt.eq r dot I_("out")$ (with $r$ = ripple-ratio):

$ L_(min) = V_("out") dot (1 - D_(min))/(r dot I_("out") dot f_(sw)) = {spec.Vout_V:.1f} dot (1 - {D_min:.3f})/({ctx["ripple_pct"]}% dot {Iout:.2f} dot {spec.f_sw_kHz} thin "kHz") = {ctx["L_req"]} thin mu"H" $

#block(fill: rgb("#f6f9fc"), inset: 10pt, radius: 3pt)[
  *Result:* $L_(min) = {ctx["L_req"]} thin mu"H"$.
  The engine uses $L_("real") = {ctx["L_actual"]} thin mu"H"$ ({ctx["N"]} turns).
]
"""


def _body_flyback(spec: Spec, ctx: dict) -> str:
    """Flyback DCM textbook (CCM mode comment at the bottom).

    Primary inductance bounded by D_max in DCM:
    Lp_max = η·Vin²·D_max² / (2·Pout·fsw).
    """
    Vin_min = getattr(spec, "Vin_dc_min_V", None) or spec.Vin_min_Vrms
    D_max = 0.45  # default the engine assumes
    Lp_dcm_uH = (spec.eta * Vin_min**2 * D_max**2) / (2.0 * spec.Pout_W * spec.f_sw_kHz * 1e3) * 1e6
    return rf"""== 1.1. Operating point

Isolated flyback in DCM (engine's default mode, $D_(max) approx 0.45$).
The coupled inductor's primary stores energy during the on-time
and transfers it to the secondary during the off-time. Sizing is by
stored energy balance.

$ V_(in,min) = {Vin_min:.1f} thin "V" $

$ P_(in) = P_("out")/eta = {spec.Pout_W:.0f}/{spec.eta * 100:.1f}% = {spec.Pout_W / spec.eta:.1f} thin "W" $

= 2. Maximum primary inductance (DCM)

The DCM criterion is $D + D_2 < 1$, with $D$ as the normalized on-time
and $D_2$ as the demagnetization time. Solving the stored → delivered
energy balance per cycle:

$ L_(p,max)^("DCM") = (eta dot V_(in,min)^2 dot D_(max)^2)/(2 dot P_("out") dot f_(sw)) $

$ L_(p,max)^("DCM") = ({spec.eta * 100:.1f}% dot {Vin_min:.1f}^2 dot {D_max:.2f}^2)/(2 dot {spec.Pout_W:.0f} dot {spec.f_sw_kHz} thin "kHz") = {Lp_dcm_uH:.0f} thin mu"H" $

In CCM (alternative), the engine uses $L_p = V_(in) dot D/(Delta I_p
dot f_(sw))$, sized for 60% primary ripple.

#block(fill: rgb("#f6f9fc"), inset: 10pt, radius: 3pt)[
  *Result:* $L_(p,"real") = {ctx["L_actual"]} thin mu"H"$ on the primary
  ({ctx["N"]} turns). The turns ratio + reflected voltages
  are in the derived parameters (see separate datasheet).
]
"""


def _body_line_reactor(spec: Spec, ctx: dict) -> str:
    """3φ / 1φ line reactor — sized by %Z impedance target.

    L = X_L / (2π·f_line), X_L = (%Z/100) · V_phase / I_rated.
    """
    import math as _math

    n_ph = getattr(spec, "n_phases", 1)
    V_LL_or_Vph = spec.Vin_nom_Vrms
    V_phase = V_LL_or_Vph / (_math.sqrt(3.0) if n_ph == 3 else 1.0)
    I_rated = getattr(spec, "I_rated_Arms", 0.0) or 1.0
    Z_base = V_phase / max(I_rated, 1e-6)
    pct_Z = getattr(spec, "pct_impedance", 4.0) or 4.0
    X_L = Z_base * pct_Z / 100.0
    omega = 2 * _math.pi * spec.f_line_Hz
    L_mH = (X_L / omega) * 1000.0
    return rf"""== 1.1. Operating point ({n_ph}φ)

Line reactor in series with the rectifier, sized by the
percent impedance drop ($%Z$) criterion. The reactor does not
switch: it only sees the line fundamental and its harmonics.

$ V_("phase") = {f"{V_LL_or_Vph:.1f}\\,V/" + 'sqrt(3) = ' if n_ph == 3 else ''}{V_phase:.1f} thin "V" $

$ I_("rated") = {I_rated:.2f} thin "A"_("rms") $

$ Z_("base") = V_("phase")/I_("rated") = {V_phase:.1f}/{I_rated:.2f} = {Z_base:.2f} thin Omega $

= 2. Required inductance by $%Z$

The target reactance, at the line frequency, is a fraction $%Z$ of the
base impedance:

$ X_L = (%Z\/100) dot Z_("base") = ({pct_Z:.1f}%) dot {Z_base:.2f} = {X_L:.3f} thin Omega $

The corresponding inductance is $L = X_L \/ omega$:

$ L = X_L/(2 pi dot f_("line")) = {X_L:.3f}/(2 pi dot {spec.f_line_Hz:.0f} thin "Hz") = {L_mH:.2f} thin "mH" $

#block(fill: rgb("#f6f9fc"), inset: 10pt, radius: 3pt)[
  *Result:* $L = {L_mH:.2f}$ mH (spec target: ${getattr(spec, "L_req_mH", L_mH):.2f}$ mH).
  The engine synthesized {ctx["N"]} turns to achieve
  ${ctx["L_actual_mH"]}$ mH on the selected core.
]
"""


def _body_passive_choke(spec: Spec, ctx: dict) -> str:
    """AC-side passive choke for THD reduction.

    L = k(THD) · Z_base / (2π·f_line) — Erickson Ch.18 passive PFC.
    """
    import math as _math

    target_thd = 0.30
    Pin = spec.Pout_W / spec.eta
    Z_base = spec.Vin_min_Vrms**2 / max(Pin, 1.0)
    k = 0.35 * (0.30 / max(target_thd, 0.05))
    omega = 2 * _math.pi * spec.f_line_Hz
    L_uH = k * Z_base / omega * 1e6
    return rf"""== 1.1. Operating point

Passive PFC choke in series with the AC rectifier. No switching:
the inductor only sees the fundamental line current plus harmonics.
Sizing is by the empirical target THD criterion (Erickson Ch.
18, AND8016).

$ P_(in) = P_("out")/eta = {spec.Pout_W:.0f}/{spec.eta * 100:.1f}% = {Pin:.1f} thin "W" $

$ Z_("base") = V_(in,min)^2/P_(in) = {spec.Vin_min_Vrms:.0f}^2/{Pin:.1f} = {Z_base:.2f} thin Omega $

= 2. Required inductance

The $k("THD")$ coefficient comes from the empirical fit in Erickson Ch.
18 (passive PFC with LC). For a target THD of {target_thd * 100:.0f}%:

$ k("THD") = 0.35 dot ({0.3:.1f}/"THD"_("target")) = {k:.3f} $

$ L = k dot Z_("base")/(2 pi dot f_("line")) = {k:.3f} dot {Z_base:.2f}/(2 pi dot {spec.f_line_Hz:.0f} thin "Hz") = {L_uH:.0f} thin mu"H" $

#block(fill: rgb("#f6f9fc"), inset: 10pt, radius: 3pt)[
  *Result:* $L approx {L_uH:.0f}$ µH. The engine synthesized {ctx["N"]}
  turns for ${ctx["L_actual"]}$ µH on the chosen core.
  Practical THD depends on the bulk cap + line impedance.
]
"""


def _body_generic(spec: Spec, ctx: dict) -> str:
    """Fallback for topologies without a dedicated body."""
    return rf"""== 1.1. Topology: {spec.topology}

This topology does not have a dedicated derivation narrative in this
version of the Typst report. The universal values below (resistance,
losses, thermal) are valid; consult the legacy ReportLab datasheet
for the full derivation.

= 2. Required inductance

#block(fill: rgb("#f6f9fc"), inset: 10pt, radius: 3pt)[
  *Engine result:* $L_(min) = {ctx["L_req"]}$ µH,
  $L_("real") = {ctx["L_actual"]}$ µH ({ctx["N"]} turns).
]
"""


# ---------------------------------------------------------------------------
# Figure rendering — matplotlib → PNG bytes → ``extra_files`` of compile_to_pdf
# ---------------------------------------------------------------------------
def _render_figures_block(available: set[str]) -> str:
    """Return the Typst markup for the figures section.

    Only references files in ``available`` so a topology that didn't
    produce a waveform sample doesn't trip a "file not found" at
    compile time. When no figures are available the block becomes a
    short note so the report doesn't end abruptly at section 9.
    """
    if not available:
        return ""

    blocks = []
    blocks.append("= 10. Waveforms and losses\n\n")
    blocks.append(
        "The figures below are generated directly from the engine's "
        "output — the time-domain waveform (1-2 line or switching "
        "cycles, depending on topology) and the breakdown of the four "
        "loss components (Cu DC, Cu AC, core line-band, "
        "core ripple-band).\n\n"
    )
    if "fig_waveform.png" in available:
        blocks.append("== 10.1. Inductor current\n\n")
        blocks.append('#align(center)[#image("fig_waveform.png", width: 100%)]\n\n')
    if "fig_losses.png" in available:
        blocks.append("== 10.2. Loss breakdown\n\n")
        blocks.append('#align(center)[#image("fig_losses.png", width: 100%)]\n\n')
    return "".join(blocks)


def _render_figures(spec: Spec, result: DesignResult) -> dict[str, bytes]:
    """Build the per-design PNG blobs the Typst template references.

    Returned filenames must match the ``#image("name.png")`` calls in
    the template. Each helper isolates its matplotlib figure (own
    ``Figure`` object, closed before returning) so the engine's
    background-thread workers don't leak global pyplot state.
    """
    figures: dict[str, bytes] = {}
    wf_png = _make_waveform_png(spec, result)
    if wf_png:
        figures["fig_waveform.png"] = wf_png
    loss_png = _make_loss_breakdown_png(result)
    if loss_png:
        figures["fig_losses.png"] = loss_png
    return figures


def _make_waveform_png(spec: Spec, result: DesignResult) -> bytes | None:
    """Inductor current vs time over one (or two) line cycles.

    The engine populates ``waveform_t_s`` / ``waveform_iL_A`` for
    every topology that has a meaningful time-domain shape (boost,
    buck, flyback, line reactor). When absent we return ``None`` so
    the caller skips the figure cleanly.
    """
    t = result.waveform_t_s
    i = result.waveform_iL_A
    if not t or not i:
        return None
    try:
        import io

        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 2.6), dpi=140)
    ax.plot(
        [x * 1e3 for x in t],
        i,
        color="#2364AA",
        linewidth=0.7,
    )
    ax.set_xlabel("Time (ms)", fontsize=9)
    ax.set_ylabel(_waveform_y_label(spec.topology), fontsize=9)
    ax.set_title(
        f"Inductor current — {_topology_label(spec.topology)}",
        fontsize=10,
        pad=8,
    )
    ax.grid(True, linestyle=":", linewidth=0.4, color="#ccc")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _waveform_y_label(topology: str) -> str:
    if topology == "flyback":
        return "Primary I (A)"
    if topology in ("line_reactor", "passive_choke"):
        return "Line I (A)"
    return "Inductor I (A)"


def _make_loss_breakdown_png(result: DesignResult) -> bytes | None:
    """Horizontal stacked bar of the four loss components.

    The four-way split (Cu DC, Cu AC, Core line, Core ripple) is
    exactly what the engine emits in ``LossBreakdown`` — no
    re-derivation here, just a visual grouping the customer can scan
    in <1 s.
    """
    try:
        import io

        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    L = result.losses
    parts = [
        ("Cu DC", L.P_cu_dc_W, "#2364AA"),
        ("Cu AC (fsw)", L.P_cu_ac_W, "#3DA5D9"),
        ("Core (line)", L.P_core_line_W, "#73BFB8"),
        ("Core (ripple)", L.P_core_ripple_W, "#FEC601"),
    ]
    total = sum(p[1] for p in parts)
    if total <= 0:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 1.6), dpi=140)
    cumulative = 0.0
    for label, value, color in parts:
        if value <= 0:
            continue
        ax.barh([0], [value], left=cumulative, color=color, edgecolor="white", linewidth=1.0)
        # In-bar label when the slice is wide enough; otherwise skip
        # so tiny components don't print over their neighbours.
        if value / total > 0.05:
            ax.text(
                cumulative + value / 2,
                0,
                f"{label}\n{value:.2f} W",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if color in ("#2364AA", "#73BFB8") else "#222",
            )
        cumulative += value
    ax.set_xlim(0, total * 1.02)
    ax.set_ylim(-0.6, 0.6)
    ax.set_yticks([])
    ax.set_xlabel("Loss (W)", fontsize=9)
    ax.set_title(f"Loss breakdown — total {total:.2f} W", fontsize=10, pad=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


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
        gap_status=("calculated by engine" if gap_mm > 0 else "powder core (distributed gap)"),
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
        feasible="FEASIBLE" if result.is_feasible() else "REVISE",
        feasible_color="#2C7A3F" if result.is_feasible() else "#B8302B",
        # Warnings list (joined)
        warnings_block=_render_warnings(result.warnings),
        # Misc
        date_iso="",  # filled by caller
        designer="",
        revision="",
        project_id="",
        topology_label="",
        spec_table="",
        cover_summary="",
        )
    )


def _render_warnings(warnings: list[str]) -> str:
    if not warnings:
        return "No warnings. Design is within all spec margins."
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
  title: "Project Report — PFC Inductor",
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
        [MagnaDesign · PFC Inductor · {project_id}],
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
      [Confidential — internal use only],
      [Page #counter(page).display() of #counter(page).final().first()],
      [{topology_label}],
    )
  ],
)

#set text(font: "New Computer Modern", size: 10.5pt, lang: "en")
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
  #text(size: 26pt, weight: "bold")[PFC Inductor Design]
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
    {cover_summary}
  ]
  #v(1cm)
  #text(size: 9pt, fill: rgb("#555"))[
    This document describes every step of the design process — equation,
    substituted values, and result — so the engineer can
    audit and reproduce the calculation. All the math shown here is
    the same that the MagnaDesign engine executed.
  ]
]
#pagebreak()

// ────────────────────────────────────────────────────────────────────
// 1. Spec
// ────────────────────────────────────────────────────────────────────
= 1. Input specification

The user-defined specification sets the operating window
against which the engine sizes the inductor.

{spec_table}

{topology_body}

// ────────────────────────────────────────────────────────────────────
// 3. Selected core + material
// ────────────────────────────────────────────────────────────────────
= 3. Selected components

== 3.1. Core

#table(
  columns: (auto, 1fr),
  align: (left, left),
  stroke: (x, y) => if y == 0 {{{{ (bottom: 0.7pt) }}}} else {{{{ (bottom: 0.2pt + rgb("#ddd")) }}}},
  inset: (x: 6pt, y: 4pt),
  table.header[Parameter][Value],
  [Identifier], [`{core_id}`],
  [Vendor / part-number], [{core_vendor} / {core_part}],
  [Shape], [{core_shape}],
  [$A_e$ — magnetic area], [{Ae_mm2} mm² = {Ae_cm2} cm²],
  [$W_a$ — window area], [{Wa_mm2} mm²],
  [$l_e$ — magnetic path length], [{le_mm} mm],
  [$V_e$ — effective volume], [{Ve_mm3} mm³ = {Ve_cm3} cm³],
  [MLT — mean length per turn], [{MLT_mm} mm],
  [Nominal $A_L$ (from catalog)], [{AL_nominal} nH/N²],
  [Outer dimensions (toroid)], [OD = {OD_mm} mm · ID = {ID_mm} mm · HT = {HT_mm} mm],
)

== 3.2. Magnetic material

#table(
  columns: (auto, 1fr),
  align: (left, left),
  stroke: (x, y) => if y == 0 {{{{ (bottom: 0.7pt) }}}} else {{{{ (bottom: 0.2pt + rgb("#ddd")) }}}},
  inset: (x: 6pt, y: 4pt),
  table.header[Parameter][Value],
  [Identifier / vendor], [`{mat_id}` · {mat_vendor}],
  [Family], [{mat_name}],
  [Initial permeability $mu_r$], [{mu_r}],
  [$B_(sat)$ at 25 °C], [{B_sat_25_mT} mT],
  [$B_(sat)$ at 100 °C], [{B_sat_100_mT} mT],
  [Steinmetz $alpha$], [{steinmetz_alpha}],
  [Steinmetz $beta$], [{steinmetz_beta}],
  [Steinmetz $P_(v,ref)$ @ ($f_(ref)$, $B_(ref)$)], [{steinmetz_Pv_ref} mW/cm³ @ ({steinmetz_f_ref} kHz, {steinmetz_B_ref} mT)],
  [Valid $f_(min)$ for loss model], [{steinmetz_f_min} kHz],
)

== 3.3. Wire

#table(
  columns: (auto, 1fr),
  align: (left, left),
  stroke: (x, y) => if y == 0 {{{{ (bottom: 0.7pt) }}}} else {{{{ (bottom: 0.2pt + rgb("#ddd")) }}}},
  inset: (x: 6pt, y: 4pt),
  table.header[Parameter][Value],
  [Identifier / type], [`{wire_id}` · {wire_type}],
  [AWG], [{wire_awg}],
  [Outer diameter (with insulation)], [{wire_d_mm} mm],
  [Copper diameter], [{wire_d_cu_mm} mm],
  [Copper area (per strand)], [{wire_A_cu_mm2} mm²],
  [Parallel wires (litz / strands)], [{wire_n_strands}],
  [Total copper area], [{A_cu_total_mm2} mm²],
)

// ────────────────────────────────────────────────────────────────────
// 4. Turns + gap solution
// ────────────────────────────────────────────────────────────────────
= 4. Turns, effective $A_L$, and air gap

The inductance of a wound magnetic core is
$L = N² dot A_L$, where $A_L$ depends on the material and its
saturation state. The engine solves this in two distinct paths
depending on the material type:

== 4.1. Air gap resolution

The core choice influences the calculation: powder cores (Magnetics
Kool-Mu, High-Flux, Sendust) have a distributed gap implicit in the
material — the catalog $A_L$ is effective and saturation is handled
via the $mu(H)$ roll-off curve. Ferrite cores ($mu_r$ high, no
roll-off) require an explicit air gap calculated from the
magnetic energy balance.

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Gap status:* {gap_status}. \
  *Value used:* $l_(gap) = {gap_mm}$ mm.
]

For the ferrite case (with $mu_r approx {mu_r}$), the engine imposes the
saturation constraint:

$ N_(min,sat) = ceil((L dot I_(pk))/(B_(sat)^* dot A_e)) $

where $B_(sat)^* = B_(sat)(100\\,°"C") dot (1 - "margin") = {B_limit_mT}$ mT.
Substituting:

$ N_(min,sat) = ceil(({L_actual}\\,mu"H" dot {I_in_pk}\\,"A")/({B_limit_mT}\\,"mT" dot {Ae_mm2}\\,"mm"^2)) approx {N} thick "turns" $

With $N$ defined, the air gap becomes:

$ l_(gap) = (N^2 dot mu_0 dot A_e)/L - l_e/mu_r $

And the effective $A_L$ is:

$ A_L^("eff") = (mu_0 dot A_e)/(l_e/mu_r + l_(gap)) = {AL_eff} thin "nH"\\/N^2 $

== 4.2. Resulting inductance

$ L_("real") = N² dot A_L^("eff") dot mu(H) = {N}^2 dot {AL_eff}\\,"nH" dot {mu_pct}\\,% = {L_actual} thin mu"H" $

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Result:* $N = {N}$ turns · $L_("real") = {L_actual} thin mu"H"$
  ({L_actual_mH} mH) vs. required $L_(min) = {L_req}$ µH.
]

// ────────────────────────────────────────────────────────────────────
// 5. Magnetic flux and saturation
// ────────────────────────────────────────────────────────────────────
= 5. Flux density and saturation

The $H$ field at the peak line current:

$ H_(pk) = (N dot I_(in,pk))/l_e = ({N} dot {I_in_pk}\\,"A")/{le_mm}\\,"mm" = {H_pk_Am} thin "A/m" = {H_pk_Oe} thin "Oe" $

The magnetic flux density in the core at the wave peak:

$ B_(pk) = (L dot I_(in,pk))/(N dot A_e) = ({L_actual_mH}\\,"mH" dot {I_in_pk}\\,"A")/({N} dot {Ae_mm2}\\,"mm"^2) = {B_pk_mT} thin "mT" $

Comparing with the saturation margin:

#table(
  columns: (auto, 1fr, auto, auto),
  align: (left, left, right, center),
  stroke: (x, y) => if y == 0 {{{{ (bottom: 0.7pt) }}}} else {{{{ (bottom: 0.2pt + rgb("#ddd")) }}}},
  inset: (x: 6pt, y: 4pt),
  table.header[Metric][Definition][Value][Status],
  [$B_(pk)$], [Computed peak flux], [{B_pk_mT} mT], [—],
  [$B_(sat)^*$], [Limit = $B_(sat)(100\\,°"C") dot (1 - "margin")$], [{B_limit_mT} mT], [—],
  [Margin], [$(B_(sat)^* - B_(pk))/B_(sat)^*$], [{sat_margin_pct} %], [{ok_B}],
)

// ────────────────────────────────────────────────────────────────────
// 6. Window fill
// ────────────────────────────────────────────────────────────────────
= 6. Window and manufacturability

The total copper area occupied by the winding:

$ A_("copper,tot") = N dot A_("cu,wire") dot n_("strands") = {N} dot {wire_A_cu_mm2}\\,"mm"^2 dot {wire_n_strands} = {A_cu_total_mm2} thin "mm"^2 $

The window fill factor:

$ K_u = A_("copper,tot") / W_a = {A_cu_total_mm2}\\,"mm"^2 / {Wa_mm2}\\,"mm"^2 = {Ku_actual_pct}\\,% $

#table(
  columns: (auto, 1fr, auto, auto),
  align: (left, left, right, center),
  stroke: (x, y) => if y == 0 {{{{ (bottom: 0.7pt) }}}} else {{{{ (bottom: 0.2pt + rgb("#ddd")) }}}},
  inset: (x: 6pt, y: 4pt),
  table.header[Metric][Definition][Value][Status],
  [$K_u$], [Actual fill factor], [{Ku_actual_pct} %], [{ok_Ku}],
  [$K_(u,max)$], [Limit (spec)], [{Ku_max_pct} %], [—],
  [Estimated layers], [For Dowell calculation], [{layers}], [—],
  [Total wire length], [$l_("wire") = N dot "MLT"$], [{l_wire_m} m], [—],
)

// ────────────────────────────────────────────────────────────────────
// 7. DC + AC Resistance
// ────────────────────────────────────────────────────────────────────
= 7. Resistance and copper losses

== 7.1. DC Resistance

Copper resistivity increases with temperature according to the
coefficient $alpha_(Cu) = 3.93 dot 10^(-3)$/°C:

$ rho_(Cu)(T) = rho_(Cu,20) dot (1 + alpha_(Cu) dot (T - 20)) $

Evaluated at $T = T_("winding") = {T_winding}$ °C:

$ rho_(Cu)({T_winding}\\,°"C") = {rho_20}\\,Omega dot "m" dot (1 + 0.00393 dot ({T_winding} - 20)) = {rho_at_T}\\,Omega dot "m" $

$ R_("dc") = (rho_(Cu) dot N dot "MLT")/A_("cu,wire") = ({rho_at_T}\\,Omega"·m" dot {N} dot {MLT_mm}\\,"mm")/{wire_A_cu_mm2}\\,"mm"^2 = {R_dc_mOhm} thin "mΩ" $

== 7.2. AC Resistance (Dowell)

At $f_(sw) = {fsw_kHz}$ kHz, the skin effect and proximity
between turns raise $R_("ac")$ above $R_("dc")$. The correction
factor $F_R$ comes from the Dowell model for round conductors
(or Litz, when applicable) with the estimated layer count.

$ R_("ac") = R_("dc") dot F_R("layers"={layers}, f={fsw_kHz}\\,"kHz", T={T_winding}\\,°"C") $

$ F_R = {F_R} arrow.r R_("ac") = {R_ac_mOhm} thin "mΩ" $

== 7.3. Copper losses

$ P_(Cu,dc) = I_("rms,line")^2 dot R_("dc") = ({I_in_rms}\\,"A")^2 dot {R_dc_mOhm}\\,"mΩ" = {P_cu_dc} thin "W" $

$ P_(Cu,ac) = I_("rms,ripple")^2 dot R_("ac") = ({I_ripple_rms}\\,"A")^2 dot {R_ac_mOhm}\\,"mΩ" = {P_cu_ac} thin "W" $

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Total copper loss:* $P_("copper") = P_(Cu,dc) + P_(Cu,ac) = {P_cu_tot}$ W
]

// ────────────────────────────────────────────────────────────────────
// 8. Core losses
// ────────────────────────────────────────────────────────────────────
= 8. Core losses

The Steinmetz model parameterizes volumetric loss as a function of
frequency and flux amplitude:

$ P_v thin ["mW"\/"cm"^3] = P_(v,ref) dot (f/f_(ref))^alpha dot (B/B_(ref))^beta $

The coefficients for this material (from the catalog):
$alpha = {steinmetz_alpha}$,
$beta = {steinmetz_beta}$,
$P_(v,ref) = {steinmetz_Pv_ref}$ mW/cm³ @
$(f_(ref) = {steinmetz_f_ref}$ kHz,
$B_(ref) = {steinmetz_B_ref}$ mT$)$.

== 8.1. Line band (envelope $2 dot f_("line")$)

$ P_("core,line") = P_v(f_("line"), B_(pk)) dot V_e = {P_core_line} thin "W" $

When $f_("line") < f_(min) = {steinmetz_f_min}$ kHz, the model is
extrapolated and the engine zeroes out this band (avoids predicting
outside the calibrated range).

== 8.2. Switching band (iGSE on $Delta B_(pp)(t)$)

The triangular wave at $f_(sw)$ has an amplitude $Delta B_(pp)$ that
varies throughout the line half-cycle. The engine applies iGSE
(Mühlethaler 2012) over the $Delta B_(pp)(t)$ array to capture the
non-linear effect $lr(angle.l B^beta angle.r) >> lr(angle.l B angle.r)^beta$ characteristic of PFC:

$ P_("core,ripple") = lr(angle.l P_v(f_(sw), Delta B_(pp)(t)\/2) angle.r) dot V_e = {P_core_ripple} thin "W" $

#block(
  fill: rgb("#f6f9fc"),
  inset: 10pt,
  radius: 3pt,
)[
  *Total core loss:* $P_("core") = P_("line") + P_("ripple") = {P_core_tot}$ W
]

// ────────────────────────────────────────────────────────────────────
// 9. Thermal balance
// ────────────────────────────────────────────────────────────────────
= 9. Thermal balance

The lumped model is natural convection plus radiation, with a
combined coefficient $h = {h_conv}$ W/m²/K. The surface area of the
assembled inductor:

$ A_("surf") = pi dot OD dot HT + pi dot ID dot HT + 2 dot pi/4 dot (OD^2 - ID^2) = {A_surf_cm2} thin "cm"^2 $

The temperature rise is solved iteratively because $rho_(Cu)(T)$
feeds back into the copper loss:

$ Delta T = (P_("total")(T))/(h dot A_("surf")) thick arrow.r thick T = T_("amb") + Delta T $

Convergence (3-6 iterations typical):

#table(
  columns: (auto, 1fr, auto),
  align: (left, left, right),
  stroke: (x, y) => if y == 0 {{{{ (bottom: 0.7pt) }}}} else {{{{ (bottom: 0.2pt + rgb("#ddd")) }}}},
  inset: (x: 6pt, y: 4pt),
  table.header[Metric][Definition][Value],
  [$T_("amb")$], [Ambient temperature], [{T_amb} °C],
  [$Delta T$], [Rise over ambient], [{T_rise} K],
  [$T_("winding")$], [Winding temperature], [*{T_winding} °C*],
  [$T_("max")$], [Spec limit], [{T_max} °C],
)

{figures_block}

// ────────────────────────────────────────────────────────────────────
// 11. Summary
// ────────────────────────────────────────────────────────────────────
#pagebreak()
= 11. Design summary

#block(
  width: 100%,
  inset: 14pt,
  radius: 4pt,
  fill: rgb("#fafbfc"),
  stroke: 0.5pt + rgb("#dee"),
)[
  #set text(size: 11pt)
  *Overall status:* #text(fill: rgb("{feasible_color}"), weight: "bold")[{feasible}]

  #v(8pt)
  #grid(
    columns: (1fr, 1fr),
    column-gutter: 1cm,
    row-gutter: 8pt,
    [
      *Magnetic*
      - $N$ = {N} turns
      - $L$ = {L_actual} µH
      - $B_(pk)$ = {B_pk_mT} mT
      - $l_(gap)$ = {gap_mm} mm
      - $K_u$ = {Ku_actual_pct} %
    ],
    [
      *Thermal + losses*
      - $T_("winding")$ = {T_winding} °C ($Delta T$ = {T_rise} K)
      - $P_("copper")$ = {P_cu_tot} W
      - $P_("core")$ = {P_core_tot} W
      - $P_("total")$ = *{P_total} W*
      - $eta_("inductor")$ = {eta_inductor} %
    ],
  )
]

#v(12pt)
== Checks

#table(
  columns: (auto, 1fr, auto, auto),
  align: (left, left, right, center),
  stroke: (x, y) => if y == 0 {{{{ (bottom: 0.7pt) }}}} else {{{{ (bottom: 0.2pt + rgb("#ddd")) }}}},
  inset: (x: 6pt, y: 4pt),
  table.header[Criterion][Rule][Achieved][Status],
  [Saturation], [$B_(pk) lt.eq B_(sat)^*$], [{B_pk_mT} mT $lt.eq$ {B_limit_mT} mT], [{ok_B}],
  [Window], [$K_u lt.eq K_(u,max)$], [{Ku_actual_pct} % $lt.eq$ {Ku_max_pct} %], [{ok_Ku}],
  [Thermal], [$T_("winding") lt.eq T_("max)$], [{T_winding} °C $lt.eq$ {T_max} °C], [{ok_T}],
)

== Engine warnings

#block(inset: (left: 4pt))[
{warnings_block}
]

#v(0.6cm)
#align(right)[
  #set text(size: 8pt, fill: rgb("#888"))
  Generated by MagnaDesign on {date_iso} · project `{project_id}` · revision {revision}
]
"""

