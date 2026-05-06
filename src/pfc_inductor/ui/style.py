"""Global QSS stylesheet generator driven by `theme.Palette`.

Apply with:
    QApplication.instance().setStyleSheet(make_stylesheet(get_theme()))

The CSS subset used is what Qt6 supports: selectors with widget class names,
state pseudo-classes (`:hover`, `:focus`, `:disabled`, `:checked`, `:selected`),
and most box-model properties.

v2 ("MagnaDesign") helpers
--------------------------

The module is now organised as a set of *fragment* helpers (``base_qss``,
``buttons_qss``, ``inputs_qss``, ``cards_qss``, ``pills_qss``,
``sidebar_qss``, …) that ``make_stylesheet`` composes into the final string.
Callers that only want one fragment (e.g. ``card_qss(elevation=1)`` to style
a single ``QFrame.Card``) can import it directly.

Selector convention for v2 widgets
----------------------------------

- ``QFrame#Card`` — outer card frame (radius 16, surface, 1 px border).
- ``QFrame#Sidebar`` — navy chrome on the left.
- ``QPushButton[class~="SidebarItem"]`` — sidebar nav item.
- ``QPushButton[class~="Primary"]`` — primary CTA (accent fill).
- ``QPushButton[class~="Secondary"]`` — secondary CTA (outline).
- ``QPushButton[class~="Tertiary"]`` — ghost button (no border, hover bg).
- ``QToolButton[class~="Chip"]`` — view chips and segmented controls.
- ``QLabel.Pill`` — status pill (variant via ``pill`` dynamic property).
"""
from __future__ import annotations

from pfc_inductor.ui.theme import Sidebar, ThemeState, get_theme

# ---------------------------------------------------------------------------
# Public composers
# ---------------------------------------------------------------------------

def make_stylesheet(state: ThemeState | None = None) -> str:
    """Compose every fragment into the application-wide QSS string."""
    s = state or get_theme()
    parts = [
        base_qss(s),
        buttons_qss(s),
        toolbar_qss(s),
        inputs_qss(s),
        labels_qss(s),
        pills_qss(s),
        tabs_qss(s),
        tables_qss(s),
        lists_qss(s),
        statusbar_qss(s),
        progress_qss(s),
        splitter_qss(s),
        checkbox_qss(s),
        scrollbar_qss(s),
        # v2 additions
        cards_qss(s),
        sidebar_qss(s),
        v2_buttons_qss(s),
        chip_qss(s),
        stepper_qss(s),
    ]
    return "\n".join(parts)


# Convenience single-card helper used by tests and ad-hoc callers.
def card_qss(elevation: int = 1, state: ThemeState | None = None) -> str:
    """Return the QSS fragment for a ``QFrame#Card`` at the given elevation.

    Elevation 0 = flat (no shadow class hint), 1 = ``card_shadow_sm``,
    2 = ``card_shadow_md``. The shadow itself is attached via
    ``QGraphicsDropShadowEffect`` by the widget class — this fragment only
    sets the visual properties Qt's QSS can express (radius, border,
    surface).
    """
    s = state or get_theme()
    p = s.palette
    r = s.radius
    sp = s.spacing
    elev_class = f".elev{max(0, min(2, elevation))}"
    return f"""
QFrame#Card {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r.card}px;
    padding: 0px;
}}

QFrame#Card{elev_class} {{
    /* marker class — the QGraphicsDropShadowEffect is attached in code */
}}

QLabel#CardTitle {{
    color: {p.text};
    font-size: {s.type.title_md}px;
    font-weight: {s.type.semibold};
}}

QLabel#CardSubtitle {{
    color: {p.text_secondary};
    font-size: {s.type.caption}px;
}}

QFrame#CardBody {{
    background: transparent;
    border: 0;
    padding: {sp.card_pad}px;
}}

QFrame#CardHeader {{
    background: transparent;
    border: 0;
    border-bottom: 1px solid {p.border};
    padding: {sp.lg}px {sp.card_pad}px;
}}
"""


