"""Render gmsh ``.pos`` post-processing files as PNG heatmaps.

After a FEMMT/ONELAB simulation, gmsh writes scalar-field views
into the working directory's ``e_m/results/fields`` subfolder:

- ``Magb.pos``        — magnetic flux density magnitude |B| [T]
- ``j2F_density.pos`` — ohmic-loss density (frequency domain) [W/m³]
- ``jH_density.pos``  — H-field magnitude [A/m]
- ``raz.pos``         — magnetic vector potential A_z (used in
                        gmsh to draw flux lines)

The native FEMMT visualiser opens these in the gmsh GUI
(``gmsh.fltk.run``), which is non-starter for our worker thread
(blocking + needs DISPLAY). Instead we parse the ASCII format
directly — gmsh's ``View "name" { ... }`` block of ``ST(...){v1,v2,v3}``
scalar-triangle entries — and render each view with
``matplotlib.tripcolor``. Pure Python, fully headless, gives us
control over colormap and labelling.

The output PNGs are written next to their source ``.pos`` file
so :class:`~pfc_inductor.ui.widgets.fea_field_gallery.FEAFieldGallery`'s
recursive ``rglob("*.png")`` scan picks them up automatically.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Pretty labels per gmsh view. Keys are the view name string
# inside ``View "..."``; values are (axis label, plot title).
# Unknown views fall through to a generic "field" label.
_VIEW_LABELS: dict[str, tuple[str, str]] = {
    "Magb": ("|B| [T]", "Magnetic flux density"),
    "j2F_density": ("Loss density [W/m³]", "Ohmic loss density"),
    "j2H_density": ("Loss density [W/m³]", "Litz ohmic loss density"),
    "jH_density": ("|H| [A/m]", "H-field magnitude"),
}

# ``raz`` is A_z (vector potential); rendered as a scalar field
# the contour lines are flux lines. We render it but with a
# different colormap so users don't confuse it with B.
_VIEW_LABELS["raz"] = ("A_z [Wb/m]", "Magnetic vector potential")

# Thermal solve outputs — only present when the user explicitly
# enables FEMMT's coupled thermal pass (out of scope for the
# current runner, but the labels live here so the gallery
# auto-categorises them when a custom run drops them on disk).
_VIEW_LABELS["temperature"] = ("Temperature [°C]", "Predicted temperature")
_VIEW_LABELS["thermal_total_loss_density"] = (
    "Loss density [W/m³]", "Coupled thermal loss density",
)


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------
def render_field_pngs(working_dir: str | Path | None) -> list[Path]:
    """Find every ``.pos`` file under ``working_dir`` and render
    a heatmap PNG next to each. Returns the list of PNG paths
    created. Failures are logged but don't raise — this is a
    visualisation nice-to-have, never a critical path.
    """
    if not working_dir:
        return []
    root = Path(working_dir)
    if not root.exists() or not root.is_dir():
        return []

    out: list[Path] = []
    for pos_path in sorted(root.rglob("*.pos")):
        # Skip ONELAB's bookkeeping files (option.pos is the
        # solver state, not a field).
        if pos_path.name.lower() in ("option.pos",):
            continue
        try:
            png_path = render_pos_to_png(pos_path)
            if png_path is not None:
                out.append(png_path)
        except Exception:
            logger.exception("Failed to render %s as PNG", pos_path)

        # Sidecar plots: 1-D centerline + histogram. Only worth
        # producing for B-field views (Magb, B-field, flux density);
        # current-density / vector-potential plots have different
        # interpretation modes.
        name = pos_path.stem.lower()
        is_b_field = any(
            tok in name for tok in ("magb", "b_field", "flux_density")
        )
        if is_b_field:
            try:
                cl = render_centerline_png(pos_path)
                if cl is not None:
                    out.append(cl)
            except Exception:
                logger.exception(
                    "Failed to render %s centerline PNG", pos_path
                )
            try:
                hi = render_histogram_png(pos_path)
                if hi is not None:
                    out.append(hi)
            except Exception:
                logger.exception(
                    "Failed to render %s histogram PNG", pos_path
                )
    return out


def render_centerline_png(pos_path: Path) -> Optional[Path]:
    """1-D plot of the field along the gap centerline (``z = 0``).

    Identifies the gap centreline by sampling the scalar values
    at points whose ``z`` coordinate is closest to zero, then
    plots ``|B| vs r``. The resulting curve makes saturation
    crowding obvious in a way the 2-D heatmap doesn't — small
    bright pixels in a heatmap look the same whether they're at
    Bsat or 10 % below; the 1-D plot puts a hard number on every
    radial position.

    Returns the output PNG path, or ``None`` when the data isn't
    suitable (no scalar triangles, all points off-axis).
    """
    parsed = _parse_pos_scalar_triangles(pos_path)
    if parsed is None:
        return None
    view_name, points, triangles, values = parsed
    if not triangles:
        return None

    import numpy as np

    pts = np.asarray(points, dtype=float)
    vals = np.asarray(values, dtype=float)
    # Pick points within a small z-window. The window thickness
    # is sized as 5 % of the total z-extent so even very fine
    # meshes return enough samples for a smooth curve.
    z_min, z_max = float(pts[:, 1].min()), float(pts[:, 1].max())
    z_span = max(z_max - z_min, 1e-12)
    z_window = z_span * 0.05
    mask = np.abs(pts[:, 1]) <= z_window
    if mask.sum() < 8:
        # Not enough samples on the centerline — fall back to
        # the closest |z| slice (whichever side of zero is
        # populated).
        z_target = float(pts[np.argmin(np.abs(pts[:, 1])), 1])
        mask = np.abs(pts[:, 1] - z_target) <= z_window

    r_centerline = pts[mask, 0]
    v_centerline = vals[mask]
    if r_centerline.size < 4:
        return None

    # Sort by r so the line plot reads left-to-right.
    order = np.argsort(r_centerline)
    r_sorted = r_centerline[order]
    v_sorted = v_centerline[order]

    out_path = pos_path.with_name(f"{pos_path.stem}_centerline.png")
    _render_centerline(view_name, r_sorted, v_sorted, out_path)
    return out_path


def render_histogram_png(pos_path: Path) -> Optional[Path]:
    """Volumetric distribution of the scalar field.

    Histogram of every node value, weighted by the surrounding
    triangle area. Bright outliers in the heatmap are easy to
    over-react to — the histogram tells you what fraction of the
    volume actually sits at each level. A long tail to high |B|
    is the saturation warning; a fat body well below Bsat means
    you're using the core conservatively.
    """
    parsed = _parse_pos_scalar_triangles(pos_path)
    if parsed is None:
        return None
    view_name, points, triangles, values = parsed
    if not triangles:
        return None

    import numpy as np

    pts = np.asarray(points, dtype=float)
    tri = np.asarray(triangles, dtype=np.int64)
    vals = np.asarray(values, dtype=float)

    # Per-triangle area for weighting (so dense-mesh regions
    # don't dominate the histogram).
    p1, p2, p3 = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    area = 0.5 * np.abs(
        (p2[:, 0] - p1[:, 0]) * (p3[:, 1] - p1[:, 1])
        - (p3[:, 0] - p1[:, 0]) * (p2[:, 1] - p1[:, 1])
    )
    # Per-triangle scalar value: average of the three node
    # values. Matches what the heatmap shows visually.
    tri_vals = (vals[tri[:, 0]] + vals[tri[:, 1]] + vals[tri[:, 2]]) / 3.0

    out_path = pos_path.with_name(f"{pos_path.stem}_histogram.png")
    _render_histogram(view_name, tri_vals, area, out_path)
    return out_path


def render_pos_to_png(pos_path: Path) -> Optional[Path]:
    """Render a single ``.pos`` scalar-triangle view as a heatmap
    PNG. Returns the output path, or ``None`` if the file isn't
    a renderable scalar view (e.g. vector field, empty)."""
    parsed = _parse_pos_scalar_triangles(pos_path)
    if parsed is None:
        return None
    view_name, points, triangles, values = parsed
    if not triangles:
        return None
    out_png = pos_path.with_suffix(".png")
    _render_heatmap(view_name, points, triangles, values, out_png)
    return out_png


# ----------------------------------------------------------------
# Internals
# ----------------------------------------------------------------
# Match scalar-triangle entries:
#   ST(r1,z1,e1, r2,z2,e2, r3,z3,e3){v1,v2,v3};
# Whitespace-permissive; gmsh's writer typically uses no spaces
# but third-party tools may differ.
_RE_VIEW_NAME = re.compile(r'View\s+"([^"]+)"')
_RE_ST = re.compile(r"ST\s*\(\s*([^)]+)\)\s*\{\s*([^}]+)\}")


def _parse_pos_scalar_triangles(
    path: Path,
) -> Optional[tuple[str, list[tuple[float, float]], list[tuple[int, int, int]], list[float]]]:
    """Defensive ASCII parser for gmsh ``.pos`` scalar-triangle
    views. Returns ``(view_name, points, triangles, node_values)``
    where points is a deduplicated list of (x, y) coords, triangles
    is a list of 3-tuples of indices into points, and node_values
    matches points (averaged across shared corners). ``None`` when
    the file has no scalar-triangle data.
    """
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return None

    # View name — gmsh always writes it; fall back to filename
    # stem if absent so we always have a label.
    m_name = _RE_VIEW_NAME.search(text)
    view_name = m_name.group(1) if m_name else path.stem

    pts_idx: dict[tuple[float, float], int] = {}
    points: list[tuple[float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    node_vals: dict[int, list[float]] = {}

    for m_st in _RE_ST.finditer(text):
        try:
            coords = [float(x.strip()) for x in m_st.group(1).split(",")]
            vals = [float(x.strip()) for x in m_st.group(2).split(",")]
        except ValueError:
            continue
        # Need 9 coords (3 nodes × xyz) and 3 values.
        if len(coords) < 9 or len(vals) < 3:
            continue
        # Quantise on a 1 nm grid so floating-point round-trip in
        # the ASCII writer doesn't break node deduplication.
        # Round to 12 decimal digits ≈ pm precision in metres.
        nodes_xy = (
            (round(coords[0], 12), round(coords[1], 12)),
            (round(coords[3], 12), round(coords[4], 12)),
            (round(coords[6], 12), round(coords[7], 12)),
        )
        idx_tri: list[int] = []
        for xy, v in zip(nodes_xy, vals[:3]):
            i = pts_idx.get(xy)
            if i is None:
                i = len(points)
                pts_idx[xy] = i
                points.append(xy)
            idx_tri.append(i)
            node_vals.setdefault(i, []).append(v)
        triangles.append((idx_tri[0], idx_tri[1], idx_tri[2]))

    if not triangles:
        return None

    # Average values at shared nodes. Gouraud shading needs
    # per-node values, not per-element.
    averaged = [
        (sum(node_vals[i]) / len(node_vals[i])) if i in node_vals else 0.0
        for i in range(len(points))
    ]
    return view_name, points, triangles, averaged


def _render_heatmap(
    view_name: str,
    points: list[tuple[float, float]],
    triangles: list[tuple[int, int, int]],
    values: list[float],
    out_path: Path,
) -> None:
    """Render the scalar field as a colored Gouraud-shaded
    heatmap on the triangulated cross-section, with a colorbar.

    Coordinates are FEMMT's axisymmetric (r, z) in metres; we
    label the axes accordingly. Values are clipped to the 1st-99th
    percentile so a single saturated element doesn't crush the
    contrast for the rest of the geometry.
    """
    # Lazy-import matplotlib so importing the module has no
    # GUI/Qt dependency. ``Agg`` backend keeps the renderer
    # headless even if matplotlib was already imported with
    # something else.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: E402
    import numpy as np  # noqa: E402
    from matplotlib.tri import Triangulation  # noqa: E402

    pts_arr = np.asarray(points, dtype=float)
    tri_arr = np.asarray(triangles, dtype=np.int64)
    val_arr = np.asarray(values, dtype=float)

    # Robust colour range: percentiles instead of min/max so a
    # single hot element near a corner doesn't wash out the rest
    # of the cross-section. Magnetic-field plots are dominated
    # by the gap region; clipping here keeps the core's flux
    # legible.
    if val_arr.size > 0 and np.isfinite(val_arr).any():
        finite = val_arr[np.isfinite(val_arr)]
        vmin = float(np.percentile(finite, 1.0))
        vmax = float(np.percentile(finite, 99.0))
        if vmax <= vmin:
            vmax = vmin + max(abs(vmin) * 1e-3, 1e-12)
    else:
        vmin, vmax = 0.0, 1.0

    label, title = _VIEW_LABELS.get(view_name, (view_name, view_name))
    cmap = "viridis" if "loss" not in title.lower() else "magma"

    triang = Triangulation(pts_arr[:, 0], pts_arr[:, 1], tri_arr)

    fig, ax = plt.subplots(figsize=(7.0, 5.4), dpi=110)
    fig.patch.set_facecolor("white")
    tcf = ax.tripcolor(
        triang,
        val_arr,
        shading="gouraud",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
    )
    # Faint mesh wireframe over the heatmap so the user can see
    # the discretisation density. Alpha is low so it doesn't
    # overpower the colour data.
    ax.triplot(triang, color="black", alpha=0.08, linewidth=0.3)

    ax.set_aspect("equal")
    ax.set_xlabel("r [mm]")
    ax.set_ylabel("z [mm]")
    # FEMMT works in metres; relabel the ticks in mm for engineer
    # readability without changing the underlying data scale.
    _relabel_axis_mm(ax)
    ax.set_title(f"{title} — FEMMT FEA", fontsize=11, fontweight="bold")

    cbar = fig.colorbar(tcf, ax=ax, shrink=0.92, pad=0.02)
    cbar.set_label(label, fontsize=10)
    cbar.ax.tick_params(labelsize=9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _relabel_axis_mm(ax) -> None:
    """Convert axis tick labels from metres to millimetres in
    place. Cheap visual fix — engineers think in mm."""
    from matplotlib.ticker import FuncFormatter

    fmt = FuncFormatter(lambda v, _pos: f"{v * 1e3:g}")
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)


def _render_centerline(
    view_name: str,
    r_arr,  # np.ndarray[float] in metres
    v_arr,  # np.ndarray[float], scalar values
    out_path: Path,
) -> None:
    """Plot ``v(r)`` along the ``z = 0`` line as a clean 1-D curve.

    Visual: a single line with markers at the sampled points
    (so the underlying mesh density is visible), the value's
    peak annotated as text, and a horizontal reference line at
    Bsat when the view is a B-field plot.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: E402
    import numpy as np  # noqa: E402

    label, title = _VIEW_LABELS.get(view_name, (view_name, view_name))
    is_b_field = view_name.lower().startswith("magb") or "B" in label[:2]
    line_color = "#7C3AED" if is_b_field else "#1E40AF"

    fig, ax = plt.subplots(figsize=(7.0, 4.4), dpi=110)
    fig.patch.set_facecolor("white")

    ax.plot(
        r_arr * 1e3,  # metres → mm for the engineer
        v_arr,
        color=line_color,
        marker="o",
        markersize=3,
        markerfacecolor=line_color,
        markeredgecolor="white",
        markeredgewidth=0.4,
        linewidth=1.6,
    )
    ax.fill_between(r_arr * 1e3, 0.0, v_arr,
                    color=line_color, alpha=0.10)

    # Peak annotation.
    if v_arr.size > 0:
        i_pk = int(np.argmax(np.abs(v_arr)))
        r_pk_mm = float(r_arr[i_pk]) * 1e3
        v_pk = float(v_arr[i_pk])
        ax.scatter([r_pk_mm], [v_pk], color="#DC2626",
                   s=70, zorder=4, edgecolors="white",
                   linewidths=1.4)
        ax.annotate(
            f"peak {v_pk:.3g} {label.split()[0]}",
            xy=(r_pk_mm, v_pk),
            xytext=(8, -16), textcoords="offset points",
            fontsize=9, color="#1F2937",
            bbox=dict(boxstyle="round,pad=0.35",
                      fc="white", ec="#D1D5DB", lw=0.7),
        )

    ax.set_xlabel("Radial position r [mm]")
    ax.set_ylabel(label)
    ax.set_title(f"{title} along gap centerline (z = 0) — FEMMT FEA",
                 fontsize=11, fontweight="bold")
    ax.grid(True, alpha=0.20, linestyle=":")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _render_histogram(
    view_name: str,
    tri_vals,  # np.ndarray[float], one value per triangle
    weights,   # np.ndarray[float], triangle areas (== weights)
    out_path: Path,
) -> None:
    """Area-weighted histogram of the field over the cross-section.

    Visual: vertical bars sized by fractional area at each value
    bin, plus cumulative-distribution curve overlay so the user
    can read "X % of the volume is above Y" directly.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: E402
    import numpy as np  # noqa: E402

    label, title = _VIEW_LABELS.get(view_name, (view_name, view_name))
    is_loss = "loss" in title.lower()
    bar_color = "#F59E0B" if is_loss else "#7C3AED"

    fig, ax_h = plt.subplots(figsize=(7.0, 4.4), dpi=110)
    fig.patch.set_facecolor("white")

    # Drop non-finite values so a single NaN doesn't break
    # numpy's histogram.
    finite_mask = np.isfinite(tri_vals)
    tri_vals = np.asarray(tri_vals)[finite_mask]
    weights = np.asarray(weights)[finite_mask]
    total_area = float(weights.sum()) or 1.0

    # 40 bins in the 1-99 % percentile range — same robust-range
    # rule the heatmap uses, so the histogram and the heatmap
    # tell consistent stories.
    if tri_vals.size == 0:
        plt.close(fig)
        return
    vmin = float(np.percentile(tri_vals, 1.0))
    vmax = float(np.percentile(tri_vals, 99.0))
    if vmax <= vmin:
        vmax = vmin + 1e-9
    bins = np.linspace(vmin, vmax, 41)
    counts, edges = np.histogram(tri_vals, bins=bins, weights=weights)
    pct_per_bin = counts / total_area * 100.0

    width = (edges[1] - edges[0]) * 0.9
    centers = 0.5 * (edges[:-1] + edges[1:])
    ax_h.bar(centers, pct_per_bin, width=width,
             color=bar_color, alpha=0.85,
             edgecolor="white", linewidth=0.4)

    ax_h.set_xlabel(label)
    ax_h.set_ylabel("Fraction of cross-section [%]", color=bar_color)
    ax_h.tick_params(axis="y", labelcolor=bar_color)
    ax_h.grid(True, alpha=0.20, linestyle=":", axis="y")
    for spine in ("top",):
        ax_h.spines[spine].set_visible(False)

    # CDF overlay on a secondary right-axis.
    ax_c = ax_h.twinx()
    sorted_vals = np.sort(tri_vals)
    sorted_weights = weights[np.argsort(tri_vals)]
    cdf = np.cumsum(sorted_weights) / total_area * 100.0
    ax_c.plot(sorted_vals, cdf, color="#374151", linewidth=1.4)
    ax_c.set_ylabel("Cumulative volume [%]", color="#374151")
    ax_c.tick_params(axis="y", labelcolor="#374151")
    ax_c.set_ylim(0, 100)
    for spine in ("top",):
        ax_c.spines[spine].set_visible(False)

    ax_h.set_title(f"{title} — distribution across cross-section",
                   fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
