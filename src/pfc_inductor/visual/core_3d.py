"""Parametric mesh generation for inductor cores and windings.

Geometry follows the physical proportions of real cores so the rendered
view matches what an engineer would build:

- **Toroid**: rectangular cross-section, hundreds of turns wrap through
  the hole; each turn tilts on the toroidal cross-section.
- **EE / EI**: 2 mating E halves with a centre leg ≈ 2× outer-leg
  width (the textbook proportion); two windows host the bobbin.
- **ETD / PQ**: round centre column + outer back-plates; bobbin
  winding sits annularly around the column.

The bobbin winding is generated as a multi-layer helix that **fits the
window**: number of turns per layer = floor(window_h / wire_d), number
of layers = ceil(N / turns_per_layer). When N is large the result is a
realistic-looking solenoid filling the window — not the unrealistic
single-helix passing through walls that the simpler ``Spline.tube``
gave us before.

All dimensions in millimetres. Centre at origin, bobbin axis along +Z
(both half-cores split symmetrically at z=0). Toroid axis is +Z.
"""
from __future__ import annotations
import math
from typing import Literal, Optional

import numpy as np
import pyvista as pv

from pfc_inductor.models import Core, Wire


ShapeKind = Literal["toroid", "ee", "etd", "pq", "generic"]


def infer_shape(core: Core) -> ShapeKind:
    """Map free-text core.shape to a known mesh kind."""
    s = (core.shape or "").lower().strip()
    if "tor" in s:
        return "toroid"
    if "etd" in s:
        return "etd"
    if s.startswith("pq") or "pq" in s:
        return "pq"
    if s.startswith("ee") or s.startswith("e ") or s == "e" or "nee" in s or "ei" in s:
        return "ee"
    return "generic"


# ---------------------------------------------------------------------------
# Dimension inference
# ---------------------------------------------------------------------------
def _toroid_dims(core: Core) -> Optional[tuple[float, float, float]]:
    """Return (OD_mm, ID_mm, HT_mm). Use explicit values if present, else
    infer from Wa, le, Ae:
        Wa = π·(ID/2)²        →  ID = 2·√(Wa/π)
        le = π·(OD+ID)/2      →  OD = 2·le/π − ID
        Ae = ((OD−ID)/2)·HT   →  HT = 2·Ae/(OD−ID)
    """
    if core.OD_mm and core.ID_mm and core.HT_mm:
        return core.OD_mm, core.ID_mm, core.HT_mm
    if core.le_mm > 0 and core.Wa_mm2 > 0 and core.Ae_mm2 > 0:
        ID = 2.0 * math.sqrt(core.Wa_mm2 / math.pi)
        OD = 2.0 * core.le_mm / math.pi - ID
        if OD <= ID:
            return None
        HT = 2.0 * core.Ae_mm2 / (OD - ID)
        return OD, ID, HT
    return None


def _bobbin_dims(core: Core) -> tuple[float, float, float]:
    """Estimate (W, H, D) for EE/ETD/PQ from the actual core parameters.

    Prefer the explicit ``OD_mm`` (used as overall width) and ``HT_mm``
    when the core ships them. Otherwise solve for the aspect ratios
    that satisfy Ae and Wa:

      - Center-leg cross-section ≈ Ae for ETD/PQ (round) or
        Ae = leg_W · D for EE.
      - Each window in the EE has area Wa/2 (two windows side by side).
      - Stack depth D ≈ Ae / leg_W for EE; height H ≈ 2 × leg_h_yoke
        + window_h.
    """
    Ae = max(core.Ae_mm2, 1e-6)
    Wa = max(core.Wa_mm2, 1e-6)
    Ve = max(core.Ve_mm3, Ae * 10.0)
    # If the core ships an outer dimension OD or HT, use it as anchor
    if core.OD_mm and core.HT_mm:
        W = core.OD_mm
        H = core.HT_mm
        D = Ve / max(W * H, 1e-6)
        if D <= 1.0:
            D = max(Ae / max(W / 4.0, 1e-3), W * 0.4)
        return W, H, D
    # Solve from Ae/Wa for an EE-like layout: leg_w = W·0.16,
    # center_w = W·0.32, two windows of W·0.18 wide, total W=1.0·W.
    # Window height (= bobbin h) ≈ Wa / (2 · 0.18W) = 2.78 Wa / W.
    # Stack D ≈ Ae / leg_w_center = Ae / (0.32W).
    # Cube root of Ve to anchor scale, then refine.
    W = (Ve * 1.4) ** (1 / 3)
    D = Ae / (0.32 * W)
    H = 2.0 * (W * 0.18) + Wa / (2 * 0.18 * W)  # 2 yokes + window height
    # Sanity-clamp aspect to avoid pathological shapes from bad data
    if D < W * 0.30:
        D = W * 0.30
    if D > W * 1.10:
        D = W * 1.10
    if H < W * 0.50:
        H = W * 0.50
    if H > W * 1.30:
        H = W * 1.30
    return W, H, D


