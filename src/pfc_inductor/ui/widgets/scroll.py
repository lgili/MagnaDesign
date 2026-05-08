"""``wrap_scrollable`` — shared vertical-scroll wrapper for workspace pages.

Several sidebar pages stack tall content (Cascade alone is ~920 px
before its Top-N table can shrink) inside ``QStackedWidget``. On a
1366 × 768 laptop the page exceeds the viewport, Qt grows the window
past the screen edge, and the bottom Scoreboard / OS taskbar gets
hidden — the user sees no scrollbar because the page itself never
asked to scroll.

This helper is the single source of truth for "wrap a body widget in
a vertical-only QScrollArea". It mirrors the static
``ProjetoPage._wrap_scrollable`` previously used for the 4 Projeto
tabs; promoting it to a module-level function lets every workspace
page reuse the exact same configuration:

- ``setWidgetResizable(True)`` — child grows horizontally with the
  scroll area, scrolls vertically only when needed.
- ``Qt.ScrollBarAlwaysOff`` on the horizontal axis — bento and form
  layouts inside the pages are designed to flex horizontally.
- ``QFrame.Shape.NoFrame`` — no double border between the page and
  the wrapped card body.
- Expanding × Expanding size policy — the scroll area absorbs all
  remaining vertical space the parent gives it.

Use it like this::

    body = QFrame()
    layout = QVBoxLayout(body)
    layout.addWidget(card_a)
    layout.addWidget(card_b)
    ...

    outer = QVBoxLayout(self)
    outer.addWidget(WorkspacePageHeader(...))      # sticky header
    outer.addWidget(wrap_scrollable(body), 1)       # scrolling body
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget


def wrap_scrollable(widget: QWidget) -> QScrollArea:
    """Wrap ``widget`` in a vertical-only ``QScrollArea``.

    The returned ``QScrollArea`` takes ownership of ``widget``. The
    caller should add the scroll area to its layout in place of where
    ``widget`` would otherwise have gone.
    """
    scroll = QScrollArea()
    scroll.setWidget(widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Expanding,
    )
    return scroll