def pill_qss(variant: str, state: ThemeState | None = None) -> str:
    """Return the QSS for ``QLabel.Pill[variant="<v>"]`` only.

    Useful when a caller wants to style a single pill widget without
    pulling the whole pills_qss block. Variants:
    ``success`` | ``warning`` | ``danger`` | ``info`` | ``neutral`` |
    ``violet``.
    """
    s = state or get_theme()
    p = s.palette
    r = s.radius
    t = s.type
    table = {
        "success":  (p.success_bg, p.success),
        "warning":  (p.warning_bg, p.warning),
        "danger":   (p.danger_bg, p.danger),
        "info":     (p.info_bg, p.info),
        "neutral":  (p.bg, p.text_secondary),
        "violet":   (p.accent_violet_subtle_bg, p.accent_violet_subtle_text),
    }
    bg, fg = table[variant]
    return f"""
QLabel[class~="Pill"][pill="{variant}"] {{
    background: {bg};
    color: {fg};
    border-radius: {r.pill}px;
    padding: 2px 10px;
    font-size: {t.caption}px;
    font-weight: {t.semibold};
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
"""


# ---------------------------------------------------------------------------
# v1 fragments (preserved verbatim from prior version, factored)
# ---------------------------------------------------------------------------

def base_qss(s: ThemeState) -> str:
    p = s.palette
    t = s.type
    r = s.radius
    return f"""
* {{
    outline: 0;
}}

QMainWindow, QDialog, QWidget {{
    background-color: {p.bg};
    color: {p.text};
    font-family: {t.ui_family_brand};
    font-size: {t.body}px;
}}

QToolTip {{
    background-color: {p.surface_elevated};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.sm}px;
    padding: 4px 8px;
}}

QGroupBox {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    margin-top: {s.spacing.md}px;
    padding: 12px {s.spacing.md}px 6px {s.spacing.md}px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {s.spacing.md}px;
    top: -2px;
    padding: 0 {s.spacing.sm}px;
    background-color: {p.surface};
    color: {p.text_muted};
    font-size: {t.caption}px;
    font-weight: {t.semibold};
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}
"""


def buttons_qss(s: ThemeState) -> str:
    p = s.palette
    t = s.type
    r = s.radius
    return f"""
QPushButton {{
    background-color: {p.surface_elevated};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {r.md}px;
    padding: 4px 10px;
    font-weight: {t.medium};
    min-height: 18px;
}}

QPushButton:hover {{
    background-color: {p.bg};
    border-color: {p.text_muted};
}}

QPushButton:pressed {{
    background-color: {p.border};
}}

QPushButton:disabled {{
    color: {p.text_muted};
    border-color: {p.border};
    background-color: {p.surface};
}}

QPushButton[primary="true"] {{
    background-color: {p.accent};
    color: {p.text_inverse};
    border-color: {p.accent};
}}
QPushButton[primary="true"]:hover {{
    background-color: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton[primary="true"]:pressed {{
    background-color: {p.accent_pressed};
    border-color: {p.accent_pressed};
}}

QPushButton[ghost="true"] {{
    background-color: transparent;
    border-color: transparent;
}}
QPushButton[ghost="true"]:hover {{
    background-color: {p.bg};
}}

/* Keyboard focus ring — applies to every QPushButton variant. Qt6 QSS
 * does not support `outline` on QWidget reliably, so we widen the
 * border to 2px and switch its colour to the focus token. The border
 * is already 1px on every button, so this only nudges the layout by
 * a single pixel — acceptable since focus is a transient state. */
QPushButton:focus {{
    border: 2px solid {p.focus_ring};
}}
QPushButton[ghost="true"]:focus {{
    border: 2px solid {p.focus_ring};
    background-color: {p.bg};
}}
"""