# ---------------------------------------------------------------------------
# Toroid (rectangular cross-section)
# ---------------------------------------------------------------------------
def _toroid_mesh(OD_mm: float, ID_mm: float, HT_mm: float,
                 resolution: int = 96) -> pv.PolyData:
    """Annulus extruded along Z. Built directly as a quad mesh (4 rings × n)."""
    R_o = OD_mm / 2.0
    R_i = ID_mm / 2.0
    H = HT_mm
    n = resolution

    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)
    z_b, z_t = -H / 2, H / 2
    out_b = np.column_stack([R_o * cos_t, R_o * sin_t, np.full(n, z_b)])
    out_t = np.column_stack([R_o * cos_t, R_o * sin_t, np.full(n, z_t)])
    in_t = np.column_stack([R_i * cos_t, R_i * sin_t, np.full(n, z_t)])
    in_b = np.column_stack([R_i * cos_t, R_i * sin_t, np.full(n, z_b)])
    points = np.vstack([out_b, out_t, in_t, in_b])

    def quad(a, b, c, d):
        return [4, a, b, c, d]

    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces += quad(i, j, n + j, n + i)              # outer wall
        faces += quad(n + i, n + j, 2 * n + j, 2 * n + i)  # top annulus
        faces += quad(2 * n + i, 2 * n + j, 3 * n + j, 3 * n + i)  # inner wall
        faces += quad(3 * n + i, 3 * n + j, j, i)      # bottom annulus

    mesh = pv.PolyData(points, np.asarray(faces, dtype=np.int64))
    mesh.compute_normals(inplace=True, auto_orient_normals=True)
    return mesh


def _toroidal_winding(OD_mm: float, ID_mm: float, HT_mm: float,
                       N_turns: int, wire_d_mm: float = 1.0,
                       points_per_turn: int = 28) -> pv.PolyData:
    """N-turn winding wrapping through the toroid hole.

    Each turn passes once through the centre hole and over the outer
    rim; turns are distributed around the toroid axis. Render a tube
    along that path; if the wire would self-intersect for very large
    N (e.g. 200+ turns on a small toroid) we cap turns_per_loop so the
    visual stays readable while still conveying the right pattern.
    """
    R0 = (OD_mm + ID_mm) / 4.0
    cs_w = (OD_mm - ID_mm) / 2.0
    cs_h = HT_mm
    # Cap visualised turns so the helix doesn't overlap into a blob.
    N_visual = min(N_turns, 80)
    r_radial = cs_w / 2.0 + wire_d_mm / 2.0 + 0.4
    r_axial = cs_h / 2.0 + wire_d_mm / 2.0 + 0.4
    n_pts = max(N_visual * points_per_turn, 96)
    t = np.linspace(0.0, 1.0, n_pts)
    phi = 2 * np.pi * t
    psi = 2 * np.pi * N_visual * t
    R = R0 + r_radial * np.cos(psi)
    z = r_axial * np.sin(psi)
    x = R * np.cos(phi)
    y = R * np.sin(phi)
    points = np.column_stack([x, y, z])
    spline = pv.Spline(points, n_pts)
    return spline.tube(radius=wire_d_mm / 2.0, n_sides=14)


# ---------------------------------------------------------------------------
# EE / EI core — proper proportions: centre leg ≈ 2× outer leg
# ---------------------------------------------------------------------------
def _ee_proportions(W: float) -> tuple[float, float, float]:
    """Return (outer_leg_w, center_leg_w, window_w) such that
    2·outer + center + 2·window = W with center = 2·outer.
    Ratios picked from JIS EE / E-26 / ETD-29 datasheets.
    """
    outer_w = W * 0.16
    center_w = W * 0.32
    window_w = W * 0.18
    return outer_w, center_w, window_w


