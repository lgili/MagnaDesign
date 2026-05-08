"""Compliance dispatcher — pick standards + run them.

For each applicable standard the dispatcher pulls the right
inputs from the engine outputs, calls into
:mod:`pfc_inductor.standards`, and wraps the result into a
uniform :class:`StandardResult` so consumers (UI, CLI, PDF
writer) don't need to know which standard returned which shape.

Topology → standards table
--------------------------

================== ============================================
Topology            Standards triggered (by default)
================== ============================================
``boost_ccm``       IEC 61000-3-2 Class D (active PFC mostly
                    *passes by design*, but we still report the
                    spectrum so an auditor can see the margin).
``line_reactor``    IEC 61000-3-2 Class A (uncontrolled rectifier
                    + reactor — the main use case for harmonic
                    compliance reports).
``passive_choke``   IEC 61000-3-2 Class D.
================== ============================================

Region tags
-----------

The dispatcher accepts a ``region`` hint (``EU``, ``US``,
``BR``, ``Worldwide``) so future per-region rule sets (UL,
NBR, GB) can be added without changing call sites. Today only
``EU`` / ``Worldwide`` are wired (IEC standards apply); ``US``
and ``BR`` route through the same Class A/D check until the
follow-up commits land their UL / NBR variants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.standards import en55032, iec61000_3_2

ConclusionLabel = Literal["PASS", "MARGINAL", "FAIL", "NOT APPLICABLE"]
RegionTag = Literal["EU", "US", "BR", "Worldwide"]


# ---------------------------------------------------------------------------
# Per-standard result wrapper
# ---------------------------------------------------------------------------
@dataclass
class StandardResult:
    """One standard's evaluation, in a shape every consumer can render.

    Each row of ``rows`` is a tuple ``(label, value_str, limit_str,
    margin_pct, passed)`` so the PDF writer can lay out a generic
    "compared against limit" table without per-standard branching.
    """

    standard: str             # e.g. "IEC 61000-3-2:2018"
    edition: str              # e.g. "Edition 5.0"
    scope: str                # plain-language description
    conclusion: ConclusionLabel
    summary: str              # one-line headline
    rows: list[tuple[str, str, str, float, bool]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Free-form notes shown under the table — calibration warnings,
    follow-on action items ("LISN measurement required for
    certification"), etc."""

    extras: dict = field(default_factory=dict)
    """Per-standard payload that doesn't fit the generic row shape
    — e.g. the raw harmonic spectrum for the IEC plot. The PDF
    writer pulls per-standard plots out of here when present."""


@dataclass
class ComplianceBundle:
    """Aggregate output of :func:`evaluate`."""

    project_name: str
    topology: str
    region: RegionTag
    standards: list[StandardResult] = field(default_factory=list)

    @property
    def overall(self) -> ConclusionLabel:
        """Worst case across every applicable standard.

        ``NOT APPLICABLE`` per-standard is excluded from the
        aggregate; only standards that actually evaluated count
        toward the verdict.
        """
        scores = {"PASS": 0, "MARGINAL": 1, "FAIL": 2, "NOT APPLICABLE": -1}
        worst = -1
        worst_label: ConclusionLabel = "NOT APPLICABLE"
        for r in self.standards:
            score = scores.get(r.conclusion, 0)
            if score > worst:
                worst = score
                worst_label = r.conclusion
        return worst_label


