"""AboutDialog renders the positioning matrix."""

from __future__ import annotations

import os

# Ensure offscreen mode for headless test runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


def test_about_dialog_mounts_and_lists_all_differentials(app):
    from pfc_inductor.positioning import COMPETITORS, DIFFERENTIALS
    from pfc_inductor.ui.about_dialog import AboutDialog

    dlg = AboutDialog()
    # Find the table widget (only one).
    from PySide6.QtWidgets import QTableWidget

    tables = dlg.findChildren(QTableWidget)
    assert len(tables) == 1
    tbl = tables[0]

    # rows == differentials, cols == 1 (title) + 1 (us) + competitors
    assert tbl.rowCount() == len(DIFFERENTIALS)
    assert tbl.columnCount() == 2 + len(COMPETITORS)

    # First column shows differential titles.
    titles_in_table = {tbl.item(i, 0).text() for i in range(tbl.rowCount())}
    expected_titles = {d.title for d in DIFFERENTIALS}
    assert titles_in_table == expected_titles


def test_about_dialog_us_column_all_yes(app):
    """Column 1 ("Nós") must show ✓ for every differential — by definition."""
    from pfc_inductor.ui.about_dialog import AboutDialog

    dlg = AboutDialog()
    from PySide6.QtWidgets import QTableWidget

    tbl = dlg.findChildren(QTableWidget)[0]
    for i in range(tbl.rowCount()):
        assert tbl.item(i, 1).text() == "✓"
