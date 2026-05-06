"""Reusable ``Card`` container.

Visual contract (enforced by QSS in :mod:`pfc_inductor.ui.style`):
- 16 px outer corner radius
- 1 px ``palette.border`` stroke
- ``palette.surface`` background
- Header with 14 px semibold title + optional badge + optional "..." overflow
- ``QGraphicsDropShadowEffect`` attached at construction (elevation 1) and
  smoothly raised to elevation 2 on hover.

Public API
----------

::

    card = Card("Resumo do Projeto", body_widget,
                badge="Aprovado", elevation=1)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QEnterEvent
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QWidget, QMenu,
    QGraphicsDropShadowEffect, QSizePolicy,
)

from pfc_inductor.ui.theme import get_theme, ShadowSpec
from pfc_inductor.ui.icons import icon as ui_icon


def _make_drop_shadow(parent: QWidget, spec: ShadowSpec) -> QGraphicsDropShadowEffect:
    eff = QGraphicsDropShadowEffect(parent)
    eff.setBlurRadius(float(spec.blur))
    eff.setOffset(float(spec.dx), float(spec.dy))
    # ShadowSpec.color uses #AARRGGBB which Qt's QColor accepts directly.
    eff.setColor(QColor(spec.color))
    return eff


class Card(QFrame):
    """Card container with header, body, and animated shadow elevation."""

    def __init__(
        self,
        title: str,
        body: QWidget,
        *,
        badge: Optional[str] = None,
        badge_variant: str = "neutral",
        actions: Optional[list[tuple[str, object]]] = None,
        elevation: int = 1,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setProperty("elevation", elevation)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- header ---------------------------------------------------
        self._header = QFrame()
        self._header.setObjectName("CardHeader")
        h = QHBoxLayout(self._header)
        h.setContentsMargins(20, 14, 14, 14)
        h.setSpacing(10)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("CardTitle")
        h.addWidget(self._title_label)
        h.addStretch(1)

        if badge is not None:
            self._badge = QLabel(badge)
            self._badge.setProperty("class", "Pill")
            self._badge.setProperty("pill", badge_variant)
            h.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            self._badge = None

        if actions:
            self._overflow = QToolButton()
            self._overflow.setIcon(
                ui_icon("more-horizontal",
                        color=get_theme().palette.text_muted, size=16)
            )
            self._overflow.setCursor(Qt.CursorShape.PointingHandCursor)
            self._overflow.setStyleSheet(
                "QToolButton { background: transparent; border: 0; padding: 4px; }"
                "QToolButton:hover { background: "
                f"{get_theme().palette.bg}; border-radius: 6px; }}"
                "QToolButton::menu-indicator { image: none; width: 0; }"
            )
            menu = QMenu(self._overflow)
            for label, slot in actions:
                act = menu.addAction(label)
                if callable(slot):
                    act.triggered.connect(slot)
            self._overflow.setMenu(menu)
            self._overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            h.addWidget(self._overflow, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            self._overflow = None

        # ---- body -----------------------------------------------------
        self._body_frame = QFrame()
        self._body_frame.setObjectName("CardBody")
        body_lay = QVBoxLayout(self._body_frame)
        body_lay.setContentsMargins(20, 16, 20, 20)
        body_lay.setSpacing(12)
        body_lay.addWidget(body)
        self._body_widget = body

        outer.addWidget(self._header)
        outer.addWidget(self._body_frame, 1)

        # ---- elevation shadow -----------------------------------------
        self._spec_idle = get_theme().palette.card_shadow_sm
        self._spec_hover = get_theme().palette.card_shadow_md
        self._effect = _make_drop_shadow(self, self._spec_idle)
        self.setGraphicsEffect(self._effect)

        # Animations on blur radius give a sense of elevation lift.
        self._anim = QPropertyAnimation(self._effect, b"blurRadius", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_badge(self, text: Optional[str], variant: str = "neutral") -> None:
        """Update the header badge (right side). Pass ``None`` to hide."""
        if self._badge is None:
            return
        if text is None:
            self._badge.hide()
            return
        self._badge.setText(text)
        self._badge.setProperty("pill", variant)
        st = self._badge.style()
        st.unpolish(self._badge)
        st.polish(self._badge)
        self._badge.show()

    def body(self) -> QWidget:
        """Access the original body widget."""
        return self._body_widget

    def title(self) -> str:
        return self._title_label.text()

    # ------------------------------------------------------------------
    # Hover elevation
    # ------------------------------------------------------------------
    def enterEvent(self, event: QEnterEvent) -> None:  # type: ignore[override]
        self._anim.stop()
        self._anim.setStartValue(self._effect.blurRadius())
        self._anim.setEndValue(float(self._spec_hover.blur))
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._anim.stop()
        self._anim.setStartValue(self._effect.blurRadius())
        self._anim.setEndValue(float(self._spec_idle.blur))
        self._anim.start()
        super().leaveEvent(event)
