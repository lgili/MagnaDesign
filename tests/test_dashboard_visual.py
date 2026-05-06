"""Visual regression for the DashboardPage.

Renders the dashboard headlessly to a PNG and compares it against
``tests/baselines/dashboard_default.png`` at ≤ 1 % per-pixel
tolerance. Update the baseline only when the layout intentionally
changes (and review the diff before committing).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "tests" / "baselines" / "dashboard_default.png"
SIZE = (1140, 820)


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance() or QApplication([])
    yield inst


def _render_dashboard():
    from pfc_inductor.ui.dashboard import DashboardPage
    from pfc_inductor.ui.theme import set_theme
    set_theme("light")
    p = DashboardPage()
    p.resize(*SIZE)
    p.show()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
        app.processEvents()
    return p.grab()


def test_baseline_exists(app):
    assert BASELINE.exists(), (
        f"Visual baseline missing at {BASELINE}. To create it for "
        "the first time, run "
        "``python -m pytest tests/test_dashboard_visual.py::test_create_baseline``."
    )


@pytest.mark.skipif(
    not BASELINE.exists(),
    reason="No baseline yet — run test_create_baseline first.",
)
def test_dashboard_matches_baseline(app):
    """Per-pixel diff against the stored baseline.

    Tolerance: at most 1 % of pixels may differ by more than ε. The
    diff metric is a coarse RGB Manhattan distance — fine for catching
    layout shifts, generous on antialiasing wobble.
    """
    from PySide6.QtGui import QImage

    rendered = _render_dashboard().toImage()
    baseline = QImage(str(BASELINE))

    if rendered.size() != baseline.size():
        pytest.fail(
            f"Size mismatch: rendered {rendered.size()} vs "
            f"baseline {baseline.size()}",
        )

    w, h = rendered.width(), rendered.height()
    n_total = 0
    n_diff = 0
    eps = 12  # per-channel difference threshold
    # Sample every 4th pixel for speed; ~16x faster, still catches
    # any layout regression that touches more than a tiny region.
    step = 4
    for y in range(0, h, step):
        for x in range(0, w, step):
            n_total += 1
            r1 = rendered.pixelColor(x, y)
            r2 = baseline.pixelColor(x, y)
            if (abs(r1.red() - r2.red()) > eps
                    or abs(r1.green() - r2.green()) > eps
                    or abs(r1.blue() - r2.blue()) > eps):
                n_diff += 1
    pct = 100.0 * n_diff / max(n_total, 1)
    assert pct <= 1.0, (
        f"Dashboard visual diverged: {pct:.2f}% of sampled pixels "
        f"changed (threshold 1.0%). Review the diff and update "
        f"{BASELINE.relative_to(REPO_ROOT)} if the change is "
        "intentional."
    )


def test_create_baseline(app):
    """Helper: regenerate the baseline. Always passes; only meaningful
    if the user ran ``REGENERATE_BASELINE=1 pytest …``."""
    if os.environ.get("REGENERATE_BASELINE") != "1":
        pytest.skip(
            "Set REGENERATE_BASELINE=1 to overwrite the baseline.",
        )
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    pix = _render_dashboard()
    pix.save(str(BASELINE))
    assert BASELINE.exists()