def _ee_half(z_back: float, z_open: float, W: float, D: float,
             outer_w: float, center_w: float, back_t: float,
             ) -> list[pv.PolyData]:
    """One half of an E core. Back plate (yoke) at z_back,
    centre + 2 outer legs span back-plate inner face → z_open.
    """
    direction = 1 if z_open > z_back else -1
    back_inner = z_back + direction * back_t
    leg_z_lo = min(back_inner, z_open)
    leg_z_hi = max(back_inner, z_open)
    back_z_lo = min(z_back, back_inner)
    back_z_hi = max(z_back, back_inner)

    blocks = []
    blocks.append(pv.Box(bounds=(-W / 2, W / 2, -D / 2, D / 2,
                                 back_z_lo, back_z_hi)))
    # 2 outer legs
    for cx in (-W / 2 + outer_w / 2, W / 2 - outer_w / 2):
        blocks.append(pv.Box(bounds=(
            cx - outer_w / 2, cx + outer_w / 2,
            -D / 2, D / 2,
            leg_z_lo, leg_z_hi,
        )))
    # centre leg (wider)
    blocks.append(pv.Box(bounds=(
        -center_w / 2, center_w / 2,
        -D / 2, D / 2,
        leg_z_lo, leg_z_hi,
    )))
    return blocks


def _ee_mesh(W: float, H: float, D: float, gap_mm: float = 0.0
             ) -> pv.MultiBlock:
    outer_w, center_w, window_w = _ee_proportions(W)
    back_t = H * 0.18
    half_h = (H - gap_mm) / 2.0
    if half_h <= back_t:
        half_h = back_t * 1.5

    z_top_back = gap_mm / 2 + half_h
    z_bot_back = -(gap_mm / 2 + half_h)

    mb = pv.MultiBlock()
    for i, b in enumerate(_ee_half(z_top_back, gap_mm / 2, W, D,
                                    outer_w, center_w, back_t)):
        mb.append(b, name=f"top_{i}")
    for i, b in enumerate(_ee_half(z_bot_back, -gap_mm / 2, W, D,
                                    outer_w, center_w, back_t)):
        mb.append(b, name=f"bot_{i}")
    return mb


# ---------------------------------------------------------------------------
# ETD - back plate + 2 outer legs + round centre column per half
# ---------------------------------------------------------------------------
def _etd_half(z_back: float, z_open: float, W: float, D: float,
              outer_w: float, back_t: float, col_r: float
              ) -> list[pv.PolyData]:
    direction = 1 if z_open > z_back else -1
    back_inner = z_back + direction * back_t
    leg_z_lo = min(back_inner, z_open)
    leg_z_hi = max(back_inner, z_open)
    back_z_lo = min(z_back, back_inner)
    back_z_hi = max(z_back, back_inner)

    blocks = [
        pv.Box(bounds=(-W / 2, W / 2, -D / 2, D / 2, back_z_lo, back_z_hi)),
    ]
    for cx in (-W / 2 + outer_w / 2, W / 2 - outer_w / 2):
        blocks.append(pv.Box(bounds=(
            cx - outer_w / 2, cx + outer_w / 2,
            -D / 2, D / 2,
            leg_z_lo, leg_z_hi,
        )))
    blocks.append(pv.Cylinder(
        center=(0, 0, (leg_z_lo + leg_z_hi) / 2),
        direction=(0, 0, 1),
        radius=col_r, height=(leg_z_hi - leg_z_lo) * 0.999,
        capping=True, resolution=64,
    ))
    return blocks


def _etd_mesh(W: float, H: float, D: float, gap_mm: float = 0.0
              ) -> pv.MultiBlock:
    outer_w = W * 0.13
    col_r = W * 0.16
    back_t = H * 0.16
    half_h = (H - gap_mm) / 2.0
    if half_h <= back_t:
        half_h = back_t * 1.5

    z_top_back = gap_mm / 2 + half_h
    z_bot_back = -(gap_mm / 2 + half_h)
    mb = pv.MultiBlock()
    for i, b in enumerate(_etd_half(z_top_back, gap_mm / 2, W, D,
                                     outer_w, back_t, col_r)):
        mb.append(b, name=f"top_{i}")
    for i, b in enumerate(_etd_half(z_bot_back, -gap_mm / 2, W, D,
                                     outer_w, back_t, col_r)):
        mb.append(b, name=f"bot_{i}")
    return mb


