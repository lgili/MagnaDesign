"""Tests for ``pfc_inductor.physics.leakage``.

The leakage estimator is empirical (no closed-form derivation).
These tests pin the published vendor app-note ranges so future
table edits surface as real changes.

Reference numbers:
- TI SLUA535: typical sandwich winding ≈ 0.3 % of Lp.
- Coilcraft Doc 158: simple P-S layout ≈ 1.5 % of Lp.
- Würth ANP034: poor coupling ≈ 4 % of Lp.
"""

from __future__ import annotations

import pytest

from pfc_inductor.physics import leakage

# ---------------------------------------------------------------------------
# Headline estimator
# ---------------------------------------------------------------------------


def test_zero_lp_returns_zero() -> None:
    assert leakage.leakage_estimate_uH(0.0) == 0.0


def test_single_layer_returns_zero() -> None:
    """Single-layer designs have negligible geometric leakage —
    the (n_layers − 1) / n_layers term zeros out."""
    assert leakage.leakage_estimate_uH(100.0, n_layers=1) == 0.0


def test_sandwich_two_layer_matches_ti_app_note() -> None:
    """TI SLUA535 sandwich design @ 100 µH primary should land
    around 0.25 % of Lp (one layer of leakage between halves)."""
    L_leak = leakage.leakage_estimate_uH(
        100.0,
        layout="sandwich",
        n_layers=2,
    )
    # 100 · 0.005 · (1/2) = 0.25 µH
    assert L_leak == pytest.approx(0.25, rel=0.05)


def test_simple_ps_two_layer_matches_published() -> None:
    """Simple P-S layout — the textbook 1–2 % of Lp band."""
    L_leak = leakage.leakage_estimate_uH(
        100.0,
        layout="simple",
        n_layers=2,
    )
    # 100 · 0.020 · (1/2) = 1.0 µH (exactly 1 % of Lp)
    assert L_leak == pytest.approx(1.0, rel=0.05)


def test_poor_coupling_caps_at_few_percent() -> None:
    """Poorly coupled designs — bobbin overflow, mismatched
    widths — sit around 4 % of Lp at 2 layers."""
    L_leak = leakage.leakage_estimate_uH(
        100.0,
        layout="poor",
        n_layers=2,
    )
    assert L_leak == pytest.approx(2.0, rel=0.05)


def test_more_layers_increase_leakage() -> None:
    """More layers (deeper bobbin) → larger leakage. The factor
    (n−1)/n grows monotonically."""
    L_2 = leakage.leakage_estimate_uH(100.0, layout="sandwich", n_layers=2)
    L_4 = leakage.leakage_estimate_uH(100.0, layout="sandwich", n_layers=4)
    L_8 = leakage.leakage_estimate_uH(100.0, layout="sandwich", n_layers=8)
    assert L_2 < L_4 < L_8


def test_unknown_layout_falls_back_to_simple() -> None:
    """Unknown layouts use the conservative 'simple' value
    (over-estimate snubber loss → safer FET selection)."""
    L_unknown = leakage.leakage_estimate_uH(
        100.0,
        layout="exotic-bifilar-litz",
        n_layers=2,
    )
    L_simple = leakage.leakage_estimate_uH(
        100.0,
        layout="simple",
        n_layers=2,
    )
    assert L_unknown == pytest.approx(L_simple, rel=1e-9)


def test_bifilar_lowest_in_table() -> None:
    """Bifilar windings have the smallest practical leakage."""
    leakages = {
        layout: leakage.leakage_estimate_uH(
            100.0,
            layout=layout,
            n_layers=2,
        )
        for layout in ("bifilar", "sandwich", "simple", "poor")
    }
    assert leakages["bifilar"] < leakages["sandwich"] < leakages["simple"] < leakages["poor"]


# ---------------------------------------------------------------------------
# Table accessors
# ---------------------------------------------------------------------------


def test_k_layout_lookup_case_insensitive() -> None:
    assert leakage.k_layout("Sandwich") == leakage.k_layout("sandwich")
    assert leakage.k_layout("  SIMPLE  ") == leakage.k_layout("simple")


def test_k_layout_unknown_returns_simple_value() -> None:
    assert leakage.k_layout("nonsense") == leakage.K_LAYOUT_TABLE["simple"]


def test_shape_correction_default_one_x() -> None:
    """v1 ships an empty per-shape correction table — every
    shape lands at 1.0×."""
    assert leakage.shape_correction("ee_25_13_7") == pytest.approx(1.0)
    assert leakage.shape_correction("efd_30_15_9") == pytest.approx(1.0)
    assert leakage.shape_correction(None) == pytest.approx(1.0)


def test_uncertainty_is_documented() -> None:
    """The report layer emits a ``±X %`` caveat next to the
    leakage estimate. v1 ships ±30 %."""
    assert leakage.leakage_uncertainty_pct() == pytest.approx(30.0)
