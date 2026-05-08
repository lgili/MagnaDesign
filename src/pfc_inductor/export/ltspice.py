"""LTspice ``.subckt`` emitter — saturable inductor model.

LTspice handles a saturable inductor via a 2-port subcircuit
that integrates voltage to flux linkage and looks up current
from a piece-wise-linear ``flux → current`` table:

- ``B``-source ``B1`` integrates ``v(p, n) → flux(t)`` (a flux
  state variable).
- A second ``B``-source produces a current proportional to the
  table lookup ``i = table(flux, …)``.
- A series resistor models DCR + average AC resistance.

Header carries the design provenance + the L(0) value the
engine produced so an LTspice user can spot-check by running
a 0.1 A AC analysis.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from typing import Optional

from pfc_inductor.export.curves import L_vs_I_table, flux_vs_current
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


def to_ltspice_subcircuit(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    name: str = "L_PFC",
    n_points: int = 25,
) -> str:
    """Return a complete LTspice ``.subckt`` text for the design.

    Output is a single multi-line string suitable for piping to
    a ``.lib`` file or pasting into LTspice's symbol editor.
    The subcircuit has two pins (``+``, ``-``); calling
    ``L_PFC`` from a schematic via ``X1 a b L_PFC`` slots the
    saturable model into a converter test bench.
    """
    n_turns = max(1, int(result.N_turns))
    I_max = max(_peak_current_A(result), 1e-3) * 1.5  # 1.5× headroom

    # Use flux-vs-current for the lookup; LTspice's `B` source
    # supports a `table()` PWL lookup natively.
    flux_table = flux_vs_current(
        material=material, core=core, n_turns=n_turns,
        I_max=I_max, n_points=n_points,
    )

    # Series resistance — engine's DC resistance + a guard for
    # AC resistance (use ratio if engine provides it).
    R_dc = float(getattr(result, "R_dc_ohm", 0.0) or 0.0)
    if R_dc <= 0 and hasattr(result, "losses"):
        R_dc = float(getattr(result.losses, "R_dc_ohm", 0.0) or 0.0)
    R_series = max(R_dc, 1e-6)

    L_nominal_H = (
        float(result.L_actual_uH) * 1e-6 if result.L_actual_uH else 0.0
    )

    header = _build_header(
        spec=spec, core=core, wire=wire, material=material,
        result=result, n_turns=n_turns, I_max=I_max,
        L_nominal_H=L_nominal_H, R_series=R_series,
    )

    table_pairs = ", ".join(
        f"{flux:.6e}, {I:.6f}"
        for I, flux in flux_table
    )

    body = textwrap.dedent(f"""\
        .subckt {name} p n
        * Internal flux node — driven by integral of v(p, n).
        * Current is recovered via the (flux → current) table.
        Bflux flux 0 V=idt(V(p, n) - I(Bcur) * {R_series:.6e}, 0)
        Bcur p n I=table(V(flux), {table_pairs})
        * Reference small-signal inductance (zero-bias):
        * L_ref = {L_nominal_H:.6e} H
        .ends {name}
    """).strip("\n")

    return f"{header}\n{body}\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_header(
    *, spec: Spec, core: Core, wire: Wire, material: Material,
    result: DesignResult, n_turns: int, I_max: float,
    L_nominal_H: float, R_series: float,
) -> str:
    """Comment block with provenance + design parameters."""
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return textwrap.dedent(f"""\
        * --------------------------------------------------------------
        * MagnaDesign — LTspice saturable-inductor subcircuit export
        * Generated: {timestamp}
        *
        * Topology     : {spec.topology}
        * Core         : {core.part_number} ({core.shape}, {material.name})
        * Wire         : {wire.id}
        * N turns      : {n_turns}
        * L (small-sig): {L_nominal_H * 1e6:.2f} uH
        * R_series     : {R_series * 1e3:.1f} mOhm
        * I_pk swept   : 0..{I_max:.2f} A
        * Rolloff      : {"yes" if material.rolloff is not None else "no (flat L)"}
        * --------------------------------------------------------------
    """).rstrip("\n")


def _peak_current_A(result: DesignResult) -> float:
    """Best-effort peak-current resolver — boost-CCM uses
    ``I_pk_max_A``, line-reactor uses ``I_line_pk_A``, buck uses
    a derived value. Never raises; returns 0.0 when nothing is
    set so the caller can fall back to a default sweep range."""
    for attr in ("I_pk_max_A", "I_line_pk_A", "I_pk_A"):
        val = getattr(result, attr, None)
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
    return 0.0
