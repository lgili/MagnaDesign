"""Leakage-inductance estimator for coupled-inductor designs.

The leakage inductance ``L_leak`` is the part of the primary
flux that doesn't link the secondary winding. In a flyback it
becomes the snubber's job: the energy stored in ``L_leak``
during the ON interval can't transfer through the magnetising
path on switch-off, so it gets dumped into an RCD clamp on the
primary. Typical loss budget: 3–8 % of Pout for a well-coupled
sandwich winding, 10–15 % for a single-layer P-S layout.

There's no closed-form expression for ``L_leak`` from first
principles — it depends on the full 3-D winding geometry. What
the industry uses (TI SLUA535, Coilcraft Doc 158, Würth ANP034)
is an empirical rule:

    L_leak ≈ Lp · k_layout · (n_layers − 1) / n_layers

with ``k_layout`` calibrated per winding strategy:

    | layout       | k_layout | typical L_leak / Lp |
    |--------------|----------|---------------------|
    | bifilar      |   0.002  | 0.1 – 0.2 %         |
    | sandwich     |   0.005  | 0.2 – 0.5 %         |
    | simple P-S   |   0.020  | 1 – 2 %             |
    | poor coupling|   0.040  | 3 – 5 %             |

The (n_layers − 1) / n_layers term penalises designs with many
primary layers — each additional layer adds another segment of
flux that doesn't link the secondary. Single-layer designs
cancel the term to zero, which is the bifilar limit.

Per-shape calibration (EFD vs EE vs RM) is small enough that
this module ships a single table; if a future project needs
shape-specific corrections we'll add a lookup keyed on
``core_shape``.

References:
- TI SLUA535 — flyback transformer design notes, Section 4
  (leakage inductance estimation).
- Coilcraft Doc 158 — interleaved winding design.
- Würth Elektronik ANP034 — leakage inductance in flyback
  transformers.
- McLyman, *Transformer and Inductor Design Handbook*, Ch. 13.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Empirical k_layout table
# ---------------------------------------------------------------------------

# Strategy → multiplier on Lp for the leakage estimate.
# Calibrated against the published vendor app-note numbers.
K_LAYOUT_TABLE: dict[str, float] = {
    "bifilar": 0.002,  # ideal — only used on small RM cores
    "sandwich": 0.005,  # P/2 → S → P/2; the modern default
    "interleaved": 0.005,  # synonym for sandwich
    "simple": 0.020,  # P then S, no interleaving
    "p-s": 0.020,  # synonym for simple
    "poor": 0.040,  # bobbin overflow, gaps, mismatched widths
}

# Per-shape correction factors (multiplicative on the base table).
# Empty for v1 — every shape uses 1.0×. Reserved for the future
# calibration change once we have measurement data.
SHAPE_CORRECTION: dict[str, float] = {
    # "ee_25_13_7":  1.10,   (placeholder — populate when data lands)
    # "efd_25_13_9": 0.90,
}


def k_layout(layout: str) -> float:
    """Look up the empirical multiplier for a winding strategy.

    Unknown strategies fall back to the conservative ``"simple"``
    value (2 %) — better to over-estimate snubber loss than to
    under-spec the snubber and burn the FET in the field.
    """
    if not layout:
        return K_LAYOUT_TABLE["simple"]
    key = layout.strip().lower()
    return K_LAYOUT_TABLE.get(key, K_LAYOUT_TABLE["simple"])


def shape_correction(core_shape: str | None) -> float:
    """Per-shape multiplier on the base ``k_layout`` value.

    Defaults to 1.0× for any unmapped shape; the table is
    intentionally sparse until vendor measurement data backs it
    up.
    """
    if not core_shape:
        return 1.0
    key = core_shape.strip().lower().replace(" ", "_")
    return SHAPE_CORRECTION.get(key, 1.0)


# ---------------------------------------------------------------------------
# Headline estimator
# ---------------------------------------------------------------------------


def leakage_estimate_uH(
    Lp_uH: float,
    *,
    layout: str = "sandwich",
    n_layers: int = 2,
    core_shape: str | None = None,
) -> float:
    """Empirical primary leakage inductance, in microhenries.

    The formula is::

        L_leak = Lp · k_layout · (n_layers − 1) / n_layers · k_shape

    Returns 0 for ``Lp_uH ≤ 0`` (no primary inductance to leak)
    or ``n_layers ≤ 1`` (single-layer designs have negligible
    geometric leakage; copper-resistive flux still exists but
    it's well under 0.1 %).

    Uncertainty: ±30 % on the central estimate. The number is
    used to size the RCD snubber and to surface ``P_snubber`` in
    the loss table. A design that looks marginal on the snubber
    budget should be re-checked with bench measurements before
    going to production.
    """
    if Lp_uH <= 0 or n_layers <= 1:
        return 0.0
    k = k_layout(layout)
    correction = shape_correction(core_shape)
    geometry = (n_layers - 1) / n_layers
    return Lp_uH * k * geometry * correction


def leakage_uncertainty_pct() -> float:
    """Central uncertainty on the leakage estimate.

    Returned as a positive percentage; the report layer reads
    this and emits a "±30 %" caveat alongside the L_leak number
    so the engineer doesn't treat the estimate as gospel.
    """
    return 30.0
