"""BottomStatusBar pill counter regressions."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


def test_status_bar_initial_zero_counts_use_neutral_pill(app):
    from pfc_inductor.ui.shell import BottomStatusBar
    sb = BottomStatusBar()
    assert sb.warnings_text() == "0 Avisos"
    assert sb.errors_text() == "0 Erros"
    assert sb.validations_text() == "0 Validações"
    assert sb.warnings_variant() == "neutral"
    assert sb.errors_variant() == "neutral"
    assert sb.validations_variant() == "neutral"


def test_status_bar_warnings_pill_switches_to_warning_when_above_zero(app):
    from pfc_inductor.ui.shell import BottomStatusBar
    sb = BottomStatusBar()
    sb.set_warnings(2)
    assert sb.warnings_text() == "2 Avisos"
    assert sb.warnings_variant() == "warning"


def test_status_bar_errors_pill_uses_danger_when_above_zero(app):
    from pfc_inductor.ui.shell import BottomStatusBar
    sb = BottomStatusBar()
    sb.set_errors(1)
    assert sb.errors_text() == "1 Erros"
    assert sb.errors_variant() == "danger"


def test_status_bar_validations_pill_uses_success_when_above_zero(app):
    from pfc_inductor.ui.shell import BottomStatusBar
    sb = BottomStatusBar()
    sb.set_validations(12)
    assert sb.validations_text() == "12 Validações"
    assert sb.validations_variant() == "success"


def test_status_bar_save_label_relative_time(app):
    from pfc_inductor.ui.shell import BottomStatusBar
    sb = BottomStatusBar()
    five_min_ago = datetime.now() - timedelta(minutes=5)
    sb.set_save_status(unsaved=False, last_saved_at=five_min_ago)
    assert "5 min" in sb._save_label.text()


def test_status_bar_save_label_unsaved(app):
    from pfc_inductor.ui.shell import BottomStatusBar
    sb = BottomStatusBar()
    sb.set_save_status(unsaved=True)
    assert "não salvas" in sb._save_label.text().lower()
