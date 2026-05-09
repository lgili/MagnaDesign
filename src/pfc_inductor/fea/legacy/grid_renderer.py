"""Render the FEMM-legacy ``b_field_grid.csv`` as PNG heatmaps.

The legacy backend's LUA script samples ``|B|`` on a 50 × 50 grid
inside the toroid cross-section and writes the result to
``b_field_grid.csv``. This module post-processes that CSV into:

  * ``Magb.png``                  — 2-D heatmap of |B| over r-z
  * ``Magb_centerline.png``       — 1-D |B| vs r at z = 0
  * ``Magb_histogram.png``        — area-weighted distribution

so the FEA validation gallery in the GUI shows the same
diagnostics it shows for the FEMMT backend (where the renders
come from gmsh ``.pos`` files via :mod:`pos_renderer`). For the
legacy path we don't have triangulated mesh data, only a
regular grid — but the visualisation is equivalent.

Output filenames match the FEMMT renderer so the
:class:`FEAFieldGallery`'s category rules pick them up
automatically.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def render_legacy_field_pngs(working_dir: str | Path | None) -> list[Path]:
    """Find ``b_field_grid.csv`` under ``working_dir`` and emit
    the three companion PNGs next to it. Returns the list of
    PNG paths created. Failures are logged, never raised."""
    if not working_dir:
        return []
    root = Path(working_dir)
    if not root.exists() or not root.is_dir():
        return []
    csv_path = root / "b_field_grid.csv"
    if not csv_path.exists():
        # Hunt one level deeper in case the legacy runner used a
        # nested layout.
        candidates = list(root.rglob("b_field_grid.csv"))
        if not candidates:
            return []
        csv_path = candidates[0]

    out: list[Path] = []
    try:
        heatmap = csv_path.with_name("Magb.png")
        _render_heatmap(csv_path, heatmap)
        out.append(heatmap)
    except Exception:
        logger.exception("legacy heatmap render failed")
    try:
        centerline = csv_path.with_name("Magb_centerline.png")
        _render_centerline(csv_path, centerline)
        out.append(centerline)
    except Exception:
        logger.exception("legacy centerline render failed")
    try:
        histogram = csv_path.with_name("Magb_histogram.png")
        _render_histogram(csv_path, histogram)
        out.append(histogram)
    except Exception:
        logger.exception("legacy histogram render failed")
    return out


# ----------------------------------------------------------------
# Internals
# ----------------------------------------------------------------
def _load_grid(csv_path: Path):
    """Load the (r, z, Br, Bz, Bmag) grid into numpy arrays."""
    import numpy as np

    raw = np.genfromtxt(csv_path, delimiter=",", skip_header=1)
    if raw.size == 0 or raw.ndim != 2 or raw.shape[1] < 5:
        raise ValueError(
            f"Unexpected CSV shape from {csv_path}: {raw.shape}"
        )
    r = raw[:, 0]
    z = raw[:, 1]
    Bmag = raw[:, 4]
    # Reshape into the regular grid the LUA writer used.
    n_unique_r = len(np.unique(r))
    n_unique_z = len(np.unique(z))
    if n_unique_r * n_unique_z != raw.shape[0]:
        # Non-rectangular sampling — bail to the scattered path.
        return r, z, Bmag, None, None
    R = r.reshape(n_unique_r, n_unique_z)
    Z = z.reshape(n_unique_r, n_unique_z)
    B = Bmag.reshape(n_unique_r, n_unique_z)
    return r, z, Bmag, (R, Z, B), (n_unique_r, n_unique_z)


def _render_heatmap(csv_path: Path, out: Path) -> None:
    """``r vs z`` heatmap of |B| using ``pcolormesh``."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    r, z, Bmag, grid, _ = _load_grid(csv_path)
    fig, ax = plt.subplots(figsize=(7.0, 5.4), dpi=110)
    fig.patch.set_facecolor("white")

    # Robust colour range — same percentile clip the FEMMT
    # renderer uses so the legacy and FEMMT heatmaps read with
    # the same scale convention.
    finite = Bmag[np.isfinite(Bmag)]
    vmin = float(np.percentile(finite, 1.0)) if finite.size else 0.0
    vmax = float(np.percentile(finite, 99.0)) if finite.size else 1.0
    if vmax <= vmin:
        vmax = vmin + 1e-9

    if grid is not None:
        R, Z, B = grid
        # ``pcolormesh`` wants 2-D arrays; convert metres → mm
        # for the engineer.
        pcm = ax.pcolormesh(
            R * 1e3, Z * 1e3, B,
            cmap="viridis", vmin=vmin, vmax=vmax, shading="auto",
        )
    else:
        # Fallback: scatter for non-rectangular sampling.
        pcm = ax.scatter(
            r * 1e3, z * 1e3, c=Bmag, cmap="viridis",
            vmin=vmin, vmax=vmax, s=8,
        )

    cb = fig.colorbar(pcm, ax=ax, shrink=0.92, pad=0.02)
    cb.set_label("|B| [T]", fontsize=10)
    cb.ax.tick_params(labelsize=9)
    ax.set_aspect("equal")
    ax.set_xlabel("r [mm]")
    ax.set_ylabel("z [mm]")
    ax.set_title(
        "Magnetic flux density — FEMM (legacy backend)",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(str(out), dpi=110, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)


def _render_centerline(csv_path: Path, out: Path) -> None:
    """1-D |B| vs r at z ≈ 0 (the gap centerline)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    r, z, Bmag, _, _ = _load_grid(csv_path)
    # Pick the z-row closest to zero.
    z_target = z[np.argmin(np.abs(z))]
    mask = np.abs(z - z_target) < 1e-9
    r_line = r[mask]
    B_line = Bmag[mask]
    order = np.argsort(r_line)
    r_sorted = r_line[order] * 1e3
    B_sorted = B_line[order]

    fig, ax = plt.subplots(figsize=(7.0, 4.4), dpi=110)
    fig.patch.set_facecolor("white")
    ax.plot(
        r_sorted, B_sorted,
        color="#7C3AED", marker="o", markersize=3,
        markerfacecolor="#7C3AED", markeredgecolor="white",
        markeredgewidth=0.4, linewidth=1.6,
    )
    ax.fill_between(r_sorted, 0, B_sorted, color="#7C3AED", alpha=0.10)

    if B_sorted.size:
        i_pk = int(np.argmax(np.abs(B_sorted)))
        ax.scatter(
            [r_sorted[i_pk]], [B_sorted[i_pk]],
            color="#DC2626", s=70, zorder=4,
            edgecolors="white", linewidths=1.4,
        )
        ax.annotate(
            f"peak {B_sorted[i_pk]:.3g} T",
            xy=(r_sorted[i_pk], B_sorted[i_pk]),
            xytext=(8, -16), textcoords="offset points",
            fontsize=9, color="#1F2937",
            bbox=dict(boxstyle="round,pad=0.35",
                      fc="white", ec="#D1D5DB", lw=0.7),
        )

    ax.set_xlabel("Radial position r [mm]")
    ax.set_ylabel("|B| [T]")
    ax.set_title(
        "Magnetic flux density along gap centerline (z ≈ 0) — FEMM",
        fontsize=11, fontweight="bold",
    )
    ax.grid(True, alpha=0.20, linestyle=":")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    fig.savefig(str(out), dpi=110, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)


def _render_histogram(csv_path: Path, out: Path) -> None:
    """Bar histogram + cumulative-volume CDF of |B|."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    _, _, Bmag, _, _ = _load_grid(csv_path)
    finite_mask = np.isfinite(Bmag)
    Bmag = Bmag[finite_mask]
    if Bmag.size == 0:
        return

    vmin = float(np.percentile(Bmag, 1.0))
    vmax = float(np.percentile(Bmag, 99.0))
    if vmax <= vmin:
        vmax = vmin + 1e-9
    bins = np.linspace(vmin, vmax, 41)
    counts, edges = np.histogram(Bmag, bins=bins)
    pct_per_bin = counts / max(Bmag.size, 1) * 100.0
    centers = 0.5 * (edges[:-1] + edges[1:])
    width = (edges[1] - edges[0]) * 0.9

    fig, ax_h = plt.subplots(figsize=(7.0, 4.4), dpi=110)
    fig.patch.set_facecolor("white")
    ax_h.bar(
        centers, pct_per_bin, width=width,
        color="#7C3AED", alpha=0.85,
        edgecolor="white", linewidth=0.4,
    )
    ax_h.set_xlabel("|B| [T]")
    ax_h.set_ylabel("Fraction of cross-section [%]", color="#7C3AED")
    ax_h.tick_params(axis="y", labelcolor="#7C3AED")
    ax_h.grid(True, alpha=0.20, linestyle=":", axis="y")
    for spine in ("top",):
        ax_h.spines[spine].set_visible(False)

    ax_c = ax_h.twinx()
    sorted_vals = np.sort(Bmag)
    cdf = np.arange(1, sorted_vals.size + 1) / sorted_vals.size * 100.0
    ax_c.plot(sorted_vals, cdf, color="#374151", linewidth=1.4)
    ax_c.set_ylabel("Cumulative volume [%]", color="#374151")
    ax_c.tick_params(axis="y", labelcolor="#374151")
    ax_c.set_ylim(0, 100)
    for spine in ("top",):
        ax_c.spines[spine].set_visible(False)

    ax_h.set_title(
        "Magnetic flux density — distribution across cross-section (FEMM)",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(str(out), dpi=110, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
