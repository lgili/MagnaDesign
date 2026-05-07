"""Generic header for non-workspace pages.

Three of the four sidebar destinations — Otimizador, Catálogo,
Configurações — are read/edit pages, not the rich workspace that
Projeto is. They each rolled their own ``QLabel(title) + QLabel(intro)``
pair, with subtly different paddings and weights, and that
inconsistency was visible when navigating between them.

``WorkspacePageHeader`` standardises the chrome so all three look
like siblings:

- Fixed 56 px height (matches ``WorkspaceHeader.HEIGHT`` on Projeto
  so the top edge lines up across areas).
- Title (``title_md`` semibold) + subtitle (``caption`` muted)
  stacked at the left.
- Right-side stretch hosts an optional CTA list.
- Border-bottom separator from the body, same as Projeto's header.

The original ``WorkspaceHeader`` (with editable project name + 3 CTAs
+ save pill) stays distinct on Projeto — Projeto **is** a workspace,
not a page, and earns the richer chrome.
"""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed


class WorkspacePageHeader(QFrame):
    """Title + subtitle (+ optional CTAs) header for a sidebar page."""

    HEIGHT = 56

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        ctas: Optional[Sequence[QPushButton]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("WorkspacePageHeader")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        h = QHBoxLayout(self)
        h.setContentsMargins(24, 8, 24, 8)
        h.setSpacing(12)

        # Title + subtitle stack on the left.
        col = QVBoxLayout()
        col.setSpacing(0)
        col.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(title)
        self._title.setObjectName("PageTitle")
        col.addWidget(self._title)
        self._subtitle: Optional[QLabel] = None
        if subtitle:
            self._subtitle = QLabel(subtitle)
            self._subtitle.setObjectName("PageSubtitle")
            self._subtitle.setProperty("role", "muted")
            col.addWidget(self._subtitle)
        h.addLayout(col, 0)
        h.addStretch(1)

        # Optional CTAs on the right (kept lean — Projeto's full header
        # is the place for richer toolbars; this is a page header).
        for btn in ctas or ():
            h.addWidget(btn, 0)

        self.setStyleSheet(self._self_qss())
        on_theme_changed(self._refresh_qss)

    # ------------------------------------------------------------------
    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_subtitle(self, text: str) -> None:
        if self._subtitle is None:
            return
        self._subtitle.setText(text)

    # ------------------------------------------------------------------
    def _refresh_qss(self) -> None:
        self.setStyleSheet(self._self_qss())

    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QFrame#WorkspacePageHeader {{"
            f"  background: {p.surface};"
            f"  border: 0;"
            f"  border-bottom: 1px solid {p.border};"
            f"}}"
            f"QLabel#PageTitle {{"
            f"  color: {p.text};"
            f"  font-size: {t.title_md}px;"
            f"  font-weight: {t.semibold};"
            f"}}"
            f"QLabel#PageSubtitle {{"
            f"  color: {p.text_secondary};"
            f"  font-size: {t.caption}px;"
            f"}}"
        )
