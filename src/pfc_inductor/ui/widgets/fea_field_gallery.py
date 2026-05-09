"""FEA field-plot gallery — surface FEMMT's auto-generated PNGs.

FEMMT writes a handful of post-processing PNGs into its working
directory after a successful solve: the meshed geometry, the
B-field magnitude over the geometry, the H-field, current
density on the conductors, and so on. ``FEAValidation.fem_path``
points at that directory; this widget recursively scans it for
``*.png`` files, categorises them by filename heuristics, and
displays a thumbnail grid the user can click to enlarge.

Why this widget, not a direct mesh / field renderer:

We don't bind to gmsh's Python API or parse ``.msh`` files
ourselves. FEMMT already generates the visualisations (with the
right colour-mapping + node-averaging + colour-bar legend) — we
just need to display what's already on disk. That's a 100-line
QLabel grid instead of a 600-line FE-renderer.

Empty-state: when ``fem_path`` doesn't exist, isn't a directory,
or contains no PNGs, the widget shows a centred hint explaining
that some FEA backends don't auto-export field plots — keeps
the dialog's vertical layout stable.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.ui.theme import get_theme, on_theme_changed


# Filename heuristics → human-readable category. Ordered so the
# first match wins (mesh appears in many filenames; B / H are
# more specific). Keys are case-insensitive substrings.
#
# The first six rules match what our headless ``pos_renderer`` and
# FEMMT itself drop into the working directory:
#   - ``Magb.png``        — magnetic flux density magnitude
#   - ``j2F_density.png`` — ohmic-loss density (frequency domain)
#   - ``j2H_density.png`` — litz ohmic-loss density
#   - ``jH_density.png``  — H-field
#   - ``raz.png``         — vector potential A_z
# The longer fallback rules cover plot variants from FEMMT's
# `visualize_loss_distribution` (loss_*.png) and any future
# user-supplied plots dropped in the same dir.
_CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    # Sidecar plots produced by ``pos_renderer`` — listed first
    # so the more-specific ``_centerline`` / ``_histogram``
    # suffixes win over the bare ``magb`` / ``b_field`` rules
    # below.
    ("_centerline", "B along gap centerline"),
    ("_histogram", "B distribution"),
    # Native FEMMT field outputs (rendered by pos_renderer).
    ("magb", "B-field magnitude"),
    ("j2f_density", "Ohmic loss density"),
    ("j2h_density", "Litz ohmic loss"),
    ("jh_density", "H-field magnitude"),
    ("raz", "Vector potential A_z"),
    ("b_field", "B-field magnitude"),
    ("flux_density", "Flux density"),
    ("h_field", "H-field"),
    ("current_density", "Current density"),
    ("eddy", "Eddy currents"),
    ("loss", "Loss density"),
    ("current", "Currents"),
    ("temperature", "Temperature"),
    ("mesh", "Meshed geometry"),
    ("hybrid_color", "Meshed geometry"),
    ("geometry", "Geometry"),
    ("model", "Model"),
    ("interpolation", "B–H curve"),
)
_DEFAULT_CATEGORY = "Other"


# Per-category engineering context shown under each thumbnail and
# in the click-to-enlarge lightbox. Keys match the labels emitted
# by ``_CATEGORY_RULES`` above. Each value is a 2-tuple:
#
#   (one_liner, detailed_paragraph)
#
# - ``one_liner`` (≤ 90 chars) appears under the thumbnail caption
#   so the engineer scanning the gallery instantly knows what the
#   plot represents.
# - ``detailed_paragraph`` (~3 sentences) appears in the lightbox
#   side panel, telling them what to look for and what would count
#   as trouble. Engineers don't usually inspect FEA plots out of
#   curiosity — they're checking a hypothesis (saturation? loss
#   crowding? flux leakage?), so the text is task-oriented.
_CATEGORY_HELP: dict[str, tuple[str, str]] = {
    "B-field magnitude": (
        "Magnetic flux density |B| across the cross-section.",
        "Bright (yellow) = highest flux density, dark (purple) = lowest. "
        "Watch for elements approaching the material's Bsat — that's where the "
        "design saturates first under load. The brightest band is usually at the "
        "air gap or along the toroid's inner radius. If your peak |B| is within "
        "20 % of Bsat, the design has no headroom for transients.",
    ),
    "Flux density": (
        "Magnetic flux density |B| across the cross-section.",
        "Bright = high |B|, dark = low. Compare the peak against Bsat for the "
        "core material; anything within 20 % of Bsat means no transient "
        "headroom. Concentrated bright spots near the gap are normal — flux "
        "fringes there.",
    ),
    "Ohmic loss density": (
        "Per-element copper dissipation [W/m³].",
        "Bright spots = where conductor losses concentrate at the switching "
        "frequency. Concentration on the conductor edge indicates skin / "
        "proximity-effect crowding; uniform colour over the wire means DC-"
        "dominated dissipation. Total integrated value matches what the "
        "analytic loss model predicts — this view shows where the heat lives.",
    ),
    "Litz ohmic loss": (
        "Effective per-element loss for litz bundles [W/m³].",
        "FEMMT's litz model averages strand-level current crowding back into "
        "the bundle. Compare against the solid-wire equivalent at the same "
        "current to quantify how much the litz construction is buying you.",
    ),
    "H-field magnitude": (
        "Magnetising-force distribution |H| [A/m].",
        "On average H = N·I/le, but local H varies — usually highest inside "
        "the gap. Use this to verify the gap region is doing the work and "
        "stray flux through the core is small.",
    ),
    "Vector potential A_z": (
        "Iso-contours of A_z are flux lines.",
        "Lines of equal A_z trace the path of magnetic flux. A clean, "
        "channelled pattern through the core means flux is staying where you "
        "want it; bowed-out contours indicate leakage flux into surrounding "
        "geometry (enclosure, busbars, neighbouring components).",
    ),
    "Meshed geometry": (
        "The triangulation FEMMT solved on.",
        "Triangles colour-coded by region (core / gap / winding / insulation). "
        "Coarse mesh near the air gap or the conductor surface makes the "
        "FEA result optimistic — those are the high-gradient regions where "
        "field accuracy matters most. If the gap has < 5 elements across, "
        "treat |B| numbers as ±10 % uncertain.",
    ),
    "Geometry": (
        "FEMMT's interpretation of your design.",
        "Sanity-check that the core OD/ID/window match the catalog entry "
        "and the winding cells are stacked the way you specified. Mismatches "
        "here invalidate the L and B numbers downstream.",
    ),
    "B–H curve": (
        "Material B(H) interpolation FEMMT used.",
        "Sanity check that the catalog μ(H) curve was loaded correctly. The "
        "operating point should sit on the linear portion at nominal current "
        "and nudge toward the knee only at peak excursions.",
    ),
    "Currents": (
        "Conductor currents the FEA imposed.",
        "Confirms FEMMT applied the bias current we asked for. The label "
        "should match the dialog's ``test_current_A`` field.",
    ),
    "Eddy currents": (
        "Induced eddy-current density.",
        "Eddy currents oppose the changing flux in the core (and any "
        "conducting material exposed to dB/dt). Bright spots = parasitic "
        "loss centres; for laminated cores these should be tiny.",
    ),
    "Loss density": (
        "Volumetric loss density [W/m³].",
        "Where the heat is generated. Integrate visually: a uniform low "
        "colour over a large volume can exceed a small bright spot.",
    ),
    "Temperature": (
        "Predicted temperature distribution.",
        "Solid-state thermal solve. Cross-check the peak against the "
        "winding's insulation rating and the core's Curie temperature.",
    ),
    "B along gap centerline": (
        "1-D slice of |B| along z = 0 (gap line).",
        "The 2-D heatmap can hide saturation crowding behind a "
        "small bright pixel; this 1-D plot puts a hard number on every "
        "radial position. The peak is where the design saturates first — "
        "if it's within 20 % of Bsat, your transient headroom is gone.",
    ),
    "B distribution": (
        "Histogram + CDF of |B| weighted by element area.",
        "The bar chart shows what fraction of the cross-section sits at "
        "each |B| level; the CDF curve overlays cumulative volume. A "
        "long tail to high |B| signals saturation risk; a fat body well "
        "below Bsat means you're using the core conservatively. Read the "
        "CDF as 'X % of the volume is below Y T'.",
    ),
    "Other": (
        "Auxiliary plot exported by the FEA backend.",
        "Inspect the filename and the plot's own colorbar / labels for "
        "context. Open the source PNG in an external viewer if needed.",
    ),
}


class _Artifact(NamedTuple):
    path: Path
    category: str


def _categorise(path: Path) -> str:
    name = path.name.lower()
    for key, label in _CATEGORY_RULES:
        if key in name:
            return label
    return _DEFAULT_CATEGORY


def _scan(fem_path: Path | str | None) -> list[_Artifact]:
    """Walk ``fem_path`` recursively for ``*.png`` files. Returns
    a list sorted by category-then-name so the gallery groups
    related plots even when they live in different subfolders."""
    if not fem_path:
        return []
    root = Path(fem_path)
    if not root.exists() or not root.is_dir():
        return []
    out: list[_Artifact] = []
    for p in sorted(root.rglob("*.png")):
        # Skip thumbnails / icons FEMMT sometimes drops in its
        # mesh subfolder — they're tiny and uninformative
        # (~5 KB) and crowd the gallery.
        try:
            if p.stat().st_size < 4096:
                continue
        except OSError:
            continue
        out.append(_Artifact(p, _categorise(p)))
    # Sort: category first (alpha), then filename within
    # category. The category-rule order above is the priority
    # for matching; this final sort is purely for display.
    out.sort(key=lambda a: (a.category, a.path.name))
    return out


def _humanise(name: str) -> str:
    """Filename → display label. Drops the extension, replaces
    underscores with spaces, and Title-Cases the first letter of
    each word."""
    stem = Path(name).stem
    parts = re.split(r"[_-]+", stem)
    return " ".join(p.capitalize() for p in parts if p)


class _Thumbnail(QFrame):
    """One clickable image card in the gallery.

    Sized at 480×420 — large enough that matplotlib axis ticks,
    colorbar labels, and units stay readable inline (the previous
    220×200 forced users to click into the lightbox just to read
    the colorbar). Caption carries the category title, the per-
    category one-liner from ``_CATEGORY_HELP``, and a click-to-
    enlarge hint.
    """

    # Geometry: image area 480×320 + caption 100, total 480×420.
    # Sized for a 2-column layout in the dialog's ~1080-px content
    # area, with margins and spacing budgeted in.
    THUMB_W = 480
    THUMB_H = 420
    IMG_H = 320

    # Emits ``(path, category)`` so the gallery can route the
    # click to the lightbox along with the per-category context
    # text — without the gallery having to maintain a separate
    # path → artifact map.
    clicked = Signal(Path, str)

    def __init__(self, artifact: _Artifact, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._path = artifact.path
        self._artifact = artifact
        self.setObjectName("FEAArtifactThumb")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to enlarge")

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Image area — 480 × 320, KeepAspectRatio + smooth scale.
        # At this size the matplotlib colorbar ticks (~9pt) are
        # legible without zooming.
        self._img = QLabel()
        self._img.setObjectName("FEAArtifactThumbImg")
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setFixedHeight(self.IMG_H)
        pix = QPixmap(str(self._path))
        if not pix.isNull():
            self._img.setPixmap(
                pix.scaled(
                    self.THUMB_W,
                    self.IMG_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self._img.setText("(unreadable)")
        v.addWidget(self._img)

        # Caption block: category title + one-liner from
        # _CATEGORY_HELP + hover hint. Left-aligned so the text
        # block reads as a card, not a centred annotation.
        p = get_theme().palette
        one_liner, _ = _CATEGORY_HELP.get(
            artifact.category, _CATEGORY_HELP["Other"]
        )
        caption = QLabel(
            f"<div style='margin: 0; padding: 0;'>"
            f"<b style='color:{p.text}; font-size: 13px;'>"
            f"{artifact.category}</b><br>"
            f"<span style='color:{p.text_secondary}; font-size: 11px;'>"
            f"{one_liner}</span><br>"
            f"<span style='color:{p.text_muted}; font-size: 10px;'>"
            f"{_humanise(artifact.path.name)} · click to enlarge</span>"
            f"</div>"
        )
        caption.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        caption.setWordWrap(True)
        caption.setFixedHeight(self.THUMB_H - self.IMG_H)
        caption.setStyleSheet("padding: 8px 12px;")
        v.addWidget(caption)

        self._refresh_qss()
        on_theme_changed(self._refresh_qss)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path, self._artifact.category)
        super().mousePressEvent(event)

    def _refresh_qss(self) -> None:
        p = get_theme().palette
        r = get_theme().radius
        self.setStyleSheet(
            f"#FEAArtifactThumb {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: {r.md}px;"
            f"}}"
            f"#FEAArtifactThumb:hover {{"
            f"  border: 1px solid {p.accent_violet};"
            f"}}"
        )


class _LightboxDialog(QDialog):
    """Click-to-enlarge modal: full-size PNG on the left, side
    panel on the right with the category title, the long-form
    explanation from ``_CATEGORY_HELP``, and the source path.

    Side-panel pattern (over a "just the image, full bleed"
    lightbox) is deliberate: the user clicked through to *learn*
    what the plot means, so we surface the engineering context
    next to the figure instead of forcing a context switch back
    to the gallery caption.
    """

    def __init__(
        self,
        image_path: Path,
        category: str = _DEFAULT_CATEGORY,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{category} — {image_path.name}")
        # Wider than before so the side panel + bigger image both
        # fit without crowding. 1240 × 760 is comfortable on a
        # 1440-px laptop display and still small enough for a
        # 1280-px display.
        self.resize(1240, 760)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # ── Title row ──
        p = get_theme().palette
        title = QLabel(category)
        title.setStyleSheet(
            f"font-size: 17px; font-weight: 700; color: {p.text}; "
            f"padding-bottom: 2px;"
        )
        outer.addWidget(title)

        # ── Body: image | side panel ──
        body = QHBoxLayout()
        body.setSpacing(16)

        # Image.
        self._img = QLabel()
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setMinimumSize(820, 620)
        pix = QPixmap(str(image_path))
        if not pix.isNull():
            self._img.setPixmap(
                pix.scaled(
                    820,
                    620,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self._img.setText("(image could not be loaded)")
        body.addWidget(self._img, 3)

        # Side panel with engineering explanation + source path.
        side = QVBoxLayout()
        side.setSpacing(10)

        _, detail = _CATEGORY_HELP.get(category, _CATEGORY_HELP[_DEFAULT_CATEGORY])
        what_h = QLabel("WHAT YOU'RE LOOKING AT")
        what_h.setStyleSheet(
            f"font-size: 11px; font-weight: 700; letter-spacing: 0.6px; "
            f"color: {p.text_muted};"
        )
        side.addWidget(what_h)

        what_p = QLabel(detail)
        what_p.setWordWrap(True)
        what_p.setStyleSheet(
            f"font-size: 13px; color: {p.text}; line-height: 1.5;"
        )
        side.addWidget(what_p)

        side.addSpacing(6)

        src_h = QLabel("SOURCE")
        src_h.setStyleSheet(
            f"font-size: 11px; font-weight: 700; letter-spacing: 0.6px; "
            f"color: {p.text_muted};"
        )
        side.addWidget(src_h)

        path_label = QLabel(str(image_path))
        path_label.setStyleSheet(
            f"font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace; "
            f"font-size: 11px; color: {p.text_secondary};"
        )
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        side.addWidget(path_label)

        side.addStretch(1)
        body.addLayout(side, 2)
        outer.addLayout(body, 1)

        # ── Close row ──
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setAutoDefault(False)
        btn_close.setDefault(False)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        outer.addLayout(btn_row)


class FEAFieldGallery(QWidget):
    """Header banner + grid of FEMMT post-processing PNGs.

    Layout:
        ┌────────────────────────────────────────────────────────┐
        │  Info banner — what these plots are, what to look for. │
        ├──────────────────────────┬──────────────────────────────┤
        │  Thumbnail (480 × 420)   │  Thumbnail                   │
        │  category title          │  ...                         │
        │  one-liner               │                              │
        │  filename · click hint   │                              │
        ├──────────────────────────┴──────────────────────────────┤
        │  ...                                                    │
        └─────────────────────────────────────────────────────────┘

    Two columns instead of three at this larger card size — fits
    comfortably in the dialog's ~1080-px content area with room
    for the scrollbar.
    """

    # Card-size pick: at 480 × 420 the matplotlib content inside
    # each thumbnail (axis ticks, colorbar, units) is legible at
    # native scale. The user gets the gist without clicking.
    COLUMNS = 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self._scroll)

        # Container swapped between empty-state and grid layouts.
        self._inner = QWidget()
        self._scroll.setWidget(self._inner)
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(8, 8, 8, 8)
        self._inner_layout.setSpacing(12)

        self._show_empty(
            "Run a FEA validation. Field plots show up here when "
            "the backend exports them."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def populate_from_path(self, fem_path: str | None) -> None:
        """Scan ``fem_path`` for PNG artifacts and rebuild the grid.

        Empty state when nothing's there or the path doesn't
        exist — the widget never errors visibly, just shows the
        empty message.
        """
        self._clear_grid()
        artifacts = _scan(fem_path)
        if not artifacts:
            self._show_empty(
                "No field plots in the FEA working directory yet.\n"
                "Run a FEA validation — FEMMT writes a meshed-"
                "geometry PNG and a B–H interpolation curve into "
                "the working directory after the solve. The legacy "
                "FEMM backend does not auto-export plots."
            )
            return
        self._render_grid(artifacts)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _clear_grid(self) -> None:
        """Drop any prior empty-state label or thumbnail grid."""
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _show_empty(self, message: str) -> None:
        self._clear_grid()
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color: {get_theme().palette.text_muted};"
            "padding: 60px 20px;"
        )
        self._inner_layout.addWidget(lbl, 1, Qt.AlignmentFlag.AlignCenter)

    def _render_grid(self, artifacts: Iterable[_Artifact]) -> None:
        """Build the explanatory banner + 2-column grid of cards."""
        artifact_list = list(artifacts)

        # ── Top banner: "what you're looking at, where to look" ──
        # Lives above the grid so the engineer can read it once,
        # then scan the cards. Stays out of the lightbox modal to
        # keep that view focused on a single plot.
        banner = self._build_banner(artifact_list)
        self._inner_layout.addWidget(banner)

        # ── Card grid ──
        grid_holder = QFrame()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)

        for i, art in enumerate(artifact_list):
            thumb = _Thumbnail(art)
            thumb.clicked.connect(self._on_thumb_clicked)
            row = i // self.COLUMNS
            col = i % self.COLUMNS
            grid.addWidget(thumb, row, col)

        # Pad the last row so thumbnails stay left-aligned even
        # when the artifact count isn't a multiple of COLUMNS.
        n = len(artifact_list)
        last_row_filled = n % self.COLUMNS
        if last_row_filled and last_row_filled < self.COLUMNS:
            for col in range(last_row_filled, self.COLUMNS):
                spacer = QWidget()
                grid.addWidget(spacer, n // self.COLUMNS, col)

        self._inner_layout.addWidget(grid_holder)
        self._inner_layout.addStretch(1)

    def _build_banner(self, artifacts: list[_Artifact]) -> QWidget:
        """Top-of-gallery info card. Mentions the categories
        actually present in the result (no point describing flux
        lines if the user only has a B-field plot) and gives a
        one-paragraph "how to read FEA field plots" primer."""
        p = get_theme().palette
        r = get_theme().radius

        frame = QFrame()
        frame.setObjectName("FEAGalleryBanner")
        frame.setStyleSheet(
            f"QFrame#FEAGalleryBanner {{"
            f"  background: {p.surface_elevated};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: {r.md}px;"
            f"  padding: 14px 16px;"
            f"}}"
        )
        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)

        title = QLabel("How to read these plots")
        title.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {p.text};"
        )
        v.addWidget(title)

        # Categories present in this run, in display order.
        present = []
        seen: set[str] = set()
        for art in artifacts:
            if art.category not in seen:
                seen.add(art.category)
                present.append(art.category)

        bullets = []
        for cat in present:
            one_liner, _ = _CATEGORY_HELP.get(cat, _CATEGORY_HELP[_DEFAULT_CATEGORY])
            bullets.append(
                f"<li><b>{cat}</b> — {one_liner}</li>"
            )

        body = QLabel(
            "Each card below is a 2-D cross-section of the inductor solved "
            "by the FEA backend. Coordinates are in millimetres "
            "(<i>r</i>, <i>z</i> for axisymmetric solves). "
            "<b>Click any card to enlarge</b> and read the "
            "engineering interpretation alongside the figure."
            "<ul style='margin: 6px 0 0 16px; padding: 0;'>"
            + "".join(bullets)
            + "</ul>"
        )
        body.setWordWrap(True)
        body.setStyleSheet(
            f"font-size: 12px; color: {p.text_secondary}; "
            f"line-height: 1.5;"
        )
        v.addWidget(body)

        return frame

    def _on_thumb_clicked(self, path: Path, category: str) -> None:
        """Open the lightbox at full resolution, with the per-
        category engineering context in the side panel."""
        dlg = _LightboxDialog(path, category=category, parent=self)
        dlg.exec()