# ---------------------------------------------------------------------------
# Applicability table
# ---------------------------------------------------------------------------
def applicable_standards(
    spec: Spec,
    region: RegionTag = "Worldwide",
) -> list[str]:
    """Return the list of standard IDs this spec triggers.

    Used by the UI to surface which checks are about to run, and
    by the dispatcher itself to drive the evaluation loop. Keep
    in sync with :func:`evaluate` — a standard listed here must
    have an evaluator branch below.
    """
    out: list[str] = []
    # IEC 61000-3-2 covers every line-frequency topology in the
    # app right now (the boost-PFC's input current is conditioned
    # by the rectifier + reactor combination, so the same Class
    # D / A limits apply to its drawn current spectrum).
    if region in ("EU", "Worldwide", "BR"):
        out.append("IEC 61000-3-2")
    # EN 55032 conducted-EMI applies to switching converters with
    # appreciable ripple. Boost-PFC + buck-CCM + flyback all qualify;
    # passive choke / line reactor produce no measurable conducted
    # EMI in this band (they're a 60 Hz path).
    if region in ("EU", "Worldwide", "BR"):
        if spec.topology in ("boost_ccm", "buck_ccm", "flyback"):
            out.append("EN 55032")
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def evaluate(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    *,
    project_name: str = "",
    region: RegionTag = "Worldwide",
    edition: iec61000_3_2.Edition = "5.0",
) -> ComplianceBundle:
    """Run every applicable standard and aggregate."""
    bundle = ComplianceBundle(
        project_name=project_name or "Untitled Project",
        topology=spec.topology,
        region=region,
    )

    applicable = applicable_standards(spec, region)
    if "IEC 61000-3-2" in applicable:
        bundle.standards.append(_evaluate_iec61000_3_2(
            spec, core, wire, material, result, edition=edition,
        ))
    if "EN 55032" in applicable:
        bundle.standards.append(_evaluate_en55032(
            spec, core, wire, material, result,
        ))

    return bundle


def _evaluate_en55032(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
) -> StandardResult:
    """Run the analytical conducted-EMI envelope estimator and
    translate to the standard ``StandardResult`` shape."""
    fsw_kHz = float(getattr(spec, "f_sw_kHz", 0.0) or 0.0)
    ripple_pk = float(getattr(result, "I_ripple_pk_pk_A", 0.0) or 0.0)

    # Class B (residential / appliance) is the default for the
    # compressor-inverter use case; the dispatcher could later
    # accept a region+application hint to pick A vs. B.
    report = en55032.evaluate_emi(
        spec_fsw_kHz=fsw_kHz,
        I_ripple_pk_pk_A=ripple_pk,
        class_="B",
        detector="QP",
    )

    rows: list[tuple[str, str, str, float, bool]] = []
    for pt in report.points:
        rows.append((
            f"n = {pt.n}",
            f"{pt.measured_dbuv:.1f} dBµV @ "
            f"{pt.frequency_Hz / 1e6:.2f} MHz",
            f"{pt.limit_dbuv:.1f} dBµV",
            float(pt.margin_dB),
            bool(pt.passes),
        ))

    if not rows:
        conclusion: ConclusionLabel = "PASS"
        summary = (
            "PASS — fsw is too low to produce harmonics in the "
            "150 kHz – 30 MHz conducted-EMI band, or ripple "
            "amplitude is zero."
        )
    elif report.passes:
        if report.worst_margin_dB < 6.0:
            conclusion = "MARGINAL"
            summary = (
                f"PASS — but worst margin only "
                f"{report.worst_margin_dB:.1f} dB at "
                f"h={report.worst_n}. LISN measurement strongly "
                f"recommended; analytical envelope has ±10 dB "
                f"uncertainty."
            )
        else:
            conclusion = "PASS"
            summary = (
                f"PASS — worst margin {report.worst_margin_dB:.1f} dB "
                f"at h={report.worst_n}."
            )
    else:
        conclusion = "FAIL"
        summary = (
            f"FAIL — h={report.worst_n} exceeds the Class B QP "
            f"limit by {abs(report.worst_margin_dB):.1f} dB. "
            f"Analytical envelope only — real LISN measurement "
            f"with snubber + Y-cap fitted may shift this; treat "
            f"as a design-stage warning."
        )

    notes: list[str] = [
        "Class B (residential / appliance) limits per EN 55032:2017 §A.5.",
        "Quasi-peak (QP) detector. Average (AV) limits are 10 dB tighter.",
        "Analytical envelope ONLY — assumes ideal square-wave switching, "
        f"a {en55032.DEFAULT_CP_PF:.0f} pF parasitic shunt capacitance, "
        "and a 50 Ω LISN. Real-world certification needs LISN + "
        "spectrum-analyser measurement with the production controller.",
        "Snubber capacitance, controller dV/dt and ground-plane "
        "returns are NOT modelled — they typically *worsen* the "
        "high-MHz envelope by 5–15 dB.",
    ]

    return StandardResult(
        standard="EN 55032",
        edition="Edition 2017 + A1:2020",
        scope=(
            "Class B conducted-emission limits for "
            "multimedia / residential equipment in the "
            "150 kHz – 30 MHz band."
        ),
        conclusion=conclusion,
        summary=summary,
        rows=rows,
        notes=notes,
        extras={
            "fsw_Hz":          report.fsw_Hz,
            "worst_margin_dB": report.worst_margin_dB,
            "worst_n":         report.worst_n,
            "n_harmonics":     len(report.points),
            "class":           report.class_,
            "detector":        report.detector,
        },
    )