# ---------------------------------------------------------------------------
# PQ - square shell + round centre column. Only side walls (front and
# back open for winding entry).
# ---------------------------------------------------------------------------
def _pq_half(z_back: float, z_open: float, W: float, D: float,
             wall_t: float, back_t: float, col_r: float) -> list[pv.PolyData]:
    direction = 1 if z_open > z_back else -1
    back_inner = z_back + direction * back_t
    leg_z_lo = min(back_inner, z_open)
    leg_z_hi = max(back_inner, z_open)
    back_z_lo = min(z_back, back_inner)
    back_z_hi = max(z_back, back_inner)

    blocks = [
        pv.Box(bounds=(-W / 2, W / 2, -D / 2, D / 2, back_z_lo, back_z_hi)),
    ]
    for cx in (-W / 2 + wall_t / 2, W / 2 - wall_t / 2):
        blocks.append(pv.Box(bounds=(
            cx - wall_t / 2, cx + wall_t / 2,
            -D / 2, D / 2,
            leg_z_lo, leg_z_hi,
        )))
    blocks.append(pv.Cylinder(
        center=(0, 0, (leg_z_lo + leg_z_hi) / 2),
        direction=(0, 0, 1),
        radius=col_r, height=(leg_z_hi - leg_z_lo) * 0.999,
        capping=True, resolution=64,
    ))
    return blocks


def _pq_mesh(W: float, H: float, D: float, gap_mm: float = 0.0
             ) -> pv.MultiBlock:
    col_r = W * 0.22
    wall_t = W * 0.13
    back_t = H * 0.18
    half_h = (H - gap_mm) / 2.0
    if half_h <= back_t:
        half_h = back_t * 1.5

    z_top_back = gap_mm / 2 + half_h
    z_bot_back = -(gap_mm / 2 + half_h)
    mb = pv.MultiBlock()
    for i, b in enumerate(_pq_half(z_top_back, gap_mm / 2, W, D,
                                    wall_t, back_t, col_r)):
        mb.append(b, name=f"top_{i}")
    for i, b in enumerate(_pq_half(z_bot_back, -gap_mm / 2, W, D,
                                    wall_t, back_t, col_r)):
        mb.append(b, name=f"bot_{i}")
    return mb


# ---------------------------------------------------------------------------
# Bobbin (FR530 nylon between core and winding)
# ---------------------------------------------------------------------------
def _bobbin_shell(col_r: float, winding_h: float, wire_d_mm: float,
                  layers: int, radial_max: float
                  ) -> pv.MultiBlock:
    """Plastic bobbin (round): just the two flanges. Used by ETD/PQ."""
    flange_t = wire_d_mm * 0.5
    flange_r = min(
        col_r + wire_d_mm * (layers + 0.6),
        radial_max - 0.2,
    )
    flange_r = max(flange_r, col_r + wire_d_mm * 1.2)
    mb = pv.MultiBlock()
    mb.append(pv.Cylinder(
        center=(0, 0, winding_h / 2 + flange_t / 2),
        direction=(0, 0, 1),
        radius=flange_r, height=flange_t,
        capping=True, resolution=64,
    ), name="bobbin_flange_top")
    mb.append(pv.Cylinder(
        center=(0, 0, -winding_h / 2 - flange_t / 2),
        direction=(0, 0, 1),
        radius=flange_r, height=flange_t,
        capping=True, resolution=64,
    ), name="bobbin_flange_bot")
    return mb