def toolbar_qss(s: ThemeState) -> str:
    p = s.palette
    t = s.type
    r = s.radius
    return f"""
QToolBar {{
    background-color: {p.surface};
    border: 0;
    border-bottom: 1px solid {p.border};
    padding: 4px 8px;
    spacing: 2px;
}}

QToolBar QToolButton {{
    background-color: transparent;
    color: {p.text_secondary};
    border: 1px solid transparent;
    border-radius: {r.md}px;
    padding: 6px 10px;
    margin: 0 1px;
    font-weight: {t.medium};
}}
QToolBar QToolButton:hover {{
    background-color: {p.bg};
    color: {p.text};
    border-color: {p.border};
}}
QToolBar QToolButton:pressed {{
    background-color: {p.border};
}}

QToolBar::separator {{
    background-color: {p.border};
    width: 1px;
    margin: 6px 8px;
}}
"""


def inputs_qss(s: ThemeState) -> str:
    p = s.palette
    r = s.radius
    return f"""
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {r.sm}px;
    padding: 2px 6px;
    selection-background-color: {p.selection_bg};
    selection-color: {p.text};
    min-height: 16px;
}}

QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {p.accent};
}}

QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled,
QComboBox:disabled {{
    background-color: {p.bg};
    color: {p.text_muted};
}}

QComboBox QAbstractItemView {{
    background-color: {p.surface_elevated};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    selection-background-color: {p.accent_subtle_bg};
    selection-color: {p.accent_subtle_text};
    padding: 2px;
}}

QComboBox::drop-down {{
    border: 0;
    width: 22px;
}}

QDoubleSpinBox::up-button, QSpinBox::up-button,
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    border: 0;
    background: transparent;
    width: 16px;
}}
"""


def labels_qss(s: ThemeState) -> str:
    p = s.palette
    t = s.type
    return f"""
QLabel[role="caption"] {{
    color: {p.text_muted};
    font-size: {t.caption}px;
    font-weight: {t.semibold};
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}
QLabel[role="muted"] {{
    color: {p.text_muted};
    font-size: {t.body}px;
}}
QLabel[role="title"] {{
    color: {p.text};
    font-size: {t.title_md}px;
    font-weight: {t.semibold};
}}
QLabel[role="display"] {{
    color: {p.text};
    font-size: {t.display}px;
    font-weight: {t.bold};
}}
QLabel[role="kpi-label"] {{
    color: {p.text_muted};
    font-size: {t.caption}px;
}}
QLabel[role="kpi-value"] {{
    color: {p.text};
    font-family: {t.numeric_family};
    font-size: {t.body_md}px;
    font-weight: {t.medium};
}}
QLabel[role="kpi-value-strong"] {{
    color: {p.text};
    font-family: {t.numeric_family};
    font-size: {t.title_sm}px;
    font-weight: {t.bold};
}}
"""


def pills_qss(s: ThemeState) -> str:
    """All pill variants in one block. Adds the v2 ``violet`` variant."""
    return (
        pill_qss("success", s)
        + pill_qss("warning", s)
        + pill_qss("danger", s)
        + pill_qss("info", s)
        + pill_qss("neutral", s)
        + pill_qss("violet", s)
        + _legacy_pill_alias_qss(s)
    )


def _legacy_pill_alias_qss(s: ThemeState) -> str:
    """v1 used a flat ``QLabel[pill="..."]`` selector (no class). Keep it
    aliased to the v2 ``QLabel[class~="Pill"][pill="..."]`` so existing widgets that
    only set the dynamic property still pick up the styles."""
    p = s.palette
    t = s.type
    r = s.radius
    return f"""
QLabel[pill="success"], QLabel[pill="warning"], QLabel[pill="danger"],
QLabel[pill="info"], QLabel[pill="neutral"], QLabel[pill="violet"] {{
    border-radius: {r.pill}px;
    padding: 2px 10px;
    font-size: {t.caption}px;
    font-weight: {t.semibold};
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
QLabel[pill="success"]  {{ background: {p.success_bg}; color: {p.success}; }}
QLabel[pill="warning"]  {{ background: {p.warning_bg}; color: {p.warning}; }}
QLabel[pill="danger"]   {{ background: {p.danger_bg};  color: {p.danger};  }}
QLabel[pill="info"]     {{ background: {p.info_bg};    color: {p.info};    }}
QLabel[pill="neutral"]  {{ background: {p.bg};         color: {p.text_secondary}; }}
QLabel[pill="violet"]   {{ background: {p.accent_violet_subtle_bg}; color: {p.accent_violet_subtle_text}; }}
"""


