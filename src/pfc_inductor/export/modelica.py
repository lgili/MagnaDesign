"""Modelica package emitter — saturable-inductor model.

Emits a single-file Modelica package (``package PFC``) containing
a ``model PFCInductor`` that uses standard Modelica.Electrical
primitives plus a ``Modelica.Blocks.Tables.CombiTable1Ds``
lookup for the L(I) curve. The user imports the file via
``OpenModelica`` (``loadFile(...)``) or any Modelica-compatible
simulator (Wolfram SystemModeler, Dymola).

Why a CombiTable1Ds and not Modelica.Magnetic.FluxTubes
-------------------------------------------------------

FluxTubes is the "physically right" choice but requires an
explicit B(H) curve and a full magnetic-circuit topology that
our app doesn't model. The CombiTable1Ds approach treats the
inductor as a non-linear two-pin element parameterised by L(i),
which matches what we *do* compute (L_effective(I) via rolloff)
without overstating the model's fidelity.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

from pfc_inductor.export.curves import L_vs_I_table
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


def to_modelica(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    package: str = "PFC",
    n_points: int = 25,
) -> str:
    """Return a complete Modelica package text."""
    n_turns = max(1, int(result.N_turns))
    I_max = max(_peak_current_A(result), 1e-3) * 1.5

    L_table = L_vs_I_table(
        material=material,
        core=core,
        n_turns=n_turns,
        I_max=I_max,
        n_points=n_points,
    )

    R_dc = float(getattr(result, "R_dc_ohm", 0.0) or 0.0)
    if R_dc <= 0 and hasattr(result, "losses"):
        R_dc = float(getattr(result.losses, "R_dc_ohm", 0.0) or 0.0)

    table_literal = ";\n        ".join(f"{I:.6f}, {L:.9e}" for I, L in L_table)
    L_nominal_H = float(result.L_actual_uH) * 1e-6 if result.L_actual_uH else 0.0

    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    info = textwrap.dedent(f"""\
        Topology     : {spec.topology}
        Core         : {core.part_number} ({core.shape}, {material.name})
        Wire         : {wire.id}
        N turns      : {n_turns}
        L (small-sig): {L_nominal_H * 1e6:.2f} uH
        R_series     : {R_dc * 1e3:.1f} mOhm
        I_pk swept   : 0..{I_max:.2f} A
        Generated    : {timestamp}
    """).rstrip("\n")

    return textwrap.dedent(f"""\
        within;
        package {package} "MagnaDesign saturable-inductor export"

          model PFCInductor
            "Saturable inductor with L(I) lookup table"
            extends Modelica.Electrical.Analog.Interfaces.OnePort;
            parameter Modelica.SIunits.Resistance R_series = {R_dc:.6e}
              "Series resistance (DC + AC average) [Ohm]";
            Modelica.Blocks.Tables.CombiTable1Ds L_lookup(
              table = [
        {table_literal}
              ],
              smoothness = Modelica.Blocks.Types.Smoothness.LinearSegments,
              extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint
            );
          equation
            L_lookup.u = abs(i);
            v = R_series * i + L_lookup.y[1] * der(i);
            annotation (
              Documentation(info="<html><pre>{info}</pre></html>")
            );
          end PFCInductor;

          annotation (
            Documentation(info="<html>
              <h3>MagnaDesign — Saturable-Inductor Modelica export</h3>
              <pre>{info}</pre>
            </html>"),
            uses(Modelica(version=\"4.0.0\"))
          );
        end {package};
    """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _peak_current_A(result: DesignResult) -> float:
    for attr in ("I_pk_max_A", "I_line_pk_A", "I_pk_A"):
        val = getattr(result, attr, None)
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
    return 0.0
