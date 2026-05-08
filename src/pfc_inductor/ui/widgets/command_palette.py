"""Command palette — fuzzy-search overlay for every action in the app.

Power users hit ``Cmd+K`` (``Ctrl+K`` on Linux/Windows) and type the
first letters of what they want: "rec" → Recalcular, "abr proj" →
Abrir projeto, "exp data" → Exportar datasheet. The palette dismisses
on Esc, on click outside, or after firing the chosen command.

Why a separate widget instead of a QMenu shortcut tree:
    - QMenu has no fuzzy match — users have to remember the menu path.
    - Discovery: every command lives in the palette regardless of
      where its UI button hides (sidebar, toolbar, modal, etc.).
    - Engineers iterating on a design hit Recalcular dozens of times
      per session; ``Cmd+K  r  ↵`` is faster than chasing the header
      button on a 27" display.

Usage from the host (``MainWindow``)::

    self._cmd_palette = CommandPalette(self)
    self._cmd_palette.register_many([
        Command("recalc",  "Recalcular",      "Ctrl+R",
                self._on_calculate),
        Command("project_save", "Salvar projeto", "Ctrl+S",
                self._on_project_save),
        ...
    ])
    QShortcut(QKeySequence("Ctrl+K"), self,
              activated=self._cmd_palette.show)

The palette mirrors actions registered elsewhere — register them once
where they live and pass the bound method into the palette. There's no
duplication of behaviour, only of *discovery*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme


@dataclass(frozen=True)
class Command:
    """A registerable command.

    - ``key``: stable identifier, used for dedup. Lowercase / snake_case.
    - ``label``: what the user sees in the palette list.
    - ``shortcut``: keyboard chord shown right-aligned (cosmetic — the
      actual binding lives on the host's QShortcut/QAction).
    - ``handler``: zero-arg callable fired when the user picks the row.
    - ``hint``: optional 1-line description shown muted below the label.
    """

    key: str
    label: str
    shortcut: str = ""
    handler: Callable[[], None] = lambda: None
    hint: str = ""


class CommandPalette(QDialog):
    """Modal-feeling overlay; dismisses on Esc / click-outside.

    The palette is a top-level frameless ``QDialog`` so it floats above
    every other widget without disturbing the parent layout. Position
    is anchored to the parent's top-centre — same pattern as VS Code,
    Linear, and Notion.
    """

    DEFAULT_WIDTH = 540
    LIST_MAX_ROWS_VISIBLE = 8

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        # Frameless so the OS chrome doesn't compete with the palette's
        # own border + shadow. Modal so Esc and Enter are unambiguous.
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(self.DEFAULT_WIDTH)

        # The visible body — wrapped in a separate QFrame so the
        # WA_TranslucentBackground above only erases the dialog's outer
        # 1 px border (lets us draw a custom shadow / radius via QSS).
        body = QFrame(self)
        body.setObjectName("CommandPaletteBody")
        body.setStyleSheet(self._self_qss())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(body)

        v = QVBoxLayout(body)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        # ---- search input -------------------------------------------------
        self._search = QLineEdit(body)
        self._search.setPlaceholderText("Buscar comando…")
        self._search.setStyleSheet(self._search_qss())
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_query_changed)
        # Forward arrow keys / Enter from the search field to the list
        # so the user never has to leave the input.
        self._search.installEventFilter(self)
        v.addWidget(self._search)

        # ---- result list --------------------------------------------------
        self._list = QListWidget(body)
        self._list.setStyleSheet(self._list_qss())
        self._list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._list.itemActivated.connect(self._fire_current)
        v.addWidget(self._list, 1)

        # ---- footer hint --------------------------------------------------
        hint = QLabel("↑↓ navegar · ↵ executar · Esc fechar", body)
        hint.setStyleSheet(self._hint_qss())
        v.addWidget(hint, 0, Qt.AlignmentFlag.AlignRight)

        self._commands: list[Command] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def register(self, command: Command) -> None:
        """Add a single command. Replaces by ``key`` if already present."""
        self._commands = [c for c in self._commands if c.key != command.key]
        self._commands.append(command)

    def register_many(self, commands: list[Command]) -> None:
        for c in commands:
            self.register(c)

    def show(self) -> None:  # type: ignore[override]
        """Reveal centred above the parent + clear the search field."""
        self._search.clear()
        self._render(self._commands)
        self._reposition()
        super().show()
        self._search.setFocus(Qt.FocusReason.PopupFocusReason)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            k = event.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move_selection(+1 if k == Qt.Key.Key_Down else -1)
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._fire_current()
                return True
            if k == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _move_selection(self, delta: int) -> None:
        n = self._list.count()
        if n == 0:
            return
        current = self._list.currentRow()
        if current < 0:
            current = 0
        new = (current + delta) % n
        self._list.setCurrentRow(new)

    def _on_query_changed(self, text: str) -> None:
        text = text.strip().lower()
        if not text:
            self._render(self._commands)
            return
        # Subsequence ("fuzzy") matcher with rank: rows whose label
        # contains the query as a contiguous substring win the top
        # spots; subsequence-only matches fall below them.
        contiguous: list[Command] = []
        subsequence: list[Command] = []
        for c in self._commands:
            label_lc = c.label.lower()
            if text in label_lc:
                contiguous.append(c)
            elif _is_subsequence(text, label_lc):
                subsequence.append(c)
        self._render(contiguous + subsequence)

    def _render(self, commands: list[Command]) -> None:
        self._list.clear()
        if not commands:
            placeholder = QListWidgetItem("(nenhum comando combina)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
            return
        for c in commands:
            item = QListWidgetItem()
            label_html = (
                f"<div style='font-size:13px; color:{get_theme().palette.text};"
                f" font-weight:500;'>{c.label}</div>"
            )
            if c.hint:
                label_html += (
                    f"<div style='font-size:11px;"
                    f" color:{get_theme().palette.text_muted};'>{c.hint}</div>"
                )
            item.setData(Qt.ItemDataRole.UserRole, c.key)
            item.setData(Qt.ItemDataRole.DisplayRole, c.label)
            # Tooltip carries the shortcut so power users can learn it.
            if c.shortcut:
                item.setToolTip(f"{c.label} — {c.shortcut}")
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _fire_current(self, *_args) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        cmd = next((c for c in self._commands if c.key == key), None)
        self.close()
        if cmd is not None:
            try:
                cmd.handler()
            except Exception:
                # The palette is non-blocking UX glue; never let a
                # downstream handler bring it down. The host's own
                # error handling (QMessageBox etc.) already covers
                # user-visible failures.
                import traceback

                traceback.print_exc()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        pg = parent.geometry()
        x = pg.center().x() - self.DEFAULT_WIDTH // 2
        y = pg.top() + 96  # 96 px below the parent's top edge
        self.move(x, y)

    # ------------------------------------------------------------------
    @staticmethod
    def _self_qss() -> str:
        p = get_theme().palette
        return (
            f"QFrame#CommandPaletteBody {{"
            f"  background: {p.surface_elevated};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: 12px;"
            f"}}"
        )

    @staticmethod
    def _search_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"QLineEdit {{"
            f"  background: transparent;"
            f"  border: 0;"
            f"  border-bottom: 1px solid {p.border};"
            f"  padding: 6px 4px;"
            f"  color: {p.text};"
            f"  font-size: {t.body_md}px;"
            f"  selection-background-color: {p.selection_bg};"
            f"}}"
        )

    @staticmethod
    def _list_qss() -> str:
        p = get_theme().palette
        return (
            f"QListWidget {{"
            f"  background: transparent;"
            f"  border: 0;"
            f"  outline: 0;"
            f"  padding: 4px 0;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: 6px 10px;"
            f"  border-radius: 6px;"
            f"  color: {p.text};"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background: {p.accent_subtle_bg};"
            f"  color: {p.accent_subtle_text};"
            f"}}"
        )

    @staticmethod
    def _hint_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return f"color: {p.text_muted};font-size: {t.caption}px;"


def _is_subsequence(needle: str, haystack: str) -> bool:
    """Return True iff every char of ``needle`` appears in ``haystack``
    in order (not necessarily contiguously). Empty needle is always a
    match — kept consistent with VS Code's "type characters in
    sequence" matcher."""
    it = iter(haystack)
    return all(c in it for c in needle)
