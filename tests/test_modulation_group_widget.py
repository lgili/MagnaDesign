"""ModulationGroup widget — Spec-drawer sub-form for the VFD band.

Covers:

- Default state (master toggle off, body hidden, ``to_modulation``
  returns None — backward-compat for legacy specs).
- Toggle reveals the body and ``to_modulation`` returns a populated
  :class:`FswModulation`.
- ``from_modulation`` round-trip — same model in and out.
- Profile combo gates the RPM-band sub-block visibility.
- ``changed`` signal fires on every editable control + the master
  toggle.
- Round-trip through SpecPanel.get_spec / set_spec preserves the
  band.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture
def group(app):
    from pfc_inductor.ui.widgets.modulation_group import ModulationGroup
    g = ModulationGroup()
    yield g
    g.deleteLater()


# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------
def test_default_state_is_disabled(group) -> None:
    assert not group.is_enabled()
    assert group.to_modulation() is None
    # ``isHidden()`` returns the widget's own visibility setting
    # independent of whether the parent is shown — required in
    # tests where the group isn't mounted in a top-level window.
    assert group._body.isHidden()


def test_toggle_on_reveals_body_and_returns_modulation(group) -> None:
    group._chk_enabled.setChecked(True)
    assert group.is_enabled()
    assert not group._body.isHidden()
    mod = group.to_modulation()
    assert mod is not None
    # Sane defaults for a compressor-VFD design.
    assert mod.fsw_min_kHz == pytest.approx(4.0)
    assert mod.fsw_max_kHz == pytest.approx(25.0)
    assert mod.profile == "uniform"
    assert mod.n_eval_points == 5


def test_toggle_off_returns_none(group) -> None:
    """The master toggle is the kill-switch — even with the
    profile combo / spinboxes populated, the unchecked state
    returns ``None`` so the engine routes through the single-
    point path."""
    group._chk_enabled.setChecked(True)
    group._sp_fsw_min.setValue(8.0)
    group._chk_enabled.setChecked(False)
    assert group.to_modulation() is None


# ---------------------------------------------------------------------------
# Profile combo
# ---------------------------------------------------------------------------
def test_profile_combo_has_three_choices(group) -> None:
    """uniform / triangular_dither / rpm_band — keys must match
    ``ModulationProfile`` literal."""
    keys = {
        group._cmb_profile.itemData(i)
        for i in range(group._cmb_profile.count())
    }
    assert keys == {"uniform", "triangular_dither", "rpm_band"}


def test_rpm_block_hidden_for_uniform_profile(group) -> None:
    group._chk_enabled.setChecked(True)
    group._select_profile("uniform")
    # _refresh_rpm_visibility runs from _on_profile_changed
    # which fires currentIndexChanged from _select_profile.
    group._refresh_rpm_visibility()
    assert group._rpm_box.isHidden()


def test_rpm_block_revealed_for_rpm_band_profile(group) -> None:
    group._chk_enabled.setChecked(True)
    group._select_profile("rpm_band")
    group._refresh_rpm_visibility()
    assert not group._rpm_box.isHidden()


def test_rpm_band_derives_fsw_from_rpm_inputs(group) -> None:
    """Changing the RPM band updates the fsw spinboxes via the
    rpm_to_fsw helper. Tests the live derivation that lets the
    user enter values they know (RPM range)."""
    group._chk_enabled.setChecked(True)
    group._select_profile("rpm_band")
    group._sp_pole_pairs.setValue(2)
    group._sp_rpm_min.setValue(1500)
    group._sp_rpm_max.setValue(4500)
    # Implementation pushes derived fsw into the (now disabled)
    # spinboxes. With K_CARRIER_RATIO=200 + pole_pairs=2:
    #   rpm × poles / 60 × 200 / 1000  →  rpm / 150
    # 1500 RPM → 10 kHz ; 4500 RPM → 30 kHz.
    group._derive_fsw_from_rpm()
    assert group._sp_fsw_min.value() == pytest.approx(10.0)
    assert group._sp_fsw_max.value() == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# from_modulation reverse mapping
# ---------------------------------------------------------------------------
def test_from_modulation_with_none_resets_to_disabled(group) -> None:
    group._chk_enabled.setChecked(True)
    group.from_modulation(None)
    assert not group.is_enabled()
    assert group._body.isHidden()


def test_from_modulation_populates_every_field(group) -> None:
    from pfc_inductor.models import FswModulation
    mod = FswModulation(
        fsw_min_kHz=8.0, fsw_max_kHz=22.0,
        profile="triangular_dither", n_eval_points=7,
    )
    group.from_modulation(mod)
    assert group.is_enabled()
    out = group.to_modulation()
    assert out.fsw_min_kHz == pytest.approx(8.0)
    assert out.fsw_max_kHz == pytest.approx(22.0)
    assert out.profile == "triangular_dither"
    assert out.n_eval_points == 7


# ---------------------------------------------------------------------------
# changed signal
# ---------------------------------------------------------------------------
def test_changed_fires_on_master_toggle(group, qtbot=None) -> None:
    seen: list[int] = []
    group.changed.connect(lambda: seen.append(1))
    group._chk_enabled.setChecked(True)
    assert seen, "changed never fired on toggle"


def test_changed_fires_on_field_edit(group) -> None:
    group._chk_enabled.setChecked(True)
    seen: list[int] = []
    group.changed.connect(lambda: seen.append(1))
    group._sp_fsw_min.setValue(7.5)
    assert seen, "changed never fired on spinbox edit"


# ---------------------------------------------------------------------------
# Integration with SpecPanel
# ---------------------------------------------------------------------------
def test_spec_panel_round_trip_through_modulation(app) -> None:
    """End-to-end: SpecPanel.get_spec returns a Spec without the
    band by default, gains a band when the toggle flips, and
    set_spec restores both shapes correctly."""
    from pfc_inductor.models import FswModulation
    from pfc_inductor.ui.spec_panel import SpecPanel

    panel = SpecPanel()
    try:
        # Default — backward-compat for legacy specs.
        spec0 = panel.get_spec()
        assert spec0.fsw_modulation is None

        # Round-trip a banded spec through set_spec → get_spec.
        m = FswModulation(
            fsw_min_kHz=10, fsw_max_kHz=30,
            profile="rpm_band", n_eval_points=4,
            rpm_min=1500, rpm_max=4500, pole_pairs=2,
        )
        spec_in = spec0.model_copy(update={"fsw_modulation": m})
        panel.set_spec(spec_in)
        spec_out = panel.get_spec()
        assert spec_out.fsw_modulation is not None
        assert spec_out.fsw_modulation.profile == "rpm_band"
        assert spec_out.fsw_modulation.rpm_min == 1500
        assert spec_out.fsw_modulation.pole_pairs == 2
    finally:
        panel.deleteLater()


def test_spec_panel_changed_signal_propagates(app) -> None:
    """A modulation edit must trigger SpecPanel's ``changed``
    so the dirty-tracking pill flips and the recalc fires."""
    from pfc_inductor.ui.spec_panel import SpecPanel

    panel = SpecPanel()
    try:
        seen: list[int] = []
        panel.changed.connect(lambda: seen.append(1))
        panel.modulation_group._chk_enabled.setChecked(True)
        assert seen, "SpecPanel.changed never fired on modulation toggle"
    finally:
        panel.deleteLater()
