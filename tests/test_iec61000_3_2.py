"""IEC 61000-3-2 Class D limits.

Cross-checked against the upstream calculations in
``../extrator_harmonicos/src/logic/iec.py`` (the project that runs on
real PDF test reports). Numbers in this file are *the same* numbers
that drive the lab's pass/fail decisions today.
"""
from __future__ import annotations

import math

import pytest

from pfc_inductor.standards import iec61000_3_2 as iec


# ---------------------------------------------------------------------------
# Factor / absolute limit tables
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n,expected_factor", [
    (3, 3.4), (5, 1.9), (7, 1.0), (9, 0.5), (11, 0.35),
])
def test_factor_per_watt_fixed_orders_match_table_3(n, expected_factor):
    assert iec.factor_per_watt_ma(n) == expected_factor


@pytest.mark.parametrize("n,expected_abs_a", [
    (3, 2.30), (5, 1.14), (7, 0.77), (9, 0.40), (11, 0.33),
])
def test_absolute_limit_fixed_orders_match_table_3(n, expected_abs_a):
    assert iec.absolute_limit_a(n) == expected_abs_a


@pytest.mark.parametrize("n", [13, 15, 17, 19, 21, 25, 39])
def test_factor_extension_4_0_decays_as_3_85_over_n(n):
    assert math.isclose(iec.factor_per_watt_ma(n, edition="4.0"),
                        3.85 / n, rel_tol=1e-9)


def test_factor_extension_5_0_uses_3_65():
    assert math.isclose(iec.factor_per_watt_ma(13, edition="5.0"),
                        3.65 / 13, rel_tol=1e-9)


@pytest.mark.parametrize("n", [13, 17, 21, 39])
def test_absolute_limit_extension_decays_as_2_25_over_n(n):
    assert math.isclose(iec.absolute_limit_a(n), 0.15 * 15 / n, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Per-power limit table
# ---------------------------------------------------------------------------
def test_class_d_limits_at_low_power_use_relative_factor():
    """At Pi=100 W the relative formula is below the absolute cap, so the
    limit is just factor·Pi/1000."""
    Pi = 100.0
    limits = iec.class_d_limits(Pi)
    # n=3: 3.4 mA/W * 100W / 1000 = 0.34 A
    assert math.isclose(limits[3], 0.34, abs_tol=1e-6)
    # n=5: 1.9 mA/W * 100W / 1000 = 0.19 A
    assert math.isclose(limits[5], 0.19, abs_tol=1e-6)


def test_class_d_limits_at_high_power_clamp_to_absolute():
    """At Pi=2000 W the relative formula exceeds the absolute caps, so
    the absolute caps win."""
    limits = iec.class_d_limits(2000.0)
    assert limits[3] == 2.30
    assert limits[5] == 1.14
    assert limits[7] == 0.77


def test_class_d_limits_match_upstream_extrator():
    """Cross-check our limits against the lab's reference implementation."""
    import sys
    upstream_path = "/Users/lgili/Documents/02 - Trabalho/extrator_harmonicos/src"
    if upstream_path not in sys.path:
        sys.path.insert(0, upstream_path)
    try:
        from logic.iec import compute_iec_limits as upstream
    except ImportError:
        pytest.skip("upstream extrator_harmonicos not on disk")
    for Pi in (75.0, 200.0, 400.0, 600.0, 1500.0):
        ours = iec.class_d_limits(Pi)
        theirs = upstream(Pi)
        for n in iec.ODD_HARMONICS:
            assert math.isclose(ours[n], theirs[n], rel_tol=1e-9), (
                f"diff at Pi={Pi}, n={n}: ours={ours[n]} vs upstream={theirs[n]}"
            )


# ---------------------------------------------------------------------------
# Compliance evaluation
# ---------------------------------------------------------------------------
def test_evaluate_compliance_passes_when_all_under_limits():
    Pi = 400.0
    # Halve every limit and feed those as harmonics — must pass.
    limits = iec.class_d_limits(Pi)
    measured = {n: lim * 0.5 for n, lim in limits.items()}
    rep = iec.evaluate_compliance(measured, Pi)
    assert rep.passes
    assert rep.margin_min_pct > 0
    assert all(c.passes for c in rep.checks)


def test_evaluate_compliance_fails_when_one_over():
    Pi = 400.0
    limits = iec.class_d_limits(Pi)
    measured = {n: lim * 0.5 for n, lim in limits.items()}
    measured[5] = limits[5] * 1.20    # 20% over the 5th-harmonic limit
    rep = iec.evaluate_compliance(measured, Pi)
    assert not rep.passes
    assert rep.limiting_harmonic == 5
    assert rep.margin_min_pct < 0


def test_evaluate_compliance_ignores_even_harmonics():
    """Even harmonics aren't part of Class D, so passing one in the dict
    doesn't break the check."""
    Pi = 200.0
    rep = iec.evaluate_compliance({2: 999.0, 3: 0.01, 5: 0.01}, Pi)
    assert rep.passes
    assert all(c.n in iec.ODD_HARMONICS for c in rep.checks)