def _bobbin_shell_rect(leg_w: float, leg_d: float, winding_h: float,
                       wire_d_mm: float, layers: int,
                       radial_max_w: float, radial_max_d: float
                       ) -> pv.MultiBlock:
    """Plastic bobbin (rectangular) for EE: two thin slabs at the top
    and bottom of the winding stack. Sized to clear the centre leg
    and contain the multi-layer winding without bursting into the
    outer legs or beyond the core depth.
    """
    flange_t = wire_d_mm * 0.5
    margin = wire_d_mm * 0.6
    # Width (W axis) — limited by inner face of outer legs.
    a = min(leg_w + 2 * (layers * wire_d_mm + margin),
            2 * radial_max_w - 0.4)
    a = max(a, leg_w + wire_d_mm * 2)
    # Depth (D axis) — limited to the leg depth itself; the winding
    # only fans out in the W direction in a real EE bobbin.
    b = min(leg_d + 2 * margin, leg_d + wire_d_mm * 2)
    b = max(b, leg_d * 1.02)
    mb = pv.MultiBlock()
    z_top = winding_h / 2 + flange_t / 2
    z_bot = -winding_h / 2 - flange_t / 2
    mb.append(pv.Box(bounds=(-a/2, a/2, -b/2, b/2,
                             z_top - flange_t/2, z_top + flange_t/2)),
              name="bobbin_flange_top")
    mb.append(pv.Box(bounds=(-a/2, a/2, -b/2, b/2,
                             z_bot - flange_t/2, z_bot + flange_t/2)),
              name="bobbin_flange_bot")
    return mb


# ---------------------------------------------------------------------------
# Multi-layer bobbin winding constrained to the window
# ---------------------------------------------------------------------------
def _rect_path_xy(a: float, b: float, r_corner: float, n_pts: int = 96
                  ) -> np.ndarray:
    """Trace a rounded rectangle of sides ``a × b`` (full lengths) with
    corner radius ``r_corner``. Returns ``n_pts`` (x, y) points sampled
    proportionally along the perimeter, starting at the right-mid edge
    and going counter-clockwise.
    """
    a2 = a / 2.0 - r_corner
    b2 = b / 2.0 - r_corner
    if a2 < 0 or b2 < 0:
        # The leg is smaller than 2·r_corner — reduce r so it fits.
        r_corner = min(a, b) / 2.0
        a2 = a / 2.0 - r_corner
        b2 = b / 2.0 - r_corner
    seg_len = [
        2 * b2,                  # right edge (going up)
        math.pi * r_corner / 2,  # top-right corner
        2 * a2,                  # top edge (going left)
        math.pi * r_corner / 2,  # top-left
        2 * b2,                  # left edge (going down)
        math.pi * r_corner / 2,  # bot-left
        2 * a2,                  # bottom edge (going right)
        math.pi * r_corner / 2,  # bot-right
    ]
    total = sum(seg_len)
    s = np.linspace(0.0, total, n_pts, endpoint=False)
    xs = np.empty(n_pts)
    ys = np.empty(n_pts)
    edges_cum = np.cumsum([0] + seg_len)
    for i, sk in enumerate(s):
        if sk < edges_cum[1]:
            t = sk / seg_len[0]
            xs[i] = a / 2.0
            ys[i] = -b2 + 2 * b2 * t
        elif sk < edges_cum[2]:
            t = (sk - edges_cum[1]) / seg_len[1]
            ang = -math.pi / 2 + math.pi / 2 * t      # 270°→360° local
            xs[i] = a2 + r_corner * math.cos(ang)
            ys[i] = b2 + r_corner * math.sin(ang)
        elif sk < edges_cum[3]:
            t = (sk - edges_cum[2]) / seg_len[2]
            xs[i] = a2 - 2 * a2 * t
            ys[i] = b / 2.0
        elif sk < edges_cum[4]:
            t = (sk - edges_cum[3]) / seg_len[3]
            ang = 0.0 + math.pi / 2 * t                # 0°→90°
            xs[i] = -a2 + r_corner * math.cos(math.pi / 2 + ang)
            ys[i] = b2 + r_corner * math.sin(math.pi / 2 + ang)
        elif sk < edges_cum[5]:
            t = (sk - edges_cum[4]) / seg_len[4]
            xs[i] = -a / 2.0
            ys[i] = b2 - 2 * b2 * t
        elif sk < edges_cum[6]:
            t = (sk - edges_cum[5]) / seg_len[5]
            ang = math.pi + math.pi / 2 * t            # 180°→270°
            xs[i] = -a2 + r_corner * math.cos(ang)
            ys[i] = -b2 + r_corner * math.sin(ang)
        elif sk < edges_cum[7]:
            t = (sk - edges_cum[6]) / seg_len[6]
            xs[i] = -a2 + 2 * a2 * t
            ys[i] = -b / 2.0
        else:
            t = (sk - edges_cum[7]) / seg_len[7]
            ang = -math.pi / 2 + math.pi / 2 * t       # but on bot-right
            xs[i] = a2 + r_corner * math.cos(-math.pi / 2 - math.pi / 2 + ang)
            ys[i] = -b2 + r_corner * math.sin(-math.pi / 2 - math.pi / 2 + ang)
    return np.column_stack([xs, ys])


