"""AcousticCard widget + AnalisePage integration tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


@pytest.fixture(scope="module")
def reference_inputs():
    """Feasible 600 W boost-PFC with Magnetics 60 µ HighFlux —
    quiet enough for the model to land below 30 dB(A) typical."""
    from pfc_inductor.data_loader import (
        ensure_user_data, load_cores, load_materials, load_wires,
    )
    from pfc_inductor.design import design as run_design
    from pfc_inductor.models import Spec

    ensure_user_data()
    mats = load_materials()
    cores = load_cores()
    wires = load_wires()
    spec = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=65, ripple_pct=20, T_amb_C=40,
    )
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    result = run_design(spec, core, wire, mat)
    return spec, core, wire, mat, result


# ---------------------------------------------------------------------------
# AcousticCard standalone behaviour
# ---------------------------------------------------------------------------
def test_acoustic_card_initial_state_hidden(app) -> None:
    """Card starts hidden — the parent doesn't know yet whether
    the engine has populated the inputs the model needs."""
    from pfc_inductor.ui.dashboard.cards.acoustic_card import (
        AcousticCard,
    )
    card = AcousticCard()
    try:
        assert card.isHidden()
        assert card._body._hero.text() == "—"
    finally:
        card.deleteLater()


def test_acoustic_card_reveals_on_valid_design(
    app, reference_inputs,
) -> None:
    """Engine reports B_pk + ripple > 0 → card reveals + hero
    label populated with SPL value."""
    from pfc_inductor.ui.dashboard.cards.acoustic_card import (
        AcousticCard,
    )

    spec, core, wire, mat, result = reference_inputs
    card = AcousticCard()
    try:
        card.update_from_design(result, spec, core, wire, mat)
        assert not card.isHidden()
        # Hero has the canonical "X.X dB(A) @ Y.Y kHz" shape.
        text = card._body._hero.text()
        assert "dB(A)" in text
        assert "kHz" in text
        # Dominant mechanism + headroom both populated.
        assert card._body._dominant.text().startswith("Dominant")
        assert "Headroom" in card._body._headroom.text()
    finally:
        card.deleteLater()


def test_acoustic_card_hides_for_zero_design(app, reference_inputs) -> None:
    """Engine with no measurable B_pk / ripple → estimator
    returns ``mechanism='none'`` → card hides rather than show
    a misleading 0 dB(A)."""
    from pfc_inductor.ui.dashboard.cards.acoustic_card import (
        AcousticCard,
    )

    spec, core, wire, mat, _ = reference_inputs

    class _ZeroResult:
        B_pk_T = 0.0
        I_ripple_pk_pk_A = 0.0
        n_layers = 1

    card = AcousticCard()
    try:
        card.update_from_design(
            _ZeroResult(), spec, core, wire, mat,  # type: ignore[arg-type]
        )
        assert card.isHidden()
    finally:
        card.deleteLater()


def test_acoustic_card_clear_resets_state(app, reference_inputs) -> None:
    from pfc_inductor.ui.dashboard.cards.acoustic_card import (
        AcousticCard,
    )

    spec, core, wire, mat, result = reference_inputs
    card = AcousticCard()
    try:
        card.update_from_design(result, spec, core, wire, mat)
        assert not card.isHidden()
        card.clear()
        assert card.isHidden()
        assert card._body._hero.text() == "—"
    finally:
        card.deleteLater()


def test_acoustic_card_table_lists_contributors(
    app, reference_inputs,
) -> None:
    """Per-mechanism table shows one row per non-inf contributor."""
    from pfc_inductor.ui.dashboard.cards.acoustic_card import (
        AcousticCard,
    )

    spec, core, wire, mat, result = reference_inputs
    card = AcousticCard()
    try:
        card.update_from_design(result, spec, core, wire, mat)
        # At least the magnetostriction row must show up.
        assert card._body._table.rowCount() >= 1
        # Each row has both columns populated.
        for r in range(card._body._table.rowCount()):
            assert card._body._table.item(r, 0).text()
            cell = card._body._table.item(r, 1)
            assert cell is not None
            assert "dB(A)" in cell.text()
    finally:
        card.deleteLater()


# ---------------------------------------------------------------------------
# AnalisePage integration
# ---------------------------------------------------------------------------
def test_analise_page_mounts_acoustic_card(app) -> None:
    from pfc_inductor.ui.dashboard.cards.acoustic_card import AcousticCard
    from pfc_inductor.ui.workspace.analise_page import AnalisePage

    page = AnalisePage()
    try:
        assert hasattr(page, "card_acoustic")
        assert isinstance(page.card_acoustic, AcousticCard)
    finally:
        page.deleteLater()


def test_analise_page_acoustic_card_in_batch_loop(
    app, reference_inputs,
) -> None:
    """``update_from_design`` calls ``card_acoustic.update_from_design``
    via the ``_cards`` batch loop — verifies the card is
    populated end-to-end through the page."""
    from pfc_inductor.ui.workspace.analise_page import AnalisePage

    spec, core, wire, mat, result = reference_inputs
    page = AnalisePage()
    try:
        page.update_from_design(result, spec, core, wire, mat)
        assert not page.card_acoustic.isHidden()
        assert "dB(A)" in page.card_acoustic._body._hero.text()
    finally:
        page.deleteLater()
