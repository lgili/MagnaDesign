"""DC bias rolloff sanity tests."""

from pfc_inductor.models import Material, RolloffParams, SteinmetzParams
from pfc_inductor.physics.rolloff import H_from_NI, inductance_uH, mu_pct


def make_material(rolloff: RolloffParams | None = None) -> Material:
    return Material(
        id="t", vendor="t", family="t", name="t", type="powder",
        mu_initial=60, Bsat_25C_T=1.0, Bsat_100C_T=0.9,
        steinmetz=SteinmetzParams(Pv_ref_mWcm3=100, alpha=1.4, beta=2.5),
        rolloff=rolloff,
    )


def test_no_rolloff_returns_full_mu():
    m = make_material(rolloff=None)
    assert mu_pct(m, 0.0) == 1.0
    assert mu_pct(m, 1000.0) == 1.0


def test_rolloff_drops_with_high_field():
    m = make_material(RolloffParams(a=0.01, b=0.01, c=1.13))
    mu_low = mu_pct(m, 1.0)
    mu_high = mu_pct(m, 500.0)
    assert mu_low > 0.95, f"At low H mu should be near 1, got {mu_low}"
    assert mu_high < 0.1, f"At high H mu should be heavily rolled off, got {mu_high}"


def test_rolloff_kool_mu_60_signature():
    """Calibrated to ~50% rolloff at H~110 Oe (Kool Mu 60u published curve)."""
    m = make_material(RolloffParams(a=0.01, b=0.01, c=1.13))
    mu_at_110 = mu_pct(m, 110.0)
    assert 0.4 < mu_at_110 < 0.6, f"Expected ~50% at 110 Oe, got {mu_at_110*100:.1f}%"


def test_H_from_NI_oersted_units():
    # H = N*I/le_meters, then convert to Oe (1 A/m = 0.01257 Oe)
    H = H_from_NI(100, 1.0, 100.0, units="Oe")  # 100 turns * 1A / 0.1m = 1000 A/m
    assert 12.0 < H < 13.0, f"H should be ~12.57 Oe, got {H}"


def test_inductance_with_rolloff():
    L_full = inductance_uH(50, 75, 1.0)
    L_half = inductance_uH(50, 75, 0.5)
    assert abs(L_full - 187.5) < 0.01
    assert abs(L_half - 93.75) < 0.01
