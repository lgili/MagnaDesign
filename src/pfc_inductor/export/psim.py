"""PSIM saturable-inductor fragment.

PSIM's "Saturable Inductor" element parameter set takes a
flux-current table as a sequence of ``flux<sub>i</sub>,
i<sub>i</sub>`` pairs (one per line). This emitter produces:

1. A header comment block matching the LTspice exporter.
2. A property block that the user pastes into PSIM's parameter
   dialog for the Saturable Inductor element. PSIM's text-based
   workflow uses ``# parameter = value`` lines; the lookup table
   uses ``flux-current = i_1 lambda_1 ; i_2 lambda_2 ; …``.

The fragment is a textual contract — PSIM doesn't have a
universal text-import format like LTspice's ``.lib``, so the
file is intended for paste-into-element-property-dialog usage.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

from pfc_inductor.export.curves import flux_vs_current
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


def to_psim_fragment(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    n_points: int = 25,
) -> str:
    """Return a PSIM-importable saturable-inductor fragment."""
    n_turns = max(1, int(result.N_turns))
    I_max = max(_peak_current_A(result), 1e-3) * 1.5

    flux_table = flux_vs_current(
        material=material,
        core=core,
        n_turns=n_turns,
        I_max=I_max,
        n_points=n_points,
    )

    R_dc = float(getattr(result, "R_dc_ohm", 0.0) or 0.0)
    if R_dc <= 0 and hasattr(result, "losses"):
        R_dc = float(getattr(result.losses, "R_dc_ohm", 0.0) or 0.0)

    L_nominal_uH = float(result.L_actual_uH or 0.0)

    header = _build_header(
        spec=spec,
        core=core,
        wire=wire,
        material=material,
        n_turns=n_turns,
        L_uH=L_nominal_uH,
        I_max=I_max,
    )

    pairs_block = "\n".join(f"  {I:.6f}  {flux:.6e}" for I, flux in flux_table)

    body = textwrap.dedent(f"""\
        # PSIM Saturable Inductor — paste into element parameters

        Name = SatL_PFC
        Nominal_Inductance_uH = {L_nominal_uH:.3f}
        DC_Resistance_Ohm = {R_dc:.6f}
        Initial_Current_A = 0
        Flux_Current_Table_Format = "current_A flux_Wb"

        # Table: current [A]  flux linkage [Wb]
        Flux_Current_Table = (
        {pairs_block}
        )
    """)

    return f"{header}\n{body}"


# ---------------------------------------------------------------------------
# Helpers (mirrors of ltspice.py — kept inline so the modules stay independent)
# ---------------------------------------------------------------------------
def _build_header(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    n_turns: int,
    L_uH: float,
    I_max: float,
) -> str:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    return textwrap.dedent(f"""\
        # --------------------------------------------------------------
        # MagnaDesign — PSIM Saturable-Inductor fragment export
        # Generated: {timestamp}
        #
        # Topology     : {spec.topology}
        # Core         : {core.part_number} ({core.shape}, {material.name})
        # Wire         : {wire.id}
        # N turns      : {n_turns}
        # L (small-sig): {L_uH:.2f} uH
        # I_pk swept   : 0..{I_max:.2f} A
        # Rolloff      : {"yes" if material.rolloff is not None else "no (flat L)"}
        # --------------------------------------------------------------
    """).rstrip("\n")


def _peak_current_A(result: DesignResult) -> float:
    for attr in ("I_pk_max_A", "I_line_pk_A", "I_pk_A"):
        val = getattr(result, attr, None)
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
    return 0.0