def tabs_qss(s: ThemeState) -> str:
    p = s.palette
    t = s.type
    return f"""
QTabWidget::pane {{
    border: 0;
    border-top: 1px solid {p.border};
    background: {p.surface};
}}

QTabBar {{
    background: transparent;
    border: 0;
}}

QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    padding: 8px 14px;
    margin-right: 2px;
    border: 0;
    border-bottom: 2px solid transparent;
    font-weight: {t.medium};
}}

QTabBar::tab:hover {{
    color: {p.text};
}}

QTabBar::tab:selected {{
    color: {p.accent};
    border-bottom-color: {p.accent};
}}
"""


def tables_qss(s: ThemeState) -> str:
    p = s.palette
    t = s.type
    r = s.radius
    return f"""
QTableWidget, QTableView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    gridline-color: {p.border};
    selection-background-color: {p.accent_subtle_bg};
    selection-color: {p.accent_subtle_text};
}}

QHeaderView::section {{
    background-color: {p.bg};
    color: {p.text_muted};
    border: 0;
    border-bottom: 1px solid {p.border};
    border-right: 1px solid {p.border};
    padding: 6px 10px;
    font-size: {t.caption}px;
    font-weight: {t.semibold};
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}

QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
    border: 0;
}}
"""


def lists_qss(s: ThemeState) -> str:
    p = s.palette
    r = s.radius
    return f"""
QListWidget, QListView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {r.md}px;
    padding: 4px;
}}
QListWidget::item, QListView::item {{
    padding: 6px 10px;
    border-radius: {r.sm}px;
}}
QListWidget::item:hover {{
    background-color: {p.bg};
}}
QListWidget::item:selected, QListView::item:selected {{
    background-color: {p.accent_subtle_bg};
    color: {p.accent_subtle_text};
}}
"""


def statusbar_qss(s: ThemeState) -> str:
    p = s.palette
    t = s.type
    return f"""
QStatusBar {{
    background-color: {p.surface};
    color: {p.text_secondary};
    border-top: 1px solid {p.border};
    font-size: {t.caption}px;
}}
QStatusBar::item {{ border: 0; }}
"""


def progress_qss(s: ThemeState) -> str:
    p = s.palette
    r = s.radius
    return f"""
QProgressBar {{
    background-color: {p.bg};
    border: 1px solid {p.border};
    border-radius: {r.pill}px;
    height: 6px;
    text-align: center;
    color: {p.text_secondary};
}}
QProgressBar::chunk {{
    background-color: {p.accent};
    border-radius: {r.pill}px;
}}
"""


def splitter_qss(s: ThemeState) -> str:
    p = s.palette
    return f"""
QSplitter::handle {{
    background-color: {p.border};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
"""


def checkbox_qss(s: ThemeState) -> str:
    p = s.palette
    return f"""
QCheckBox, QRadioButton {{
    color: {p.text};
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {p.border_strong};
    border-radius: 3px;
    background-color: {p.surface};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p.accent};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {p.accent};
    border-color: {p.accent};
}}
QRadioButton::indicator {{
    border-radius: 7px;
}}
"""


