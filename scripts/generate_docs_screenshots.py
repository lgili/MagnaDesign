#!/usr/bin/env python3
"""Generate the user-guide screenshots from a headless app run.

Boots the desktop app under ``QT_QPA_PLATFORM=offscreen`` with two
sample designs pre-loaded (``examples/600W_boost_reference.pfc``
for boost-PFC; ``examples/line_reactor_600W.pfc`` for the line
reactor) and grabs each workspace tab + dialog as a PNG, written
to ``docs/_static/screenshots/``.

The output filenames match the screenshot references in the
``docs/user-guide/*.md`` chapters so re-running this script keeps
the documentation in sync after a UI change.

Usage::

    python scripts/generate_docs_screenshots.py
    python scripts/generate_docs_screenshots.py --only 04 07   # subset
    python scripts/generate_docs_screenshots.py --resolution 1600x1000

Headless caveats:

- The 3D core viewer (PyVista) requires VTK with offscreen
  rendering (``vtkOffScreenRenderingFactoryClass``). Most
  matplotlib + Qt installs have it; if a screenshot of the 3D
  viewer comes back blank, install ``vtk`` with the offscreen
  variant: ``uv pip install --reinstall vtk``.

- Qt's offscreen platform doesn't render fonts identically to a
  real X / Aqua display — text rendering may have tiny
  sub-pixel differences. The screenshots are good enough for
  documentation purposes.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Force the offscreen platform BEFORE any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_FONT_DPI", "96")

# matplotlib must use Agg too so its embedded charts render
# without trying to find an X display.
os.environ.setdefault("MPLBACKEND", "Agg")

# ---------------------------------------------------------------------------
# Repo paths.
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
OUT_DIR = REPO / "docs" / "_static" / "screenshots"
DEFAULT_W, DEFAULT_H = 1400, 900


def _grab(widget, path: Path, w: int = DEFAULT_W, h: int = DEFAULT_H) -> None:
    """Resize ``widget`` to (w, h), let Qt re-layout, then dump the
    rendered pixmap to ``path``. ``QWidget.grab`` works under offscreen
    Qt and renders text + matplotlib canvases correctly.
    """
    from PySide6.QtCore import QCoreApplication, QSize

    widget.resize(QSize(w, h))
    # Process pending paint events so the resize takes effect.
    for _ in range(8):
        QCoreApplication.processEvents()
        time.sleep(0.05)
    pixmap = widget.grab()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(path), "PNG"):
        print(f"  ! failed to save {path}", file=sys.stderr)
        return
    print(f"  ✓ {path.relative_to(REPO)}")


def _load_project(window, pfc_path: Path) -> None:
    """Load a ``.pfc`` file via the MainWindow's open hook and
    let Qt finish the recalculate."""
    from PySide6.QtCore import QCoreApplication

    window._open_project_path(str(pfc_path))  # type: ignore[attr-defined]
    for _ in range(20):
        QCoreApplication.processEvents()
        time.sleep(0.1)


# ---------------------------------------------------------------------------
# Per-screenshot capture functions. Each grabs one specific surface;
# the orchestrator picks them by their ``id`` prefix.
# ---------------------------------------------------------------------------
def shot_01_workspace(window, args) -> None:
    """01-workspace-overview.png — full Project page, default layout."""
    _grab(window, OUT_DIR / "01-workspace-overview.png", *args.size)


def shot_02_spec_drawer(window, args) -> None:
    """02-spec-drawer.png — emphasise the left drawer."""
    drawer = window.projeto_page.drawer
    drawer.setMinimumWidth(420)
    _grab(drawer, OUT_DIR / "02-spec-drawer.png", 440, args.size[1])


def shot_03_core_tab(window, args) -> None:
    """03-core-tab.png — Core selection tab."""
    page = window.projeto_page
    page.tabs.setCurrentIndex(0)  # Core tab
    _grab(window, OUT_DIR / "03-core-tab.png", *args.size)


def shot_04_analysis_tab(window, args) -> None:
    """04-analysis-tab.png — full Analysis tab."""
    page = window.projeto_page
    page.tabs.setCurrentIndex(1)  # Analysis tab
    _grab(window, OUT_DIR / "04-analysis-tab.png", *args.size)


def shot_04_bh_card(window, args) -> None:
    """04-bh-card.png — close-up of the BH-loop card alone."""
    page = window.projeto_page
    page.tabs.setCurrentIndex(1)
    _grab(page.analise_tab.card_bh, OUT_DIR / "04-bh-card.png", 800, 360)


def shot_04_l_vs_i(window, args) -> None:
    """04-l-vs-i-card.png — saturation rolloff card."""
    page = window.projeto_page
    page.tabs.setCurrentIndex(1)
    _grab(page.analise_tab.card_l_current, OUT_DIR / "04-l-vs-i-card.png", 1200, 380)


def shot_04_p_vs_l(window, args) -> None:
    """04-p-vs-l-card.png — power vs inductance throughput card."""
    page = window.projeto_page
    page.tabs.setCurrentIndex(1)
    _grab(page.analise_tab.card_p_vs_l, OUT_DIR / "04-p-vs-l-card.png", 1200, 380)


def shot_04_pf_vs_l(window, args) -> None:
    """04-pf-vs-l-card.png — design-space PF card."""
    page = window.projeto_page
    page.tabs.setCurrentIndex(1)
    _grab(page.analise_tab.card_pf_vs_l, OUT_DIR / "04-pf-vs-l-card.png", 1200, 380)


def shot_05_optimizer(window, args) -> None:
    """05-optimizer-page.png — optimizer page in idle state."""
    # Switch to the Optimizer sidebar page. ``MainWindow`` exposes
    # the page list as ``stack`` (a QStackedWidget) populated in
    # ``AREA_PAGES`` order; "optimizer" is the second entry.
    window.stack.setCurrentIndex(1)
    _grab(window, OUT_DIR / "05-optimizer-page.png", *args.size)


def shot_06_compare_empty(window, args) -> None:
    """06-compare-empty.png — empty-state comparator."""
    from pfc_inductor.ui.compare_dialog import CompareDialog

    dlg = CompareDialog(parent=window)
    dlg.show()
    _grab(dlg, OUT_DIR / "06-compare-empty.png", 1200, 600)
    dlg.close()


def shot_07_fea_dialog(window, args) -> None:
    """07-fea-dialog.png — FEA dialog with the active design loaded."""
    from pfc_inductor.ui.fea_dialog import FEAValidationDialog

    spec, core, wire, mat = window._collect_inputs()  # type: ignore[attr-defined]
    from pfc_inductor.design import design as _design

    result = _design(spec, core, wire, mat)
    dlg = FEAValidationDialog(spec, core, wire, mat, result, parent=window)
    dlg.show()
    _grab(dlg, OUT_DIR / "07-fea-dialog.png", 1100, 720)
    dlg.close()


def shot_08_export_tab(window, args) -> None:
    """08-export-tab.png — Export workspace tab."""
    page = window.projeto_page
    # Export is the last tab regardless of how many compliance / etc. tabs ship.
    page.tabs.setCurrentIndex(page.tabs.count() - 1)
    _grab(window, OUT_DIR / "08-export-tab.png", *args.size)


SHOTS = [
    ("01", shot_01_workspace),
    ("02", shot_02_spec_drawer),
    ("03", shot_03_core_tab),
    ("04a", shot_04_analysis_tab),
    ("04b", shot_04_bh_card),
    ("04c", shot_04_l_vs_i),
    ("04d", shot_04_p_vs_l),
    ("04e", shot_04_pf_vs_l),
    ("05", shot_05_optimizer),
    ("06", shot_06_compare_empty),
    ("07", shot_07_fea_dialog),
    ("08", shot_08_export_tab),
]


# ---------------------------------------------------------------------------
def parse_size(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError(f"resolution must be WIDTHxHEIGHT (got {value!r})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="Subset of screenshot ids (e.g. 04a 04b 07).",
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        default=(DEFAULT_W, DEFAULT_H),
        help=f"Default window size, WxH (default {DEFAULT_W}x{DEFAULT_H}).",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=EXAMPLES / "600W_boost_reference.pfc",
        help="Project file to load (default: 600W_boost_reference.pfc).",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Boot the app.
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MagnaDesign-DocsCapture")

    from pfc_inductor.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    if args.project.exists():
        _load_project(window, args.project)
    else:
        print(f"!! sample project not found: {args.project}", file=sys.stderr)

    # Run the requested shots.
    selected = args.only or [s[0] for s in SHOTS]
    for shot_id, fn in SHOTS:
        if shot_id not in selected and shot_id.split("a")[0] not in selected:
            continue
        try:
            fn(window, args)
        except Exception as e:
            print(f"  ! {shot_id} failed: {type(e).__name__}: {e}", file=sys.stderr)

    print(f"\nScreenshots saved to {OUT_DIR.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
