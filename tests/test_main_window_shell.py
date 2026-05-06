"""Integration: MainWindow boots with the v3 MagnaDesign shell.

v3 contract:
- 4 sidebar areas (dashboard / otimizador / catalogo / configuracoes)
- ProjetoPage owns SpecDrawer + WorkspaceHeader + ProgressIndicator +
  3 workspace tabs + Scoreboard.
- No QToolBar, no 8-step stepper, no Modo Clássico, no QSplitter
  mounting SpecPanel|PlotPanel|ResultPanel.
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
def win(app):
    from pfc_inductor.ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_main_window_has_v3_shell_widgets(win):
    from pfc_inductor.ui.shell import Sidebar
    from pfc_inductor.ui.shell.header import WorkspaceHeader
    from pfc_inductor.ui.shell.progress_indicator import ProgressIndicator
    from pfc_inductor.ui.shell.scoreboard import Scoreboard
    from pfc_inductor.ui.shell.spec_drawer import SpecDrawer
    assert isinstance(win.sidebar, Sidebar)
    assert isinstance(win.projeto_page.drawer, SpecDrawer)
    assert isinstance(win.projeto_page.progress, ProgressIndicator)
    assert isinstance(win.projeto_page.scoreboard, Scoreboard)
    assert isinstance(win.projeto_page.header, WorkspaceHeader)


def test_main_window_no_legacy_qtoolbar(win):
    from PySide6.QtWidgets import QToolBar
    bars = win.findChildren(QToolBar)
    assert bars == []


def test_main_window_no_legacy_splitter(win):
    """v3 removed the *legacy* 3-column SpecPanel | PlotPanel |
    ResultPanel splitter. Other splitters (e.g. inside OptimizerEmbed
    where the ranked table sits next to the Pareto plot) are fine
    — they are owned by individual pages, not by the shell."""
    from PySide6.QtWidgets import QSplitter

    from pfc_inductor.ui.plot_panel import PlotPanel
    from pfc_inductor.ui.result_panel import ResultPanel
    from pfc_inductor.ui.spec_panel import SpecPanel
    legacy_panels = (SpecPanel, PlotPanel, ResultPanel)

    for sp in win.findChildren(QSplitter):
        # Walk the splitter's immediate children; flag any that hosts
        # one of the legacy panels.
        for i in range(sp.count()):
            w = sp.widget(i)
            assert not isinstance(w, legacy_panels), (
                f"Found a legacy splitter mounting {type(w).__name__} "
                "in the shell — v3 should have removed this."
            )


def test_sidebar_navigation_routes_to_stack(win):
    from pfc_inductor.ui.main_window import AREA_PAGES
    assert AREA_PAGES == (
        "dashboard", "otimizador", "catalogo", "configuracoes",
    )
    for area in AREA_PAGES:
        win.sidebar._on_nav_clicked(area)
        idx = AREA_PAGES.index(area)
        assert win.stack.currentIndex() == idx


def test_calc_populates_scoreboard(win):
    """After the construction-time _on_calculate, the Scoreboard's KPI
    strip should show L=… text. Replaces the old "validations pill"."""
    text = win.projeto_page.scoreboard.kpi_text()
    assert text and text != "—"
    # Smoke: the L= prefix is the first token.
    assert "L=" in text


def test_progress_indicator_marks_design_done_after_calc(win):
    """After a successful calc, the Design state moves from current
    to done (Spec stayed done from construction)."""
    pi = win.projeto_page.progress
    assert pi.state("design") == "done"
    # Spec is also done by default since the drawer is filled.
    assert pi.state("spec") == "done"


def test_theme_toggle_does_not_change_sidebar_palette(win, app):
    from pfc_inductor.ui.theme import SIDEBAR
    win._toggle_theme()
    assert SIDEBAR.bg == "#0F1729"
    win._toggle_theme()  # restore
