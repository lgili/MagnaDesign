"""3-step first-run tour pinned over MainWindow.

A first-time engineer opens the app and sees:

1. an empty KPI strip with **FAILED**
2. a top menu bar with 5 cryptic sections
3. a 4-tab workspace with no design loaded

Without orientation they bail in 30 seconds. The tour walks them
through the *minimum* path to a working design:

    Step 1: "Start by filling in the spec" (highlight drawer)
    Step 2: "Pick material / core / wire" (highlight Core tab)
    Step 3: "Analyse, validate and export" (highlight tabs)

Show-once contract: a ``QSettings("ui/onboarding_seen", true)`` flag
is written when the user finishes the tour OR clicks "Skip" — the
tour never appears on subsequent launches. Reset by clearing the
key in Settings or via the dev shortcut documented below.

Visual style is intentionally lightweight — a translucent overlay +
a balloon callout, *not* a multi-modal wizard. Engineers don't want
to be lectured; they want enough to start clicking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme


@dataclass(frozen=True)
class TourStep:
    """One step of the tour.

    - ``title``: 1-line headline ("Start by filling…").
    - ``body``: 1–2 sentence explanation.
    - ``cta_label``: CTA on the right of the bubble ("Next", "OK").
    """

    title: str
    body: str
    cta_label: str = "Next"


# Three-step canonical tour. Kept short on purpose — anything more is
# noise for the engineer who already knows what they're doing.
DEFAULT_STEPS: tuple[TourStep, ...] = (
    TourStep(
        title="1.  Start by filling in the spec",
        body=(
            "Open the left column (chevron > in the corner) and enter "
            "topology, voltages, current, fsw and thermal limits. "
            "Without these the KPIs stay at '—' and the design won't run."
        ),
        cta_label="Next",
    ),
    TourStep(
        title="2.  Pick material, core and wire",
        body=(
            "The Core tab ranks candidates by score (losses + volume "
            "+ cost). Pick a row and click 'Apply selection' — or use "
            "the Optimizer to run a Pareto sweep."
        ),
        cta_label="Next",
    ),
    TourStep(
        title="3.  Analyse, validate and export",
        body=(
            "The Analysis tab shows waveforms, losses, B–H and the "
            "full Technical Details panel. Validate runs FEM "
            "(2–5 min); Export generates the HTML datasheet. Recalculate "
            "is on Ctrl+R · Cmd+K opens the command palette."
        ),
        cta_label="Get started",
    ),
)


class OnboardingTour(QWidget):
    """Translucent overlay + step balloon, anchored to the parent window.

    The widget covers the full parent rect at low opacity (so the
    underlying UI is dimmed but legible), then paints a balloon at
    the bottom-centre with the active step's text and Skip / Next
    buttons. ``finished`` fires when the tour completes or is skipped.
    """

    finished = Signal()

    BALLOON_WIDTH = 520
    OVERLAY_OPACITY = 0.55

    def __init__(
        self,
        parent: QWidget,
        steps: tuple[TourStep, ...] = DEFAULT_STEPS,
    ) -> None:
        super().__init__(parent)
        self._steps = steps
        self._idx = 0
        # Cover the entire parent. ``WA_TranslucentBackground`` lets us
        # paint the dim overlay ourselves while keeping the balloon's
        # children fully opaque.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._balloon = self._build_balloon()
        self._balloon.setParent(self)

        self._render_step()
        self._reposition()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @classmethod
    def maybe_show(
        cls, parent: QWidget, settings_key: str = "ui/onboarding_seen"
    ) -> Optional[OnboardingTour]:
        """Show only if the persistent flag isn't set yet.

        Use from the host's first-show event handler. Returns the
        ``OnboardingTour`` instance when shown, else ``None``.
        """
        from PySide6.QtCore import QSettings

        from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG

        qs = QSettings(SETTINGS_ORG, SETTINGS_APP)
        if bool(qs.value(settings_key, False, type=bool)):
            return None
        tour = cls(parent)
        tour._settings_key = settings_key
        tour.show()
        tour.raise_()
        return tour

    # ------------------------------------------------------------------
    # Lifecycle / rendering
    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        # Hand-painted dim overlay — single ``fillRect`` is the cheapest
        # way to render a uniform translucent layer. ``QGraphicsOpacity``
        # would also work but introduces an effect node we don't need.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(0, 0, 0)
        c.setAlphaF(self.OVERLAY_OPACITY)
        painter.fillRect(self.rect(), c)

    def resizeEvent(self, _event):
        self._reposition()

    # ------------------------------------------------------------------
    def _build_balloon(self) -> QFrame:
        balloon = QFrame()
        balloon.setObjectName("OnboardingBalloon")
        balloon.setFixedWidth(self.BALLOON_WIDTH)
        balloon.setStyleSheet(self._balloon_qss())

        v = QVBoxLayout(balloon)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        self._title = QLabel()
        self._title.setStyleSheet(self._title_qss())
        self._title.setWordWrap(True)
        v.addWidget(self._title)

        self._body = QLabel()
        self._body.setStyleSheet(self._body_qss())
        self._body.setWordWrap(True)
        v.addWidget(self._body)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 4, 0, 0)
        button_row.setSpacing(8)

        # Step indicator (left) — "Step 1 of 3".
        self._counter = QLabel()
        self._counter.setStyleSheet(self._counter_qss())
        button_row.addWidget(self._counter, 1, Qt.AlignmentFlag.AlignVCenter)

        self._btn_skip = QPushButton("Skip")
        self._btn_skip.setProperty("class", "Tertiary")
        self._btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_skip.setStyleSheet(self._skip_qss())
        self._btn_skip.clicked.connect(self._on_skip)
        button_row.addWidget(self._btn_skip)

        self._btn_next = QPushButton("Next")
        self._btn_next.setProperty("class", "Primary")
        self._btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_next.setStyleSheet(self._next_qss())
        self._btn_next.clicked.connect(self._on_next)
        button_row.addWidget(self._btn_next)

        v.addLayout(button_row)
        return balloon

    def _render_step(self) -> None:
        step = self._steps[self._idx]
        self._title.setText(step.title)
        self._body.setText(step.body)
        self._btn_next.setText(step.cta_label)
        self._counter.setText(f"Step {self._idx + 1} of {len(self._steps)}")

    def _reposition(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        # Anchor balloon at bottom-centre — consistent landing spot
        # regardless of which step is active.
        bw = self._balloon.sizeHint().width() or self.BALLOON_WIDTH
        bh = self._balloon.sizeHint().height() or 200
        cx = self.width() // 2
        x = max(16, cx - bw // 2)
        y = self.height() - bh - 64  # 64 px above bottom edge
        self._balloon.setGeometry(x, y, bw, bh)

    # ------------------------------------------------------------------
    def _on_next(self) -> None:
        if self._idx >= len(self._steps) - 1:
            self._dismiss(persist=True)
            return
        self._idx += 1
        self._render_step()
        QTimer.singleShot(0, self._reposition)

    def _on_skip(self) -> None:
        self._dismiss(persist=True)

    def _dismiss(self, persist: bool) -> None:
        if persist and getattr(self, "_settings_key", None):
            from PySide6.QtCore import QSettings

            from pfc_inductor.settings import SETTINGS_APP, SETTINGS_ORG

            QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(
                self._settings_key,
                True,
            )
        self.finished.emit()
        self.deleteLater()

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------
    @staticmethod
    def _balloon_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#OnboardingBalloon {{"
            f"  background: {p.surface_elevated};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 12px;"
            f"}}"
        )

    @staticmethod
    def _title_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return f"color: {p.text};font-size: {t.title_md}px;font-weight: {t.semibold};"

    @staticmethod
    def _body_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return f"color: {p.text_secondary};font-size: {t.body_md}px;line-height: 1.4;"

    @staticmethod
    def _counter_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return f"color: {p.text_muted};font-size: {t.caption}px;"

    @staticmethod
    def _skip_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: 1px solid {p.border};"
            f"  color: {p.text_secondary};"
            f"  border-radius: 8px;"
            f"  padding: 6px 14px;"
            f"  font-size: {t.body_md}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {p.bg};"
            f"  color: {p.text};"
            f"}}"
        )

    @staticmethod
    def _next_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QPushButton {{"
            f"  background: {p.accent};"
            f"  border: 0;"
            f"  color: white;"
            f"  border-radius: 8px;"
            f"  padding: 6px 18px;"
            f"  font-size: {t.body_md}px;"
            f"  font-weight: {t.semibold};"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {p.accent_hover};"
            f"}}"
        )