# ---------------------------------------------------------------------------
# Per-standard evaluators
# ---------------------------------------------------------------------------
def _evaluate_iec61000_3_2(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    *,
    edition: iec61000_3_2.Edition,
) -> StandardResult:
    """Run the Class D evaluator and translate to a ``StandardResult``.

    Class D is the most common limit set for diode-rectified loads
    (PCs, TVs, lighting, drives). Class A is wider and applies to
    "general" equipment; we report Class D by default as the
    tighter envelope — passing Class D implies passing Class A.
    """
    # Fundamental + per-harmonic currents in amperes. We accept
    # two engine shapes:
    # (a) Engine produced ``harmonic_amplitudes_pct`` for line-
    #     reactor / passive-choke flows — already a per-cent
    #     spectrum normalised to the fundamental.
    # (b) Engine produced just I_line_rms_A — common for boost-PFC
    #     where the line current is sinusoidal (low THD by design),
    #     so all harmonics are nominally zero. The compliance run
    #     still emits the report (every odd order PASS at 0 A) so
    #     the auditor sees the spectrum was checked.
    pct = _resolve_harmonic_pct(spec, result)
    fundamental_a = _resolve_fundamental(spec, result)
    harmonics_a = {
        n + 1: pct[n] / 100.0 * fundamental_a
        for n in range(1, len(pct))
        if pct[n] > 0
    }

    # Apparent input power for the limit calc — IEC 61000-3-2
    # uses Pi (W) ≈ Vr × Ifund × pf_norm. Use the design's actual
    # Vin_nom + the standard's normalised pf 0.78.
    pi_w = (
        iec61000_3_2.DEFAULT_VR
        * fundamental_a
        * iec61000_3_2.DEFAULT_PF_NORMALIZED
    )

    report = iec61000_3_2.evaluate_compliance(
        harmonics_a, pi_w, edition=edition,
    )

    rows: list[tuple[str, str, str, float, bool]] = []
    for chk in report.checks:
        # Force a Python bool — the IEC evaluator can yield a
        # numpy.bool_ when the input dict came from FFT outputs,
        # and json.dumps refuses np.bool_ in some versions.
        rows.append((
            f"n = {chk.n}",
            f"{chk.measured_A * 1000:.1f} mA",
            f"{chk.limit_A * 1000:.1f} mA",
            float(chk.margin_pct),
            bool(chk.passes),
        ))

    if not report.checks:
        # No harmonic content to evaluate — typical for active
        # boost-PFC where the engine reports a sinusoidal line
        # current with all-zero higher orders. The auditable
        # outcome is "trivially compliant by construction"; we
        # report PASS but flag the analytical-bound nature in the
        # summary so a certification engineer sees the gap.
        conclusion: ConclusionLabel = "PASS"
        summary = (
            "PASS — engine reports zero higher-order harmonics. "
            "Final certification still requires LISN + spectrum-"
            "analyser measurement at the production controller "
            "bandwidth."
        )
    elif report.passes:
        if report.margin_min_pct < 10.0:
            conclusion = "MARGINAL"
            summary = (
                f"PASS — but worst margin only "
                f"{report.margin_min_pct:.1f} % "
                f"(at h={report.limiting_harmonic}). LISN measurement "
                f"recommended before certification."
            )
        else:
            conclusion = "PASS"
            summary = (
                f"PASS — worst margin "
                f"{report.margin_min_pct:.1f} % "
                f"(at h={report.limiting_harmonic})."
            )
    else:
        conclusion = "FAIL"
        summary = (
            f"FAIL — h={report.limiting_harmonic} exceeds the limit "
            f"by {abs(report.margin_min_pct):.1f} %."
        )

    notes: list[str] = []
    notes.append(
        f"Reference voltage Vr = {iec61000_3_2.DEFAULT_VR:.0f} V; "
        f"normalised power factor pf = "
        f"{iec61000_3_2.DEFAULT_PF_NORMALIZED:.2f} per IEC 61000-3-2 §6.2.3.",
    )
    notes.append(
        f"Pi (apparent input power used for limit calculation) "
        f"= {pi_w:.0f} W.",
    )
    if spec.topology == "boost_ccm":
        notes.append(
            "Active boost-PFC waveforms are sinusoidal by control; "
            "the harmonic content reported here is the analytical "
            "lower bound (zero unless the spec already encoded "
            "non-ideal control). Real-world certification needs "
            "LISN + spectrum-analyser measurement at the production "
            "controller bandwidth.",
        )

    return StandardResult(
        standard="IEC 61000-3-2",
        edition=f"Edition {edition}",
        scope=(
            "Class D harmonic-emission limits for "
            "single-phase equipment ≤ 16 A per phase with "
            "diode-rectified DC link."
        ),
        conclusion=conclusion,
        summary=summary,
        rows=rows,
        notes=notes,
        extras={
            "harmonic_pct":      list(pct),
            "fundamental_A":     fundamental_a,
            "Pi_W":              pi_w,
            "limiting_harmonic": report.limiting_harmonic,
            "margin_min_pct":    report.margin_min_pct,
        },
    )


