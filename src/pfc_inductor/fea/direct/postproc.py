"""Parse GetDP's post-operation output into a typed result.

The DC magnetostatic ``.pro`` template emits three things:

1. ``energy_2d.txt`` — total energy per unit depth integrated over
   the full 2-D domain (``W_2d`` in J/m).
2. ``energy_core.txt`` / ``energy_gap.txt`` — same, restricted to
   the core / air-gap regions (diagnostic).
3. ``B_field.pos`` / ``Magb.pos`` / ``H_field.pos`` /
   ``loss_density.pos`` / ``A_potential.pos`` — Gmsh ASCII view
   files for matplotlib rendering downstream.

GetDP's "Table" format for global scalars writes one number per
line; we just read the first valid float. The ``.pos`` files are
left on disk — the runner hands them to ``pos_renderer`` for PNG
generation, same code path the FEMMT backend uses.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

_LOG = logging.getLogger(__name__)


def parse_scalar_table(path: Path) -> Optional[float]:
    """Read a GetDP ``Format Table`` scalar — last numeric column.

    GetDP writes one line per ``OnGlobal`` integral, formatted as
    ``<region_index> <value>``. The last column is always the
    integrand value (even when the integral is exactly 0); the
    first column is just the region id from the ``In Group``
    clause.

    Returns ``None`` if the file is missing or empty; ``0.0`` for
    a valid result of zero (avoids spurious warnings on closed-
    core / no-gap geometries where ``energy_gap`` is legitimately
    zero).
    """
    if not path.is_file():
        _LOG.warning("scalar table missing: %s", path)
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = re.split(r"\s+", stripped)
        if not tokens:
            continue
        # Last token = the integral value. First token is the
        # region id (could be zero for some GetDP versions when
        # there's only one region in the group).
        try:
            return float(tokens[-1])
        except ValueError:
            continue
    _LOG.warning("scalar table %s had no parseable float", path)
    return None


def parse_pos_max_norm(path: Path) -> Optional[float]:
    """Read a Gmsh ``.pos`` file and return the maximum scalar value.

    For ``Magb.pos`` (``|B|``) this yields the peak flux density —
    the saturation-check number. Gmsh's ASCII ``.pos`` format
    encodes each element's value as the last token on its data
    line; a regex sweep is faster than a full parser and good
    enough since we only need the max.

    Returns ``None`` on missing file. The runner reports the peak
    as 0.0 in that case rather than failing the whole result.
    """
    if not path.is_file():
        return None
    max_val = 0.0
    found = False
    pattern = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # ``.pos`` element data lines start with a tag like
            # ``ST(`` or ``SQ(`` and end with a series of values.
            if not (line.startswith(("ST(", "SQ(", "SS(", "SH(", "SI("))):
                continue
            # The last numeric tokens are the values at each node;
            # for a scalar view ``Magb`` they're identical.
            matches = pattern.findall(line)
            for tok in matches[-4:]:  # check last few tokens only
                try:
                    v = abs(float(tok))
                    if v > max_val:
                        max_val = v
                        found = True
                except ValueError:
                    continue
    return max_val if found else None


def compute_inductance_uH(
    *,
    energy_2d_Jm: float,
    depth_m: float,
    current_A: float,
) -> float:
    """``L = 2·W / I²`` — energy method, depth-scaled to 3-D.

    Returns 0.0 (with a log warning) for non-positive current to
    avoid divide-by-zero crashes; the caller should treat that as
    a malformed input rather than a real measurement.
    """
    if current_A <= 0.0:
        _LOG.warning("compute_inductance_uH called with I=%s; returning 0", current_A)
        return 0.0
    energy_total_J = energy_2d_Jm * depth_m
    L_H = 2.0 * energy_total_J / (current_A * current_A)
    return L_H * 1e6