def scrollbar_qss(s: ThemeState) -> str:
    p = s.palette
    return f"""
QScrollBar:vertical {{
    background: {p.bg};
    width: 10px;
    margin: 0;
    border-left: 1px solid {p.border};
}}
QScrollBar::handle:vertical {{
    background: {p.border_strong};
    border-radius: 4px;
    min-height: 30px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.text_muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    background: transparent;
    height: 0;
    width: 0;
    border: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: {p.bg};
    height: 10px;
    margin: 0;
    border-top: 1px solid {p.border};
}}
QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 4px;
    min-width: 30px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p.text_muted};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    background: transparent;
    height: 0;
    width: 0;
    border: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
"""


# ---------------------------------------------------------------------------
# v2 fragments
# ---------------------------------------------------------------------------

def cards_qss(s: ThemeState) -> str:
    """Top-level card frame styling. Drop shadows are attached in code via
    ``QGraphicsDropShadowEffect`` because Qt6 QSS does not implement
    ``box-shadow``."""
    return card_qss(elevation=1, state=s)


def sidebar_qss(s: ThemeState) -> str:
    """Navy sidebar block. References the theme-invariant :data:`SIDEBAR`
    palette, so the rendered fragment is byte-equal across light/dark."""
    sb: Sidebar = s.sidebar
    t = s.type
    r = s.radius
    return f"""
QFrame#Sidebar {{
    background-color: {sb.bg};
    border: 0;
    border-right: 1px solid {sb.border};
}}

QFrame#SidebarHeader {{
    background: transparent;
    border: 0;
    padding: {s.spacing.lg}px {s.spacing.card_pad}px;
}}

QLabel#SidebarLogoText {{
    color: {sb.text_active};
    font-family: {t.ui_family_brand};
    font-size: {t.title_md}px;
    font-weight: {t.semibold};
    letter-spacing: -0.01em;
}}

QLabel#SidebarLogoCaption {{
    color: {sb.text_muted};
    font-family: {t.ui_family_brand};
    font-size: {t.caption}px;
}}

QPushButton[class~="SidebarItem"] {{
    background-color: transparent;
    color: {sb.text_muted};
    border: 0;
    border-radius: {r.button}px;
    padding: 8px 12px;
    text-align: left;
    font-family: {t.ui_family_brand};
    font-size: {t.body_md}px;
    font-weight: {t.medium};
    min-height: 22px;
}}
QPushButton[class~="SidebarItem"]:hover {{
    background-color: {sb.bg_hover};
    color: {sb.text};
}}
QPushButton[class~="SidebarItem"]:checked,
QPushButton[class~="SidebarItem"][active="true"] {{
    background-color: {sb.bg_active};
    color: {sb.text_active};
    font-weight: {t.semibold};
}}

QFrame#SidebarFooter {{
    background: transparent;
    border: 0;
    border-top: 1px solid {sb.border};
    padding: {s.spacing.md}px {s.spacing.card_pad}px;
}}

QLabel#SidebarVersion {{
    color: {sb.text_muted};
    font-family: {t.ui_family_brand};
    font-size: {t.caption}px;
}}
"""


