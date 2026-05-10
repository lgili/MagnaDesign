#!/usr/bin/env python3
"""Generate the synthetic-but-realistic placeholders the slide
deck needs in addition to the live widget renders.

Each renderer here produces one PNG/PDF that mocks a feature
where:

* The actual widget has too many runtime dependencies to render
  offscreen cleanly (Pareto front, Cascade Top-N, Compare dialog,
  Export HTML preview, Qt3D viewer); or
* We want a slide-friendly version of an existing widget
  (FormasOndaCard rendered from a real DesignResult, Spec card
  built as a static info panel).

Outputs go into ``presentation/figures/`` with the same filenames
the LaTeX includes expect, so re-running this script is the only
step needed to refresh the visuals before a build.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent.parent
SRC = ROOT / "src"
FIGS = HERE.parent.parent / "figures"
sys.path.insert(0, str(SRC))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import (  # noqa: E402
    FancyBboxPatch,
    Rectangle,
)

# Palette synced with the app's theme.py.
P_VIOLET = "#8B5CF6"
P_VIOLET_DARK = "#6D28D9"
P_AMBER = "#F59E0B"
P_SUCCESS = "#059669"
P_DANGER = "#DC2626"
P_TEXT = "#1F2937"
P_MUTED = "#6B7280"
P_BG = "#F9FAFB"
P_SURFACE = "#FFFFFF"
P_BORDER = "#E5E7EB"


# -------------------------------------------------------------------
# 1. Spec drawer — static info panel mocking the SpecDrawer chrome.
# -------------------------------------------------------------------
def render_spec_drawer(out: Path, title: str, fields: list[tuple[str, str]], topology: str) -> None:
    """Render a clean info panel that visually mimics the running
    app's SpecDrawer. Two columns of label / value rows on a card
    background, with a section header at the top and the topology
    chip as a coloured pill."""
    fig, ax = plt.subplots(figsize=(8.5, 5.6), dpi=110)
    fig.patch.set_facecolor(P_BG)
    ax.set_facecolor(P_BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()

    # Card frame.
    card = FancyBboxPatch(
        (0.04, 0.06),
        0.92,
        0.88,
        boxstyle="round,pad=0.005,rounding_size=0.012",
        linewidth=1.2,
        edgecolor=P_BORDER,
        facecolor=P_SURFACE,
    )
    ax.add_patch(card)

    # Header bar — coloured rule + section title.
    ax.add_patch(Rectangle((0.04, 0.86), 0.92, 0.005, color=P_VIOLET, linewidth=0))
    ax.text(0.07, 0.88, title, fontsize=14, fontweight="bold", color=P_TEXT, va="bottom")
    # Topology pill.
    pill_x, pill_y, pill_w, pill_h = 0.74, 0.875, 0.20, 0.045
    ax.add_patch(
        FancyBboxPatch(
            (pill_x, pill_y),
            pill_w,
            pill_h,
            boxstyle="round,pad=0.0,rounding_size=0.025",
            linewidth=0,
            facecolor=P_VIOLET_DARK,
        )
    )
    ax.text(
        pill_x + pill_w / 2,
        pill_y + pill_h / 2,
        topology,
        fontsize=9,
        fontweight="bold",
        color="white",
        ha="center",
        va="center",
    )

    # Fields — two columns. Generous vertical spacing so the
    # 11 pt value face under each 8 pt CAPTION leaves a clear
    # gutter to the next row.
    n = len(fields)
    half = (n + 1) // 2
    col1 = fields[:half]
    col2 = fields[half:]
    y_start = 0.80
    line_h = 0.115
    label_to_value = 0.045
    for i, (label, value) in enumerate(col1):
        y = y_start - i * line_h
        ax.text(0.08, y, label.upper(), fontsize=8, color=P_MUTED, fontweight="bold")
        ax.text(0.08, y - label_to_value, value, fontsize=11, color=P_TEXT, family="monospace")
    for i, (label, value) in enumerate(col2):
        y = y_start - i * line_h
        ax.text(0.55, y, label.upper(), fontsize=8, color=P_MUTED, fontweight="bold")
        ax.text(0.55, y - label_to_value, value, fontsize=11, color=P_TEXT, family="monospace")

    # Footer note — small caption.
    ax.text(
        0.5,
        0.10,
        "Press ENTER on any field to recalculate the design.",
        fontsize=8,
        color=P_MUTED,
        style="italic",
        ha="center",
    )

    fig.savefig(str(out), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


# -------------------------------------------------------------------
# 2. FEA dispatch flow — TikZ-equivalent in matplotlib.
# -------------------------------------------------------------------
def render_fea_dispatch(out: Path) -> None:
    """Show the high-N → fallback decision tree as a clean
    flowchart. Three boxes + arrows + verdict on each branch."""
    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=110)
    fig.patch.set_facecolor(P_BG)
    ax.set_facecolor(P_BG)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.set_axis_off()

    def box(x, y, w, h, text, color=P_VIOLET_DARK, fill=P_SURFACE, fontsize=10, bold=False):
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.02,rounding_size=0.1",
                linewidth=1.5,
                edgecolor=color,
                facecolor=fill,
            )
        )
        weight = "bold" if bold else "normal"
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            fontsize=fontsize,
            color=P_TEXT,
            fontweight=weight,
            ha="center",
            va="center",
        )

    def arrow(x1, y1, x2, y2, label=None, color=P_VIOLET_DARK):
        ax.annotate(
            "", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color=color, lw=1.6)
        )
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ax.text(
                mx,
                my,
                label,
                fontsize=8,
                color=P_MUTED,
                bbox=dict(facecolor=P_BG, edgecolor="none", pad=2),
                ha="center",
                va="center",
                style="italic",
            )

    box(3.5, 4.8, 3, 0.7, "validate_design(spec, ...)\nN = 250 turns", bold=True, fontsize=10)

    box(0.5, 2.8, 3, 0.9, "FEMMT path\n(N > 150 → would crash)", color=P_DANGER, fill="#FEF2F2")
    box(6.5, 2.8, 3, 0.9, "FEMM legacy\nbulk current region", color=P_SUCCESS, fill="#F0FDF4")

    arrow(4.5, 4.8, 2.0, 3.7, "shape = toroid?")
    arrow(5.5, 4.8, 8.0, 3.7, "auto-fallback")

    box(
        6.5,
        0.6,
        3,
        1.1,
        "Result returned\nNo error to user",
        bold=True,
        color=P_VIOLET_DARK,
        fill="#F5F3FF",
    )
    arrow(8.0, 2.8, 8.0, 1.7)

    ax.text(
        2.0,
        2.0,
        "Would skip with\n‘FEA skipped: N exceeds…’",
        fontsize=9,
        color=P_DANGER,
        ha="center",
        va="top",
        style="italic",
    )

    ax.text(
        5,
        0.1,
        "FEMM legacy models the winding as a homogeneous current "
        "region — N has zero geometric cost.",
        fontsize=9,
        color=P_MUTED,
        ha="center",
        style="italic",
    )

    fig.tight_layout()
    fig.savefig(str(out), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


# -------------------------------------------------------------------
# 3. Pareto front — synthetic optimiser output.
# -------------------------------------------------------------------
def render_pareto(out: Path) -> None:
    """1000+ candidate scatter, dominated points faded, the
    Pareto front highlighted in violet with the user's pick.

    The Pareto-meaningful data has *negative* correlation
    between loss and cost (cheaper / smaller cores ⇒ higher
    losses; bigger / better cores ⇒ lower losses, more $$$).
    A simple positive correlation would collapse the front to
    a single point.
    """
    rng = np.random.default_rng(seed=42)
    n = 1200
    losses = rng.uniform(1.8, 11.0, n)
    # Negative-correlation curve: cost decreases with loss-tolerance.
    cost = 22.0 - losses * 1.5 + rng.normal(0, 1.2, n)
    cost = np.clip(cost, 4, 25)
    losses = np.clip(losses, 1.5, 12)

    # Pareto front — sort by loss, keep monotonically decreasing
    # cost.
    order = np.argsort(losses)
    front_idx = []
    best_cost = float("inf")
    for i in order:
        if cost[i] < best_cost:
            front_idx.append(i)
            best_cost = cost[i]

    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=110)
    fig.patch.set_facecolor(P_BG)
    ax.set_facecolor(P_SURFACE)
    ax.scatter(
        losses,
        cost,
        s=14,
        alpha=0.18,
        color=P_MUTED,
        edgecolors="none",
        label=f"Dominated  (n = {n - len(front_idx)})",
    )
    ax.scatter(
        losses[front_idx],
        cost[front_idx],
        s=42,
        color=P_VIOLET,
        edgecolors="white",
        linewidths=0.7,
        zorder=4,
        label=f"Pareto front  (n = {len(front_idx)})",
    )
    # Connect the front.
    o = np.argsort(losses[front_idx])
    ax.plot(
        np.array(losses)[front_idx][o],
        np.array(cost)[front_idx][o],
        color=P_VIOLET,
        linewidth=1.4,
        alpha=0.7,
        zorder=3,
    )

    # Highlight one — the user's chosen design.
    pick_i = front_idx[len(front_idx) // 2]
    ax.scatter(
        [losses[pick_i]],
        [cost[pick_i]],
        s=180,
        facecolor=P_AMBER,
        edgecolors=P_VIOLET_DARK,
        linewidths=2,
        zorder=5,
        marker="*",
        label="Selected candidate",
    )

    ax.set_xlabel("Total loss [W]", color=P_TEXT, fontsize=11)
    ax.set_ylabel("Bill-of-materials cost [USD]", color=P_TEXT, fontsize=11)
    ax.tick_params(axis="both", labelcolor=P_TEXT)
    ax.grid(True, alpha=0.20, linestyle=":")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(P_BORDER)
    ax.set_title(
        "Pareto optimiser — losses vs cost  ·  1200 candidates",
        fontsize=12,
        fontweight="bold",
        color=P_TEXT,
        loc="left",
        pad=10,
    )
    ax.legend(
        loc="upper left",
        fontsize=9,
        frameon=True,
        facecolor=P_SURFACE,
        edgecolor=P_BORDER,
        labelcolor=P_TEXT,
    )

    fig.tight_layout()
    fig.savefig(str(out), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


# -------------------------------------------------------------------
# 4. Cascade Top-N table.
# -------------------------------------------------------------------
def render_cascade_table(out: Path) -> None:
    """Top-N table mock with refined values per tier."""
    rows = [
        # core         AL    N    L_uH(T1) loss(T1) loss(T2) loss(T3) ΔT(T2)
        ("0077439A7", 135, 55, 406, 3.18, 3.05, 3.02, 18),
        ("0077928A7", 170, 50, 402, 3.42, 3.30, 3.27, 20),
        ("0077439A7", 135, 60, 445, 3.65, 3.55, 3.52, 19),
        ("0077070A7", 68, 80, 392, 4.10, 4.02, "—", 22),
        ("0078439A7", 178, 50, 398, 3.50, 3.40, "—", 21),
    ]
    headers = [
        "Core",
        "AL [nH]",
        "N",
        "L [µH]",
        "Loss T1 [W]",
        "Loss T2 [W]",
        "Loss T3 [W]",
        "ΔT [°C]",
    ]

    fig, ax = plt.subplots(figsize=(11, 5.4), dpi=110)
    fig.patch.set_facecolor(P_BG)
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Manual table — matplotlib table is ugly, hand-roll it.
    # ``cell_h`` is shrunk a bit so all rows + header + title +
    # footer fit without the footer overlapping the last row.
    n_rows = len(rows) + 1  # + header
    cell_h = 0.70 / n_rows
    col_widths = [0.18, 0.10, 0.07, 0.10, 0.13, 0.13, 0.13, 0.11]
    cum = np.cumsum([0, *col_widths])
    # Re-scale to fit width 0.95.
    cum = cum / cum[-1] * 0.95 + 0.025

    # Title — pinned higher so the body has room.
    ax.text(
        0.025,
        0.95,
        "Cascade optimiser — Top-5 candidates",
        fontsize=14,
        fontweight="bold",
        color=P_TEXT,
        transform=ax.transAxes,
    )
    ax.text(
        0.025,
        0.91,
        "Loss T3 column shows the FEA-refined value where "
        "available; an em-dash means the candidate hasn't "
        "reached Tier 3 yet.",
        fontsize=8.5,
        color=P_MUTED,
        style="italic",
        transform=ax.transAxes,
    )

    # Header row.
    y_top = 0.85
    ax.add_patch(
        Rectangle(
            (0.025, y_top - cell_h),
            0.95,
            cell_h,
            transform=ax.transAxes,
            facecolor=P_VIOLET_DARK,
            edgecolor="white",
            linewidth=0.5,
        )
    )
    for j, h in enumerate(headers):
        ax.text(
            cum[j] + col_widths[j] * 0.95 / 2 / sum(col_widths) * 0.95,
            y_top - cell_h / 2,
            h,
            fontsize=9,
            fontweight="bold",
            color="white",
            ha="left" if j == 0 else "center",
            va="center",
            transform=ax.transAxes,
        )

    # Body rows.
    for i, row in enumerate(rows):
        y = y_top - cell_h * (i + 2)
        bg = "#FAFAFB" if i % 2 == 0 else P_SURFACE
        if i == 0:  # highlight leader
            bg = "#F5F3FF"
        ax.add_patch(
            Rectangle(
                (0.025, y),
                0.95,
                cell_h,
                transform=ax.transAxes,
                facecolor=bg,
                edgecolor=P_BORDER,
                linewidth=0.5,
            )
        )
        for j, cell in enumerate(row):
            txt = str(cell)
            color = P_TEXT
            weight = "normal"
            if i == 0 and j == 0:
                weight = "bold"
                color = P_VIOLET_DARK
            ax.text(
                cum[j] + 0.005,
                y + cell_h / 2,
                txt,
                fontsize=9.5,
                color=color,
                fontweight=weight,
                family="monospace" if j > 0 else "sans-serif",
                ha="left",
                va="center",
                transform=ax.transAxes,
            )

    # Footnote — drop the gold-medal emoji (DejaVu doesn't ship
    # emoji glyphs and matplotlib falls back to a missing-glyph
    # box). Use a plain bullet instead.
    ax.text(
        0.025,
        0.04,
        "★ Leader — refined T3 loss 3.02 W, ΔT 18 °C  ·  click any row to drill into its design.",
        fontsize=9,
        color=P_VIOLET_DARK,
        transform=ax.transAxes,
    )

    fig.savefig(str(out), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


# -------------------------------------------------------------------
# 5. Compare designs side-by-side.
# -------------------------------------------------------------------
def render_compare(out: Path) -> None:
    """Three-column comparison panel with diff-style highlighting."""
    designs = [
        ("Baseline", "0077439A7", 55, 406, 3.15, 18, 12.40),
        ("Variant A", "0077439A7", 60, 445, 2.95, 19, 12.40),
        ("Variant B", "0077928A7", 50, 402, 3.27, 20, 14.20),
    ]
    metrics = [
        ("Core", lambda d: d[1]),
        ("Turns", lambda d: f"{d[2]}"),
        ("L [µH]", lambda d: f"{d[3]}"),
        ("Total loss [W]", lambda d: f"{d[4]:.2f}"),
        ("ΔT [°C]", lambda d: f"{d[5]}"),
        ("Cost [USD]", lambda d: f"${d[6]:.2f}"),
    ]

    fig, ax = plt.subplots(figsize=(10, 5.0), dpi=110)
    fig.patch.set_facecolor(P_BG)
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.text(0.02, 0.95, "Compare designs", fontsize=14, fontweight="bold", color=P_TEXT)
    ax.text(
        0.02,
        0.90,
        "Variant A trades two more turns for ~6 % less loss "
        "at the same cost as Baseline. Variant B costs 15 % "
        "more without a clear win.",
        fontsize=9,
        color=P_MUTED,
        style="italic",
    )

    # Header row with design names.
    col_x = [0.30, 0.51, 0.72]
    col_w = 0.18
    y_header = 0.80
    ax.add_patch(Rectangle((0.02, y_header - 0.06), 0.96, 0.06, facecolor=P_VIOLET_DARK))
    ax.text(
        0.04, y_header - 0.03, "Metric", fontsize=10, fontweight="bold", color="white", va="center"
    )
    for i, (name, *_) in enumerate(designs):
        bg = "#F5F3FF" if i == 1 else P_VIOLET_DARK
        fg = P_VIOLET_DARK if i == 1 else "white"
        if i == 1:
            ax.add_patch(Rectangle((col_x[i], y_header - 0.06), col_w, 0.06, facecolor=bg))
        ax.text(
            col_x[i] + col_w / 2,
            y_header - 0.03,
            name,
            fontsize=10,
            fontweight="bold",
            color=fg,
            ha="center",
            va="center",
        )

    # Rows.
    row_h = 0.08
    for ri, (label, fn) in enumerate(metrics):
        y = y_header - 0.06 - row_h * (ri + 1)
        bg = "#FAFAFB" if ri % 2 == 0 else P_SURFACE
        ax.add_patch(
            Rectangle((0.02, y), 0.96, row_h, facecolor=bg, edgecolor=P_BORDER, linewidth=0.5)
        )
        ax.text(0.04, y + row_h / 2, label, fontsize=10, color=P_TEXT, va="center")
        # Metric values per column.
        baseline_val = fn(designs[0])
        for i, d in enumerate(designs):
            val = fn(d)
            color = P_TEXT
            weight = "normal"
            if i > 0 and val != baseline_val:
                # Best across the row in violet.
                color = P_VIOLET_DARK
                weight = "bold"
            ax.text(
                col_x[i] + col_w / 2,
                y + row_h / 2,
                val,
                fontsize=10,
                color=color,
                fontweight=weight,
                family="monospace",
                ha="center",
                va="center",
            )

    fig.savefig(str(out), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


# -------------------------------------------------------------------
# 6. Export — datasheet HTML mockup.
# -------------------------------------------------------------------
def render_export_mockup(out: Path) -> None:
    """Mock the rendered HTML datasheet — title, three orthographic
    views, spec table, performance bullet list."""
    fig = plt.figure(figsize=(9, 5.4), dpi=110)
    fig.patch.set_facecolor(P_BG)

    # Outer frame — paper.
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.0,rounding_size=0.005",
            linewidth=1,
            edgecolor=P_BORDER,
            facecolor="white",
        )
    )

    # Header.
    ax.add_patch(Rectangle((0, 0.92), 1, 0.08, facecolor=P_VIOLET_DARK))
    ax.text(
        0.02, 0.96, "INDUCTOR DATASHEET", fontsize=12, fontweight="bold", color="white", va="center"
    )
    ax.text(
        0.02,
        0.945,
        "Boost PFC 1.5 kW · Magnetics 0077439A7 · Rev. A",
        fontsize=8,
        color="white",
        va="center",
        style="italic",
    )
    ax.text(
        0.98,
        0.96,
        "MagnaDesign",
        fontsize=10,
        color="white",
        ha="right",
        va="center",
        fontweight="bold",
    )

    # Three orthographic views (placeholder boxes).
    view_y = 0.62
    view_h = 0.26
    view_w = 0.28
    for i, label in enumerate(("Front", "Top", "Side")):
        x = 0.04 + i * (view_w + 0.02)
        ax.add_patch(Rectangle((x, view_y), view_w, view_h, facecolor=P_BG, edgecolor=P_BORDER))
        # Toroid silhouette inside.
        cx, cy = x + view_w / 2, view_y + view_h / 2
        if i == 1:  # top view — annulus
            ax.add_patch(plt.Circle((cx, cy), 0.075, facecolor=P_MUTED, alpha=0.6))
            ax.add_patch(plt.Circle((cx, cy), 0.04, facecolor="white"))
        else:
            ax.add_patch(
                Rectangle((cx - 0.075, cy - 0.04), 0.15, 0.08, facecolor=P_MUTED, alpha=0.6)
            )
        ax.text(x + view_w / 2, view_y - 0.02, label, fontsize=9, color=P_TEXT, ha="center")

    # Spec table — bottom half.
    rows = [
        ("Inductance", "406 µH @ 0 A bias"),
        ("Saturation current", "16.6 A (at 30% L rolloff)"),
        ("DC resistance", "58 mΩ at 25 °C"),
        ("Operating freq.", "100 kHz"),
        ("Weight", "85 g"),
        ("Operating temp.", "-40 °C to +110 °C"),
    ]
    table_h = 0.42
    ax.add_patch(Rectangle((0.04, 0.04), 0.92, table_h, facecolor=P_BG, edgecolor=P_BORDER))
    ax.text(
        0.06, 0.45, "ELECTRICAL SPECIFICATIONS", fontsize=10, fontweight="bold", color=P_VIOLET_DARK
    )
    for i, (k, v) in enumerate(rows):
        y = 0.41 - i * 0.058
        ax.text(0.06, y, k, fontsize=9, color=P_TEXT)
        ax.text(0.50, y, v, fontsize=9, color=P_TEXT, family="monospace")
        if i < len(rows) - 1:
            ax.plot([0.06, 0.94], [y - 0.025, y - 0.025], color=P_BORDER, linewidth=0.5)

    fig.savefig(str(out), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


# -------------------------------------------------------------------
# 7. 3D viewer — matplotlib isometric of a toroid.
# -------------------------------------------------------------------
def render_3d_viewer(out: Path) -> None:
    """Matplotlib 3D isometric of a toroid with winding turns —
    visually mocks the Qt3D viewer."""
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

    fig = plt.figure(figsize=(8.5, 5.4), dpi=110)
    fig.patch.set_facecolor(P_BG)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor(P_SURFACE)

    # Toroid surface.
    R, r = 1.0, 0.30  # major / minor radius
    u, v = np.mgrid[0 : 2 * np.pi : 80j, 0 : 2 * np.pi : 30j]
    x = (R + r * np.cos(v)) * np.cos(u)
    y = (R + r * np.cos(v)) * np.sin(u)
    z = r * np.sin(v)
    ax.plot_surface(x, y, z, color=P_MUTED, alpha=0.55, edgecolor="none", shade=True)

    # Winding turns — small tori following the bobbin radius.
    n_turns = 30
    for k in range(n_turns):
        theta_c = 2 * np.pi * k / n_turns
        cx = R * np.cos(theta_c)
        cy = R * np.sin(theta_c)
        # A simple ring around the toroid cross-section at this angle.
        s = np.linspace(0, 2 * np.pi, 30)
        rx = cx + r * 1.18 * np.cos(s) * np.cos(theta_c)
        ry = cy + r * 1.18 * np.cos(s) * np.sin(theta_c)
        rz = r * 1.18 * np.sin(s)
        ax.plot(rx, ry, rz, color=P_AMBER, linewidth=1.6, alpha=0.85)

    ax.view_init(elev=22, azim=35)
    ax.set_box_aspect((1.4, 1.4, 0.5))
    ax.set_axis_off()
    ax.set_title(
        "3D viewer — Magnetics 0077439A7 toroid + winding (30 of 55 turns shown)",
        fontsize=11,
        fontweight="bold",
        color=P_TEXT,
        pad=20,
    )
    fig.savefig(str(out), bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=110)
    plt.close(fig)


# -------------------------------------------------------------------
# 8. Logo — vector mark.
# -------------------------------------------------------------------
def render_logo(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(2.4, 0.9), dpi=200)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    ax.set_axis_off()
    ax.set_xlim(0, 4)
    ax.set_ylim(0, 1)
    # M-shaped icon
    ax.plot(
        [0.15, 0.15, 0.45, 0.75, 0.75],
        [0.15, 0.85, 0.5, 0.85, 0.15],
        color=P_VIOLET_DARK,
        linewidth=3.5,
        solid_capstyle="round",
    )
    ax.text(1.0, 0.5, "MagnaDesign", fontsize=18, fontweight="bold", color=P_TEXT, va="center")
    fig.savefig(str(out), bbox_inches="tight", facecolor="none", transparent=True)
    plt.close(fig)


# -------------------------------------------------------------------
# 9. FormasOndaCard — render via the actual widget.
# -------------------------------------------------------------------
def render_formas_onda_card(d, out: Path) -> None:
    """Render the FormasOndaCard with the design's data via the
    real widget; saves as a slide-friendly PNG."""
    from PySide6.QtWidgets import QApplication

    from pfc_inductor.ui.dashboard.cards.formas_onda_card import (
        FormasOndaCard,
    )

    _app = QApplication.instance() or QApplication(sys.argv)
    card = FormasOndaCard()
    card.update_from_design(d.result, d.spec, d.core, d.wire, d.material)
    card.resize(1100, 480)
    card.show()
    QApplication.processEvents()
    pix = card.grab()
    pix.save(str(out))
    card.hide()


# -------------------------------------------------------------------
# Driver — re-uses RefDesigns from the main harness.
# -------------------------------------------------------------------
def main() -> None:
    FIGS.mkdir(parents=True, exist_ok=True)

    # Pull RefDesigns from the sibling harness.
    sys.path.insert(0, str(HERE.parent))
    from build_screenshots import (
        design_boost_1500w,
        design_flyback_65w,
        design_line_reactor_600w,
    )

    boost = design_boost_1500w()
    _reactor = design_line_reactor_600w()
    flyback = design_flyback_65w()

    # ── Spec drawers ──
    render_spec_drawer(
        FIGS / "example1_spec.png",
        "Boost PFC 1.5 kW",
        [
            ("V_in (rms)", "85–265 V (universal)"),
            ("V_out", "400 V (PFC bus)"),
            ("P_out", "1500 W"),
            ("f_sw", "100 kHz"),
            ("Ripple target", "30 % of I_pk"),
            ("η target", "≥ 95 %"),
            ("T_amb max", "55 °C"),
            ("Topology", "boost_ccm"),
        ],
        topology="BOOST CCM",
    )
    render_spec_drawer(
        FIGS / "example2_spec.png",
        "3-phase line reactor 22 kW",
        [
            ("V_LL (rms)", "400 V"),
            ("Frequency", "60 Hz"),
            ("P_out", "22 000 W"),
            ("I_rms (per phase)", "32 A"),
            ("Z target (impedance)", "3 %"),
            ("η target", "≥ 97 %"),
            ("Phases", "3"),
            ("Topology", "line_reactor"),
        ],
        topology="LINE REACTOR 3φ",
    )
    render_spec_drawer(
        FIGS / "example3_spec.png",
        "Flyback DCM 65 W",
        [
            ("V_in (rms)", "85–265 V"),
            ("V_out", "19 V"),
            ("I_out", "3.4 A → 65 W"),
            ("f_sw", "65 kHz"),
            ("Mode", "DCM"),
            ("Turns ratio n", "3.5 (Np / Ns)"),
            ("η target", "≥ 90 %"),
            ("Topology", "flyback"),
        ],
        topology="FLYBACK DCM",
    )

    # ── FormasOndaCard renders (real widget) ──
    print("[formas onda] rendering via real widget…")
    render_formas_onda_card(boost, FIGS / "example1_formas_onda.png")
    render_formas_onda_card(flyback, FIGS / "example3_formas_onda.png")

    # ── FEA dispatch flowchart ──
    render_fea_dispatch(FIGS / "example2_fea_dispatch.png")

    # ── FEA summary placeholder for flyback (use chart widget) ──
    from PySide6.QtCore import QTimer  # noqa: F401
    from PySide6.QtWidgets import QApplication

    from pfc_inductor.ui.widgets.fea_validation_chart import (
        FEAValidationChart,
    )

    _app = QApplication.instance() or QApplication(sys.argv)
    chart = FEAValidationChart()
    # Synthesise a flyback-specific FEA validation result.
    from pfc_inductor.fea.models import FEAValidation

    v = FEAValidation(
        L_FEA_uH=355.0,
        L_analytic_uH=358.0,
        L_pct_error=-0.8,
        B_pk_FEA_T=0.286,
        B_pk_analytic_T=0.280,
        B_pct_error=2.1,
        flux_linkage_FEA_Wb=1.50e-3,
        test_current_A=4.2,
        solve_time_s=8.4,
        femm_binary="FEMMT (ONELAB) 0.5.5",
        fem_path="/tmp/fea_flyback",
        log_excerpt="Demo",
        notes="Coupled-pair FEA — validates Lp",
    )
    chart.show_validation(v)
    chart.resize(900, 360)
    chart.show()
    QApplication.processEvents()
    chart.grab().save(str(FIGS / "example3_fea_summary.png"))
    chart.hide()

    # ── Synthetic feature placeholders ──
    print("[features] rendering analytic plots…")
    render_pareto(FIGS / "feature_otimizador_pareto.png")
    render_cascade_table(FIGS / "feature_cascade.png")
    render_compare(FIGS / "feature_compare.png")
    render_export_mockup(FIGS / "feature_export.png")
    render_3d_viewer(FIGS / "feature_3d.png")
    render_logo(FIGS / "logo-placeholder.pdf")

    print(f"\nDone. Wrote placeholders to {FIGS}.")


if __name__ == "__main__":
    main()
