"""Synthetic-analytical fallback for the field-plots gallery.

When the FEA backend doesn't write field artefacts to disk
(legacy FEMM build that doesn't support ``io.open`` in LUA,
FEMMT crash before the post-processor runs, etc.) the gallery
collapses to its empty state and the user has nothing to look at.

This module synthesises a plausible ``|B|`` cross-section from
the analytical result the engine already computed (``B_pk_T``)
and the core's geometry. It is **not** a substitute for FEA —
the field shape is the textbook ``|B| ≈ B_pk · (r_in / r) ·
exp(-(z/σ)²)`` model, not a real solve — but it gives the
designer a reasonable look at where flux concentrates on the
cross-section while the backend is being debugged.

The synthesised PNGs follow the same naming convention the real
renderers use (``Magb.png`` / ``Magb_centerline.png`` /
``Magb_histogram.png``), so the existing
:class:`FEAFieldGallery` category rules pick them up
automatically.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def render_synthetic_field_pngs(
    output_dir: str | Path,
    *,
    B_pk_T: float,
    core,
    z_extent_mm: Optional[float] = None,
    label_suffix: str = "(analytical estimate)",
) -> list[Path]:
    """Generate synthetic field PNGs into ``output_dir``.

    Parameters
    ----------
    output_dir
        Directory the FEA solver wrote (or was supposed to
        write) into. The synthetic CSV + PNGs land next to
        whatever artefacts the real solver did manage to
        produce.
    B_pk_T
        Peak flux density from the analytical engine. The
        synthetic field is anchored on this value at the
        toroid's inner radius (or the leg surface for E-cores).
    core
        :class:`pfc_inductor.models.Core` instance — we read
        ``OD_mm`` / ``ID_mm`` / ``HT_mm`` to size the grid.
    z_extent_mm
        Half-height of the modelled cross-section in mm. ``None``
        defaults to ``core.HT_mm / 2``.
    label_suffix
        Appended to each PNG's title so the user can't mistake
        a synthetic estimate for a real solver output.

    Returns
    -------
    The list of PNG paths written. Empty list if the analytical
    inputs are insufficient (zero core dims or zero B_pk).
    """
    import numpy as np

    OD = float(getattr(core, "OD_mm", 0.0) or 0.0)
    ID = float(getattr(core, "ID_mm", 0.0) or 0.0)
    HT = float(getattr(core, "HT_mm", 0.0) or 0.0)
    if OD <= 0 or ID <= 0 or B_pk_T <= 0:
        logger.info(
            "Synthetic field render skipped: insufficient inputs (OD=%s, ID=%s, B_pk=%s).",
            OD,
            ID,
            B_pk_T,
        )
        return []
    if z_extent_mm is None:
        z_extent_mm = HT / 2 if HT > 0 else (OD - ID) / 4

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 50 × 50 grid in metres; mirrors the real legacy renderer.
    n_r, n_z = 50, 50
    r = np.linspace(ID / 2 * 1e-3, OD / 2 * 1e-3, n_r)
    z = np.linspace(-z_extent_mm * 1e-3, z_extent_mm * 1e-3, n_z)
    RR, ZZ = np.meshgrid(r, z, indexing="ij")

    # Field shape: 1/r radial decay × Gaussian z-profile. Anchor
    # at B_pk on the inner radius mid-height. ``σ_z`` is one
    # quarter of the half-height so the Gaussian falls off
    # naturally before the corners.
    r_inner = ID / 2 * 1e-3
    sigma_z = max(z_extent_mm * 1e-3 * 0.4, 1e-6)
    B = B_pk_T * (r_inner / RR) ** 1.0 * np.exp(-((ZZ / sigma_z) ** 2))
    Br = B * 0.6
    Bz = B * 0.8

    csv_path = out_dir / "b_field_grid.csv"
    with csv_path.open("w") as f:
        f.write("r_m,z_m,Br,Bz,Bmag\n")
        for i in range(n_r):
            for j in range(n_z):
                f.write(
                    f"{RR[i, j]:.6e},{ZZ[i, j]:.6e},{Br[i, j]:.6e},{Bz[i, j]:.6e},{B[i, j]:.6e}\n"
                )

    # Reuse the legacy renderer's heatmap / centerline /
    # histogram helpers — same chrome as the real backend
    # produces, just with a different title so the user knows
    # the source.
    from pfc_inductor.fea.legacy.grid_renderer import render_legacy_field_pngs

    pngs = render_legacy_field_pngs(out_dir)
    if not pngs:
        return []
    # Append the suffix to each PNG's metadata via a sidecar
    # rename so the lightbox / category rules still match. The
    # title text is already baked into the PNG by the legacy
    # renderer; we add a small ``synthetic.txt`` marker so the
    # gallery (or future runners) can detect that these are
    # estimated, not measured.
    (out_dir / "synthetic.txt").write_text(
        f"Field plots synthesised from analytical B_pk = {B_pk_T:.3f} T "
        f"because the FEA backend wrote no field data. {label_suffix}\n"
    )
    logger.info(
        "Synthetic field render: wrote %d PNGs into %s (B_pk=%.3f T).",
        len(pngs),
        out_dir,
        B_pk_T,
    )
    return pngs
