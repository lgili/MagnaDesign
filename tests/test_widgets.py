"""Reusable dashboard widgets — Card / MetricCard / DataTable / ScorePill /
DonutChart / NextStepsCard."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    inst = QApplication.instance() or QApplication([])
    yield inst


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------


def test_card_constructs_with_title_and_body(app):
    from PySide6.QtWidgets import QLabel

    from pfc_inductor.ui.widgets import Card

    body = QLabel("body")
    c = Card("Resumo do Projeto", body, badge="Aprovado", badge_variant="success")
    assert c.title() == "Resumo do Projeto"
    assert c.body() is body
    # Card has a drop-shadow effect attached.
    assert c.graphicsEffect() is not None


def test_card_set_badge_updates_text(app):
    from PySide6.QtWidgets import QLabel

    from pfc_inductor.ui.widgets import Card

    c = Card("X", QLabel(), badge="Aprovado", badge_variant="success")
    c.set_badge("Verificar", "warning")
    assert c._badge.text() == "Verificar"
    assert c._badge.property("pill") == "warning"


def test_card_with_overflow_actions(app):
    from PySide6.QtWidgets import QLabel

    from pfc_inductor.ui.widgets import Card

    fired = []
    c = Card(
        "X",
        QLabel(),
        actions=[("Refresh", lambda: fired.append("refresh"))],
    )
    assert c._overflow is not None
    # Invoke the menu action programmatically.
    actions = c._overflow.menu().actions()
    assert any(a.text() == "Refresh" for a in actions)
    next(a for a in actions if a.text() == "Refresh").trigger()
    assert fired == ["refresh"]


# ---------------------------------------------------------------------------
# MetricCard
# ---------------------------------------------------------------------------


def test_metric_card_renders_value_and_unit(app):
    from pfc_inductor.ui.widgets import MetricCard

    m = MetricCard("Perdas", "23.4", "W")
    assert m._val.text() == "23.4"
    assert m._unit.text() == "W"


def test_metric_card_set_value(app):
    from pfc_inductor.ui.widgets import MetricCard

    m = MetricCard("Perdas", "23.4", "W")
    m.set_value("19.7", "W")
    assert m._val.text() == "19.7"


def test_metric_card_trend_lower_better_neg_pct_is_success(app):
    from pfc_inductor.ui.theme import get_theme
    from pfc_inductor.ui.widgets import MetricCard

    m = MetricCard("T_rise", "58", "°C", trend_pct=-10.8, trend_better="lower", status="ok")
    assert "▼" in m._trend_lbl.text()
    # Success colour appears in the inline stylesheet.
    assert get_theme().palette.success.lower() in m._trend_lbl.styleSheet().lower()


def test_metric_card_trend_higher_better_pos_pct_is_success(app):
    from pfc_inductor.ui.theme import get_theme
    from pfc_inductor.ui.widgets import MetricCard

    m = MetricCard("Eficiência", "97.2", "%", trend_pct=+1.5, trend_better="higher")
    assert "▲" in m._trend_lbl.text()
    assert get_theme().palette.success.lower() in m._trend_lbl.styleSheet().lower()


def test_metric_card_status_changes_left_bar(app):
    from pfc_inductor.ui.theme import get_theme
    from pfc_inductor.ui.widgets import MetricCard

    m = MetricCard("X", "1", "")
    p = get_theme().palette
    m.set_status("err")
    assert p.danger.lower() in m.styleSheet().lower()
    m.set_status("ok")
    assert p.success.lower() in m.styleSheet().lower()


# ---------------------------------------------------------------------------
# DataTable
# ---------------------------------------------------------------------------


def test_data_table_renders_rows(app):
    from pfc_inductor.ui.widgets import DataTable

    rows = [
        ("Turns", "78", None),
        ("Layers", "3", None),
        ("Length", "12.4", "m"),
    ]
    d = DataTable(rows)
    assert d.row_count() == 3
    assert d.value_text(0) == "78"
    assert d.value_text(2) == "12.4"


def test_data_table_set_rows_replaces(app):
    from pfc_inductor.ui.widgets import DataTable

    d = DataTable([("A", "1", None)])
    assert d.row_count() == 1
    d.set_rows([("B", "2", None), ("C", "3", "mm")])
    assert d.row_count() == 2
    assert d.value_text(0) == "2"


# ---------------------------------------------------------------------------
# ScorePill
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_variant",
    [
        (95, "success"),
        (85, "success"),  # lower edge of success
        (78, "info"),
        (62, "warning"),
        (50, "amber"),
        (32, "danger"),
        (0, "danger"),
    ],
)
def test_score_pill_variant_bands(app, score, expected_variant):
    from pfc_inductor.ui.widgets import ScorePill

    p = ScorePill(score)
    assert p.variant() == expected_variant


def test_score_pill_default_format(app):
    from pfc_inductor.ui.widgets import ScorePill

    p = ScorePill(91.7)
    assert p.text() == "92%"


def test_score_pill_custom_formatter(app):
    from pfc_inductor.ui.widgets import ScorePill

    p = ScorePill(91.7, formatter=lambda v: f"{v:.1f} pts")
    assert p.text() == "91.7 pts"


# ---------------------------------------------------------------------------
# DonutChart
# ---------------------------------------------------------------------------


def test_donut_chart_total(app):
    from pfc_inductor.ui.widgets import DonutChart

    d = DonutChart([("a", 5.0, "#3B82F6"), ("b", 2.5, "#F59E0B")])
    assert abs(d.total() - 7.5) < 1e-9


def test_donut_chart_set_segments(app):
    from pfc_inductor.ui.widgets import DonutChart

    d = DonutChart()
    assert d.total() == 0
    d.set_segments([("x", 1.0, None), ("y", 2.0, None)])
    assert d.total() == 3.0


# ---------------------------------------------------------------------------
# NextStepsCard
# ---------------------------------------------------------------------------


def test_next_steps_card_count_and_set(app):
    from pfc_inductor.ui.widgets import ActionItem, NextStepsCard

    n = NextStepsCard(
        [
            ActionItem("Validar FEM", "todo"),
            ActionItem("Otimizar Litz", "pending"),
            ActionItem("Comparar", "done"),
        ]
    )
    assert n.count() == 3
    n.set_items([ActionItem("Single", "todo")])
    assert n.count() == 1


def test_next_steps_card_todo_callback_fires(app):
    from pfc_inductor.ui.widgets import ActionItem, NextStepsCard

    fired = []
    n = NextStepsCard(
        [
            ActionItem("Validar FEM", "todo", lambda: fired.append("fem")),
        ]
    )
    # The CTA is the QPushButton in the only _ActionRow.
    from PySide6.QtWidgets import QPushButton

    buttons = n.findChildren(QPushButton)
    assert len(buttons) == 1
    buttons[0].click()
    assert fired == ["fem"]