def v2_buttons_qss(s: ThemeState) -> str:
    """Primary / Secondary / Tertiary CTA classes used by the workspace
    header and dashboard footers. Distinct from v1 ``[primary="true"]``
    dynamic-property buttons (kept for back-compat)."""
    p = s.palette
    t = s.type
    r = s.radius
    return f"""
QPushButton[class~="Primary"] {{
    background-color: {p.accent};
    color: {p.text_inverse};
    border: 1px solid {p.accent};
    border-radius: {r.button}px;
    padding: 8px 16px;
    font-family: {t.ui_family_brand};
    font-weight: {t.semibold};
    min-height: 22px;
}}
QPushButton[class~="Primary"]:hover {{
    background-color: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton[class~="Primary"]:pressed {{
    background-color: {p.accent_pressed};
    border-color: {p.accent_pressed};
}}
QPushButton[class~="Primary"]:disabled {{
    background-color: {p.border};
    border-color: {p.border};
    color: {p.text_muted};
}}

QPushButton[class~="Secondary"] {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {r.button}px;
    padding: 8px 16px;
    font-family: {t.ui_family_brand};
    font-weight: {t.medium};
    min-height: 22px;
}}
QPushButton[class~="Secondary"]:hover {{
    background-color: {p.bg};
    border-color: {p.text_muted};
}}
QPushButton[class~="Secondary"]:pressed {{
    background-color: {p.border};
}}

QPushButton[class~="Tertiary"] {{
    background-color: transparent;
    color: {p.text_secondary};
    border: 1px solid transparent;
    border-radius: {r.button}px;
    padding: 6px 12px;
    font-family: {t.ui_family_brand};
    font-weight: {t.medium};
}}
QPushButton[class~="Tertiary"]:hover {{
    background-color: {p.bg};
    color: {p.text};
    border-color: {p.border};
}}

/* v2 focus rings — same accessibility rationale as the v1 block above.
 * We re-declare here because the [class~="..."] selector has higher
 * specificity than bare ``QPushButton:focus`` and would otherwise lose
 * the focus visual to the v2 button colour rules. */
QPushButton[class~="Primary"]:focus,
QPushButton[class~="Secondary"]:focus,
QPushButton[class~="Tertiary"]:focus {{
    border: 2px solid {p.focus_ring};
}}
"""


def chip_qss(s: ThemeState) -> str:
    """Chips / segmented controls used by the 3D viewer view selector
    and the topology pills row."""
    p = s.palette
    t = s.type
    r = s.radius
    return f"""
QToolButton[class~="Chip"] {{
    background-color: {p.surface};
    color: {p.text_secondary};
    border: 1px solid {p.border};
    border-radius: {r.chip}px;
    padding: 6px 12px;
    font-family: {t.ui_family_brand};
    font-size: {t.caption}px;
    font-weight: {t.medium};
}}
QToolButton[class~="Chip"]:hover {{
    background-color: {p.bg};
    color: {p.text};
}}
QToolButton[class~="Chip"]:checked {{
    background-color: {p.accent_subtle_bg};
    color: {p.accent_subtle_text};
    border-color: {p.accent};
}}
"""


def stepper_qss(s: ThemeState) -> str:
    """Workflow stepper visual states."""
    p = s.palette
    t = s.type
    return f"""
QFrame#Stepper {{
    background: transparent;
    border: 0;
}}

QFrame#StepperSegment[stepperState="done"] QLabel#StepperCircle {{
    background: {p.success};
    color: {p.text_inverse};
    border-radius: 12px;
    min-width: 24px;
    min-height: 24px;
    qproperty-alignment: AlignCenter;
    font-weight: {t.semibold};
}}

QFrame#StepperSegment[stepperState="active"] QLabel#StepperCircle {{
    background: {p.accent_violet};
    color: #FFFFFF;
    border-radius: 12px;
    min-width: 24px;
    min-height: 24px;
    qproperty-alignment: AlignCenter;
    font-weight: {t.semibold};
}}

QFrame#StepperSegment[stepperState="pending"] QLabel#StepperCircle {{
    background: {p.surface};
    color: {p.text_muted};
    border: 1px solid {p.border_strong};
    border-radius: 12px;
    min-width: 24px;
    min-height: 24px;
    qproperty-alignment: AlignCenter;
    font-weight: {t.medium};
}}

QLabel#StepperLabel {{
    color: {p.text_secondary};
    font-family: {t.ui_family_brand};
    font-size: {t.caption}px;
    font-weight: {t.medium};
}}

QFrame#StepperSegment[stepperState="active"] QLabel#StepperLabel {{
    color: {p.accent_violet_subtle_text};
    font-weight: {t.semibold};
}}

QFrame#StepperSegment[stepperState="done"] QLabel#StepperLabel {{
    color: {p.text};
}}

QFrame#StepperLine {{
    background: {p.border};
    max-height: 1px;
    min-height: 1px;
}}
"""