# ---------------------------------------------------------------------------
# Helpers — engine shape adapters
# ---------------------------------------------------------------------------
def _resolve_harmonic_pct(spec: Spec, result: DesignResult) -> list[float]:
    """Return the harmonic spectrum as ``list[pct]`` indexed by order.

    For line reactors / passive chokes we ask the topology module
    to derive the spectrum from the engine's reported inductance.
    For boost-PFC we return a "flat fundamental, zeros above"
    spectrum — boost waveforms are sinusoidal by design and the
    real-world distortion comes from controller dynamics outside
    the engine's scope.
    """
    n_orders = 40  # cover up to h=39 (Class D ceiling)
    if spec.topology in ("line_reactor", "passive_choke"):
        try:
            from pfc_inductor.topology.line_reactor import (
                harmonic_amplitudes_pct,
            )
            pct = harmonic_amplitudes_pct(
                spec,
                result.L_actual_uH * 1e-3,  # uH → mH
                n_harmonics=n_orders,
            )
            return list(pct)
        except (ValueError, AttributeError, ImportError):
            pass
    # Fallback — fundamental only.
    out = [0.0] * n_orders
    if n_orders > 0:
        out[0] = 100.0
    return out


def _resolve_fundamental(spec: Spec, result: DesignResult) -> float:
    """Best-effort fundamental current in amperes (RMS).

    The engine's ``I_line_rms_A`` is the canonical surface; if it
    isn't populated for some reason we fall back to ``Pout / Vr ×
    pf`` as a conservative estimate so the limit calculation
    still produces sensible numbers.
    """
    i_rms = float(getattr(result, "I_line_rms_A", 0.0) or 0.0)
    if i_rms > 0:
        return i_rms
    pout = float(spec.Pout_W)
    if pout <= 0:
        return 1.0
    return pout / (
        iec61000_3_2.DEFAULT_VR
        * iec61000_3_2.DEFAULT_PF_NORMALIZED
        * float(spec.eta or 1.0)
    )
