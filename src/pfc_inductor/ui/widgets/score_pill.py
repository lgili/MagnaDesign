"""``ScorePill`` — colour-graded score badge.

Maps a score in [0, 100] to one of five semantic colour bands:

- ``[85, 100]`` → success (green)
- ``[70, 85)``  → info (cyan)
- ``[55, 70)``  → warning (amber)
- ``[40, 55)``  → amber-2 (orange-leaning)
- ``[0, 40)``   → danger (red)
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from pfc_inductor.ui.theme import get_theme


def _variant_for(score: float) -> str:
    if score >= 85:
        return "success"
    if score >= 70:
        return "info"
    if score >= 55:
        return "warning"
    if score >= 40:
        return "amber"
    return "danger"


class ScorePill(QLabel):
    """Score pill that auto-picks its colour from the score value.

    The pill is a ``QLabel`` so it reuses the global ``QLabel.Pill``
    QSS — but the `amber` variant (used for the 40–55 % band) is not in
    the standard pill set, so we attach an inline stylesheet for that
    band only.
    """

    def __init__(
        self,
        score: float,
        suffix: str = "%",
        *,
        formatter: Optional[Callable[[float], str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "Pill")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._formatter = formatter or (lambda v: f"{v:.0f}{suffix}")
        self.set_score(score)

    def set_score(self, score: float) -> None:
        self._score = float(score)
        self.setText(self._formatter(self._score))
        variant = _variant_for(self._score)
        # The 5 standard pill variants come from QSS; for the
        # non-standard "amber" variant we set an inline style.
        if variant == "amber":
            p = get_theme().palette
            self.setProperty("pill", "warning")  # closest standard
            self.setStyleSheet(
                f"background: {p.warning_bg}; color: {p.warning};"
                f"border-radius: 9999px; padding: 2px 10px;"
                f"font-weight: 600; text-transform: uppercase;"
                f"letter-spacing: 0.04em; font-size: 10px;"
            )
        else:
            self.setProperty("pill", variant)
            # Clear any previous inline style so the QSS variant wins.
            self.setStyleSheet("")
        # Force re-evaluation of dynamic-property selectors.
        st = self.style()
        st.unpolish(self)
        st.polish(self)
        self.update()

    @property
    def score(self) -> float:
        return self._score

    def variant(self) -> str:
        """Return the colour band picked. Useful for tests."""
        return _variant_for(self._score)
