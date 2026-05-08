"""L(I) and flux(I) tables — the simulator-friendly view of
the rolloff curve.

The engine's rolloff function takes ``H`` (in Oersted) and
returns a permeability fraction; circuit simulators want the
table indexed by *current*. This module bridges them: sweep
``I`` from 0 to ``I_max``, compute ``H = N·I/le`` at each point,
look up ``μ_frac``, and build the L(I) (or flux λ(I)) table.

The result is a list of ``(I_A, value)`` tuples — caller picks
the format. Three exporters consume the table:

- LTspice: as ``B``-source ``flux=table(i, …)`` literal pairs.
- PSIM: as ``flux-current`` parameter rows.
- Modelica: as a ``Modelica.Blocks.Tables.CombiTable1D`` table
  parameter.
"""

from __future__ import annotations

from pfc_inductor.models import Core, Material
from pfc_inductor.physics.rolloff import (
    H_from_NI,
    inductance_uH,
    mu_pct,
)


def L_vs_I_table(
    *,
    material: Material,
    core: Core,
    n_turns: int,
    I_max: float,
    n_points: int = 20,
) -> list[tuple[float, float]]:
    """Return ``[(I_A, L_H), ...]`` over ``[0, I_max]``.

    Parameters
    ----------
    material : :class:`Material`
        Carries the rolloff coefficients; ferrites without
        rolloff data return a flat-L table.
    core : :class:`Core`
        Carries ``AL_nH`` and ``le_mm``.
    n_turns : int
        Winding turn count.
    I_max : float
        Sweep upper bound (A). Always evaluates ``[0, I_max]``
        inclusive.
    n_points : int
        Number of points (default 20). ≥ 2.
    """
    n_points = max(2, int(n_points))
    if I_max <= 0 or core.AL_nH <= 0 or n_turns <= 0:
        # Degenerate — return a flat 0-current entry so the
        # caller can still emit a valid table.
        return [(0.0, 0.0)]

    table: list[tuple[float, float]] = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        I_A = frac * I_max
        H_Oe = H_from_NI(n_turns, I_A, core.le_mm, units="Oe")
        mu = mu_pct(material, H_Oe)
        L_H = inductance_uH(n_turns, core.AL_nH, mu) * 1e-6
        table.append((round(I_A, 6), round(L_H, 12)))
    return table


def flux_vs_current(
    *,
    material: Material,
    core: Core,
    n_turns: int,
    I_max: float,
    n_points: int = 20,
) -> list[tuple[float, float]]:
    """Return ``[(I_A, λ_Wb), ...]`` over ``[0, I_max]``.

    Flux linkage λ = ∫₀^I L(i) di — accumulated via trapezoid
    on the L(I) table. Some simulators (PSIM saturable inductor,
    Modelica FluxTubes) take flux directly; the trapezoidal rule
    is a one-line numerical integration that's exact when L is
    piecewise linear (it isn't, but the residual is < 1 %).
    """
    L_table = L_vs_I_table(
        material=material,
        core=core,
        n_turns=n_turns,
        I_max=I_max,
        n_points=n_points,
    )
    flux: list[tuple[float, float]] = [(0.0, 0.0)]
    cumulative = 0.0
    for k in range(1, len(L_table)):
        I_prev, L_prev = L_table[k - 1]
        I_curr, L_curr = L_table[k]
        # Trapezoid on dλ/dI = L(I).
        cumulative += 0.5 * (L_prev + L_curr) * (I_curr - I_prev)
        flux.append((round(I_curr, 6), round(cumulative, 12)))
    return flux