def _bobbin_winding_rect(
    H_window: float, leg_w: float, leg_d: float,
    radial_max_w: float, radial_max_d: float,
    N_turns: int, wire_d_mm: float = 1.0,
) -> tuple[pv.PolyData, int]:
    """Multi-layer rectangular helical winding around an EE centre leg.

    Each turn traces a rounded rectangle around the (leg_w × leg_d)
    centre leg at a radius offset (one wire_d per layer). Number of
    turns per layer is constrained by ``H_window``.
    """
    if N_turns <= 0:
        return pv.PolyData(), 0
    margin = wire_d_mm * 0.4
    h_eff = max(H_window - 2 * margin, wire_d_mm * 4)
    turns_per_layer = max(1, int(h_eff // wire_d_mm))
    # In a real EE bobbin the winding only thickens in the W direction
    # (the leg fills the full stack along D). So radial room is
    # determined by the W-axis window only.
    radial_room = max(radial_max_w - leg_w / 2 - wire_d_mm * 0.6, wire_d_mm)
    n_layers_max = max(1, int(radial_room // wire_d_mm))
    n_layers_needed = max(1, math.ceil(N_turns / turns_per_layer))
    n_layers = min(n_layers_needed, n_layers_max)
    actual_turns = min(N_turns, n_layers * turns_per_layer)

    points_per_turn = 96
    pts_list: list[np.ndarray] = []
    for layer in range(n_layers):
        offset = wire_d_mm * (layer + 0.6)
        # Width grows with layers; depth stays clamped to leg_d so the
        # winding doesn't poke through the front/back of the stack.
        a = leg_w + 2 * offset
        b = leg_d + 2 * (wire_d_mm * 0.6)        # tiny clearance only
        r_corner = max(offset, wire_d_mm * 0.5)
        path = _rect_path_xy(a, b, r_corner, points_per_turn)
        # Number of turns on this layer (last layer may be partial)
        remaining = actual_turns - layer * turns_per_layer
        n_this = min(turns_per_layer, max(0, remaining))
        if n_this <= 0:
            break
        # Vertical position alternates direction layer-to-layer
        if layer % 2 == 0:
            zs_lo, zs_hi = -h_eff / 2, h_eff / 2
        else:
            zs_lo, zs_hi = h_eff / 2, -h_eff / 2
        zs_layer = np.linspace(zs_lo, zs_hi, n_this * points_per_turn)
        # Tile the path n_this times then attach the z column
        path_tiled = np.tile(path, (n_this, 1))
        layer_pts = np.column_stack([path_tiled, zs_layer])
        pts_list.append(layer_pts)
    if not pts_list:
        return pv.PolyData(), n_layers
    pts = np.vstack(pts_list)
    spline = pv.Spline(pts, len(pts))
    tube = spline.tube(radius=wire_d_mm * 0.45, n_sides=10)
    return tube, n_layers


def _bobbin_winding(
    H_window: float, col_r: float, max_radial_mm: float,
    N_turns: int, wire_d_mm: float = 1.0,
) -> tuple[pv.PolyData, int]:
    """Multi-layer helical winding that fills the bobbin window.

    Layout:
      - turns_per_layer = floor(H_window / wire_d) (vertical packing)
      - layers needed   = ceil(N_turns / turns_per_layer)
      - radial step     = wire_d (each layer pushed out by 1 wire diameter)

    The winding starts at the bottom of the window on layer 0, climbs
    to the top, hops out one wire diameter, climbs back down, and so
    on. Direction reverses every layer to mimic real bobbin pattern.

    Returns the tube mesh and the realised number of layers (the
    caller uses it to size the bobbin).
    """
    if N_turns <= 0 or H_window <= 0:
        empty = pv.PolyData()
        return empty, 0
    margin = wire_d_mm * 0.4
    h_eff = max(H_window - 2 * margin, wire_d_mm * 4)
    turns_per_layer = max(1, int(h_eff // wire_d_mm))
    n_layers_needed = max(1, math.ceil(N_turns / turns_per_layer))
    # Cap by available radial space
    radial_room = max(max_radial_mm - col_r - wire_d_mm * 0.5, wire_d_mm)
    n_layers_max = max(1, int(radial_room // wire_d_mm))
    n_layers = min(n_layers_needed, n_layers_max)
    actual_turns = min(N_turns, n_layers * turns_per_layer)

    # Generate the spline
    points_per_turn = 32
    n_pts = actual_turns * points_per_turn
    t_layer = np.linspace(0.0, 1.0, points_per_turn, endpoint=False)
    pts = np.empty((n_pts, 3))
    idx = 0
    for layer in range(n_layers):
        r = col_r + wire_d_mm * 0.5 + layer * wire_d_mm
        # Vertical position along this layer (alternating direction)
        if layer % 2 == 0:
            zs_lo, zs_hi = -h_eff / 2, h_eff / 2
        else:
            zs_lo, zs_hi = h_eff / 2, -h_eff / 2
        # Number of turns on this layer (last layer may be short)
        remaining = actual_turns - layer * turns_per_layer
        n_this = min(turns_per_layer, max(0, remaining))
        if n_this <= 0:
            break
        for k in range(n_this):
            for tt in t_layer:
                phi = 2 * np.pi * (k + tt)
                # z linearly progresses across the layer
                u = (k + tt) / max(turns_per_layer, 1)
                z = zs_lo + (zs_hi - zs_lo) * u
                pts[idx] = (r * np.cos(phi), r * np.sin(phi), z)
                idx += 1
    pts = pts[:idx]
    if len(pts) < 4:
        empty = pv.PolyData()
        return empty, n_layers
    spline = pv.Spline(pts, len(pts))
    tube = spline.tube(radius=wire_d_mm * 0.45, n_sides=10)
    return tube, n_layers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def make_core_mesh(core: Core) -> tuple[pv.MultiBlock, ShapeKind, dict]:
    """Build a MultiBlock mesh for the core. Returns (mesh, shape_kind, info)."""
    kind = infer_shape(core)

    if kind == "toroid":
        dims = _toroid_dims(core)
        if dims is not None:
            OD, ID, HT = dims
            mb = pv.MultiBlock()
            mb.append(_toroid_mesh(OD, ID, HT), name="core")
            return mb, "toroid", {"OD_mm": OD, "ID_mm": ID, "HT_mm": HT}

    if kind == "etd":
        W, H, D = _bobbin_dims(core)
        outer_w = W * 0.13
        col_r = W * 0.16
        back_t = H * 0.16
        winding_h = max(H - 2 * back_t - core.lgap_mm, H * 0.4)
        # Available radial room: from col_r up to (W/2 - outer_w)
        radial_max = W / 2.0 - outer_w - 0.5
        return _etd_mesh(W, H, D, gap_mm=core.lgap_mm), "etd", {
            "W": W, "H": H, "D": D, "col_r": col_r,
            "winding_h": winding_h, "back_t": back_t,
            "radial_max": radial_max,
        }

    if kind == "pq":
        W, H, D = _bobbin_dims(core)
        col_r = W * 0.22
        wall_t = W * 0.13
        back_t = H * 0.18
        winding_h = max(H - 2 * back_t - core.lgap_mm, H * 0.4)
        radial_max = W / 2.0 - wall_t - 0.5
        return _pq_mesh(W, H, D, gap_mm=core.lgap_mm), "pq", {
            "W": W, "H": H, "D": D, "col_r": col_r,
            "winding_h": winding_h, "back_t": back_t,
            "radial_max": radial_max,
        }

    if kind == "ee":
        W, H, D = _bobbin_dims(core)
        outer_w, center_w, window_w = _ee_proportions(W)
        back_t = H * 0.18
        winding_h = max(H - 2 * back_t - core.lgap_mm, H * 0.4)
        # EE keeps a *rectangular* winding around the rectangular centre
        # leg. Available radial room is (window_w − clearance) on the
        # W-axis and (D/2 − leg_d/2) on the D-axis (in practice ~0 for
        # most EE because the leg fills the full stack — that means
        # the winding can't extend in the D direction beyond the leg
        # itself; it only gains thickness in the W direction).
        radial_max_w = W / 2 - outer_w - 0.4         # outer-leg inner face
        radial_max_d = D / 2 + window_w * 0.6        # winding can poke past
                                                       # the stack along D
        return _ee_mesh(W, H, D, gap_mm=core.lgap_mm), "ee", {
            "W": W, "H": H, "D": D,
            "leg_w": center_w, "leg_d": D,
            "winding_h": winding_h, "back_t": back_t,
            "radial_max_w": radial_max_w,
            "radial_max_d": radial_max_d,
        }

    # Generic: simple cube from Ve
    side = max(core.Ve_mm3, 1.0) ** (1 / 3)
    box = pv.Box(bounds=(-side / 2, side / 2, -side / 2, side / 2,
                         -side / 2, side / 2))
    mb = pv.MultiBlock()
    mb.append(box, name="core")
    return mb, "generic", {"side": side}


def make_winding_mesh(
    core: Core,
    wire: Wire,
    N_turns: int,
    info: Optional[dict] = None,
) -> Optional[pv.PolyData]:
    """Build a winding mesh matched to the core scale."""
    if N_turns <= 0:
        return None
    wire_d = max(wire.outer_diameter_mm(), 0.3)
    kind = infer_shape(core)
    info = info or {}

    if kind == "toroid":
        dims = _toroid_dims(core)
        if dims is None:
            return None
        OD, ID, HT = dims
        return _toroidal_winding(OD, ID, HT, N_turns, wire_d)

    if kind == "ee":
        winding_h = info.get("winding_h", 10.0)
        leg_w = info.get("leg_w", 8.0)
        leg_d = info.get("leg_d", 8.0)
        radial_max_w = info.get("radial_max_w", leg_w)
        radial_max_d = info.get("radial_max_d", leg_d)
        tube, _ = _bobbin_winding_rect(
            winding_h, leg_w, leg_d, radial_max_w, radial_max_d,
            N_turns, wire_d,
        )
        return tube

    if kind in ("etd", "pq"):
        winding_h = info.get("winding_h", 10.0)
        col_r = info.get("col_r", 5.0)
        radial_max = info.get("radial_max", col_r * 2.0)
        tube, _ = _bobbin_winding(winding_h, col_r, radial_max,
                                   N_turns, wire_d)
        return tube
    return None


def make_bobbin_mesh(
    core: Core,
    wire: Wire,
    N_turns: int,
    info: Optional[dict] = None,
) -> Optional[pv.MultiBlock]:
    """Plastic bobbin matched to the winding stack height."""
    if N_turns <= 0:
        return None
    kind = infer_shape(core)
    if kind not in ("etd", "pq", "ee"):
        return None
    info = info or {}
    wire_d = max(wire.outer_diameter_mm(), 0.3)
    winding_h = info.get("winding_h", 10.0)
    margin = wire_d * 0.4
    h_eff = max(winding_h - 2 * margin, wire_d * 4)
    turns_per_layer = max(1, int(h_eff // wire_d))
    n_layers = max(1, math.ceil(N_turns / turns_per_layer))

    if kind == "ee":
        leg_w = info.get("leg_w", 8.0)
        leg_d = info.get("leg_d", 8.0)
        rmax_w = info.get("radial_max_w", leg_w)
        rmax_d = info.get("radial_max_d", leg_d)
        radial_room = min(rmax_w - leg_w / 2, rmax_d - leg_d / 2) - wire_d * 0.6
        n_layers = min(n_layers, max(1, int(max(radial_room, wire_d) // wire_d)))
        return _bobbin_shell_rect(leg_w, leg_d, winding_h, wire_d,
                                   n_layers, rmax_w, rmax_d)
    # ETD / PQ — round bobbin
    col_r = info.get("col_r", 5.0)
    radial_max = info.get("radial_max", col_r * 2.0)
    radial_room = max(radial_max - col_r - wire_d * 0.5, wire_d)
    n_layers = min(n_layers, max(1, int(radial_room // wire_d)))
    return _bobbin_shell(col_r, winding_h, wire_d, n_layers, radial_max)
