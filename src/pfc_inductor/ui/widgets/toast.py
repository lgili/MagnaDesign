"""Lightweight transient toast — for "saved", "exported", "applied".

Why a custom widget instead of ``QStatusBar`` or ``QMessageBox``:

- ``QMessageBox.information`` is modal and demands an OK click for
  every confirmation. Engineers regenerating a datasheet 10 times
  per session would mutiny.
- ``QStatusBar`` is too quiet: a permanent footer line is easy to
  miss when the user is staring at the centre of the screen.
- A floating, auto-dismissing toast at bottom-right of the window
  matches the pattern Linear / Notion / VS Code use — same place,
  same behaviour, low cognitive load.

API: ``Toast.show(parent, message, action_label=None, action=None)``.
The optional action button renders inline ("Abrir"); clicking it
fires the callback and dismisses the toast immediately.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from pfc_inductor.ui.theme import ANIMATION, get_theme


class Toast(QFrame):
    """Floating bottom-right confirmation pill with optional action.

    Self-positioning via ``parent.geometry()`` — the toast walks 16 px
    in from the parent's bottom-right corner. Auto-dismisses after
    ``ANIMATION.toast_ms`` (default 3 s) with a fade-out.
    """

    MARGIN = 16
    HEIGHT = 44

    def __init__(
        self,
        parent: QWidget,
        message: str,
        *,
        action_label: Optional[str] = None,
        action: Optional[Callable[[], None]] = None,
        duration_ms: int = ANIMATION.toast_ms,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(self._self_qss())
        self.setFixedHeight(self.HEIGHT)

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 8, 12, 8)
        h.setSpacing(12)

        # ✓ glyph for "success" toasts. Kept as a label so themes
        # don't paint a tinted icon over it.
        check = QLabel("✓")
        check.setStyleSheet(self._check_qss())
        h.addWidget(check, 0, Qt.AlignmentFlag.AlignVCenter)

        msg = QLabel(message)
        msg.setStyleSheet(self._msg_qss())
        h.addWidget(msg, 1, Qt.AlignmentFlag.AlignVCenter)

        if action_label and action is not None:
            btn = QPushButton(action_label)
            btn.setProperty("class", "Tertiary")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._btn_qss())
            btn.setFixedHeight(24)
            btn.clicked.connect(action)
            btn.clicked.connect(self.dismiss)
            h.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Fade-in/out via QGraphicsOpacityEffect — smoother than
        # toggling visibility, doesn't interrupt user focus.
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_out.setDuration(180)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.deleteLater)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)
        self._dismiss_timer.setInterval(duration_ms)

    # ------------------------------------------------------------------
    @classmethod
    def show_message(
        cls,
        parent: QWidget,
        message: str,
        *,
        action_label: Optional[str] = None,
        action: Optional[Callable[[], None]] = None,
        duration_ms: int = ANIMATION.toast_ms,
    ) -> Toast:
        """Convenience constructor + reveal in one call."""
        t = cls(
            parent,
            message,
            action_label=action_label,
            action=action,
            duration_ms=duration_ms,
        )
        t._reveal()
        return t

    # ------------------------------------------------------------------
    def dismiss(self) -> None:
        if self._dismiss_timer.isActive():
            self._dismiss_timer.stop()
        if self._fade_out.state() == QPropertyAnimation.State.Running:
            return
        self._fade_out.start()

    def _reveal(self) -> None:
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._fade_in.start()
        self._dismiss_timer.start()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        pg: QRect = parent.rect()
        self.move(
            pg.right() - self.width() - self.MARGIN,
            pg.bottom() - self.height() - self.MARGIN,
        )

    # Re-anchor on parent resize.
    def parentResized(self) -> None:
        self._reposition()

    # ------------------------------------------------------------------
    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#Toast {{"
            f"  background: {p.surface_elevated};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 10px;"
            f"}}"
        )

    @staticmethod
    def _check_qss() -> str:
        p = get_theme().palette
        return f"color: {p.success};font-size: 16px;font-weight: 700;"

    @staticmethod
    def _msg_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return f"color: {p.text};font-size: {t.body_md}px;"

    @staticmethod
    def _btn_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 0;"
            f"  color: {p.accent};"
            f"  font-size: {t.body_md}px;"
            f"  font-weight: {t.semibold};"
            f"  padding: 0 6px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  text-decoration: underline;"
            f"}}"
        )
