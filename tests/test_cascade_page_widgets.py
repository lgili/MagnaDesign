"""Tests for the redesigned `CascadePage` UI surfaces.

Covers the widgets added in the GUI rebuild: spec strip,
run-config card, 4-tier progress grid, stats card, richer
top-N table column reveal, and the new `selection_applied`
signal that lets MainWindow promote a cascade winner without
leaving the page.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from pfc_inductor.models import Spec
from pfc_inductor.optimize.cascade import CandidateRow


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


def _spec() -> Spec:
    return Spec(
        topology="boost_ccm",
        Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
        Vout_V=400.0, Pout_W=800.0, eta=0.97,
        f_sw_kHz=65.0, ripple_pct=30.0,
        T_amb_C=40.0, T_max_C=100.0, Ku_max=0.40, Bsat_margin=0.20,
    )


# ─── _SpecStrip ────────────────────────────────────────────────────


def test_spec_strip_displays_topology_pout_voltages(app):
    from pfc_inductor.ui.workspace.cascade_page import _SpecStrip

    strip = _SpecStrip()
    strip.update_from_spec(_spec())
    assert strip._fields["topology"].text() == "boost_ccm"
    assert "800" in strip._fields["Pout"].text()
    assert "85" in strip._fields["Vin"].text() and "265" in strip._fields["Vin"].text()
    assert "400" in strip._fields["Vout"].text()
    assert "65" in strip._fields["fsw"].text()


def test_spec_strip_handles_none_spec(app):
    from pfc_inductor.ui.workspace.cascade_page import _SpecStrip

    strip = _SpecStrip()
    strip.update_from_spec(None)
    for label in strip._fields.values():
        assert label.text() == "—"


def test_spec_strip_passive_choke_blanks_vout(app):
    """Passive choke has no DC bus; the Vout field shows ``—``."""
    from pfc_inductor.ui.workspace.cascade_page import _SpecStrip

    strip = _SpecStrip()
    spec = _spec().model_copy(update={"topology": "passive_choke"})
    strip.update_from_spec(spec)
    assert strip._fields["Vout"].text() == "—"


# ─── _RunConfigCard ────────────────────────────────────────────────


def test_run_config_card_default_values(app):
    """Sane defaults: Tier 2 sample = 50, Tier 3 = 0 (off), workers ≥ 1."""
    from pfc_inductor.ui.workspace.cascade_page import _RunConfigCard

    cfg = _RunConfigCard()
    config = cfg.to_cascade_config()
    assert config.tier2_top_k == 50
    assert config.tier3_top_k == 0
    assert cfg.workers() >= 1


def test_run_config_card_emits_change_signal(app):
    from pfc_inductor.ui.workspace.cascade_page import _RunConfigCard

    cfg = _RunConfigCard()
    fired: list[None] = []
    cfg.config_changed.connect(lambda: fired.append(None))
    cfg.tier3_spin.setValue(10)
    assert fired


def test_run_config_card_set_busy_disables_spinboxes(app):
    from pfc_inductor.ui.workspace.cascade_page import _RunConfigCard

    cfg = _RunConfigCard()
    cfg.set_busy(True)
    assert not cfg.tier2_spin.isEnabled()
    assert not cfg.tier3_spin.isEnabled()
    assert not cfg.workers_spin.isEnabled()
    cfg.set_busy(False)
    assert cfg.tier2_spin.isEnabled()


def test_run_config_card_fea_badge_reflects_backend(app):
    """The badge text changes between `configurado` and `indisponível`
    based on what `supports_tier3()` returns."""
    from unittest.mock import patch

    from pfc_inductor.ui.workspace.cascade_page import _RunConfigCard

    cfg = _RunConfigCard()
    with patch("pfc_inductor.ui.workspace.cascade_page.supports_tier3",
               return_value=True):
        cfg.refresh_fea_status()
        assert "configurado" in cfg.fea_badge.text().lower()
    with patch("pfc_inductor.ui.workspace.cascade_page.supports_tier3",
               return_value=False):
        cfg.refresh_fea_status()
        assert "indisponível" in cfg.fea_badge.text().lower()


# ─── _TierProgressGrid ────────────────────────────────────────────


def test_tier_progress_grid_has_four_rows(app):
    from pfc_inductor.ui.workspace.cascade_page import _TierProgressGrid

    grid = _TierProgressGrid()
    assert set(grid._bars.keys()) == {0, 1, 2, 3}
    for status in grid._statuses.values():
        assert status.text() == "idle"


def test_tier_progress_grid_update_and_reset(app):
    from pfc_inductor.ui.workspace.cascade_page import _TierProgressGrid

    grid = _TierProgressGrid()
    grid.update_tier(0, 50, 100)
    assert grid._bars[0].value() == 50
    assert grid._statuses[0].text() == "running"
    grid.update_tier(0, 100, 100)
    assert grid._statuses[0].text() == "done"
    grid.reset()
    assert grid._statuses[0].text() == "idle"
    assert grid._bars[0].value() == 0


def test_tier_progress_grid_mark_skipped(app):
    from pfc_inductor.ui.workspace.cascade_page import _TierProgressGrid

    grid = _TierProgressGrid()
    grid.mark_skipped(3)
    assert grid._statuses[3].text() == "skipped"


# ─── _TopNTable column reveal ─────────────────────────────────────


def _row(
    candidate_key: str,
    *,
    loss_t1: float = 8.5,
    notes: dict | None = None,
    L_t3_uH: float | None = None,
    Bpk_t3_T: float | None = None,
    saturation_t2: bool | None = None,
) -> CandidateRow:
    return CandidateRow(
        candidate_key=candidate_key,
        core_id=candidate_key.split("|")[0] if "|" in candidate_key else candidate_key,
        material_id="mat", wire_id="wire",
        N=45, gap_mm=None,
        highest_tier=3 if L_t3_uH is not None else (2 if notes and "tier2" in notes else 1),
        feasible_t0=True,
        loss_t1_W=loss_t1, temp_t1_C=80.0, cost_t1_USD=5.0,
        loss_t2_W=loss_t1 if notes and "tier2" in notes else None,
        saturation_t2=saturation_t2,
        L_t3_uH=L_t3_uH, Bpk_t3_T=Bpk_t3_T,
        L_t4_uH=None,
        notes=notes,
    )


def test_top_n_table_base_columns_when_only_tier1(app):
    from pfc_inductor.ui.workspace.cascade_page import _TopNTable

    table = _TopNTable()
    table.populate([_row(f"core_{i}|mat|wire", loss_t1=5.0 + i) for i in range(3)])
    assert table.columnCount() == len(_TopNTable.BASE_HEADERS)
    assert table.rowCount() == 3


def test_top_n_table_widens_when_tier2_present(app):
    from pfc_inductor.ui.workspace.cascade_page import _TopNTable

    table = _TopNTable()
    rows = [
        _row(f"core_{i}|mat|wire",
             notes={"tier2": {"L_avg_uH": 380.0, "B_pk_T": 0.36}},
             saturation_t2=False)
        for i in range(2)
    ]
    table.populate(rows)
    expected = len(_TopNTable.BASE_HEADERS) + len(_TopNTable.T2_HEADERS)
    assert table.columnCount() == expected


def test_top_n_table_widens_again_when_tier3_present(app):
    from pfc_inductor.ui.workspace.cascade_page import _TopNTable

    table = _TopNTable()
    rows = [
        _row(
            f"core_{i}|mat|wire",
            notes={
                "tier2": {"L_avg_uH": 380.0, "B_pk_T": 0.36},
                "tier3": {
                    "L_relative_error_pct": 12.5,
                    "B_relative_error_pct": 3.0,
                    "confidence": "média",
                    "backend": "femmt",
                },
            },
            saturation_t2=False,
            L_t3_uH=420.0, Bpk_t3_T=0.34,
        )
        for i in range(2)
    ]
    table.populate(rows)
    expected = (
        len(_TopNTable.BASE_HEADERS)
        + len(_TopNTable.T2_HEADERS)
        + len(_TopNTable.T3_HEADERS)
    )
    assert table.columnCount() == expected


def test_top_n_table_first_cell_carries_candidate_key(app):
    from pfc_inductor.ui.workspace.cascade_page import (
        _USER_ROLE_KEY,
        _TopNTable,
    )

    table = _TopNTable()
    table.populate([_row("k1|m|w"), _row("k2|m|w")])
    cell = table.item(0, 0)
    assert cell is not None
    assert cell.data(_USER_ROLE_KEY) == "k1|m|w"


# ─── selection_applied signal end-to-end ──────────────────────────


def test_cascade_page_apply_button_emits_selection_applied(app, tmp_path: Path):
    """Selecting a row + clicking Apply must emit the same
    (material_id, core_id, wire_id) tuple the OtimizadorPage emits —
    so MainWindow's `_apply_optimizer_choice` handler picks it up
    unchanged."""
    from PySide6.QtWidgets import QTableWidgetItem

    from pfc_inductor.ui.workspace import CascadePage
    from pfc_inductor.ui.workspace.cascade_page import _USER_ROLE_KEY

    page = CascadePage(store_path=tmp_path / "cascade.db")
    # Inject a synthetic row directly into the table — avoids running
    # the orchestrator end-to-end for a UI-flow regression.
    page._table.setColumnCount(len(page._table.BASE_HEADERS))
    page._table.setRowCount(1)
    page._table.setItem(
        0, 0, QTableWidgetItem("1"),
    )
    page._table.item(0, 0).setData(_USER_ROLE_KEY, "core_x|mat_x|wire_x|_|_")
    page._table.setItem(0, 1, QTableWidgetItem("core_x"))
    page._table.setItem(0, 2, QTableWidgetItem("mat_x"))
    page._table.setItem(0, 3, QTableWidgetItem("wire_x"))
    page._table.selectRow(0)

    received: list[tuple[str, str, str]] = []
    page.selection_applied.connect(
        lambda mid, cid, wid: received.append((mid, cid, wid)),
    )
    page._on_apply_clicked()
    assert received == [("mat_x", "core_x", "wire_x")]


def test_cascade_page_apply_open_disabled_until_selection(app, tmp_path: Path):
    from pfc_inductor.ui.workspace import CascadePage

    page = CascadePage(store_path=tmp_path / "cascade.db")
    assert not page._btn_apply.isEnabled()
    assert not page._btn_open.isEnabled()
