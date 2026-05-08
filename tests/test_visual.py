"""Mesh generation tests for the 3D viewer.

Run with PyVista in off-screen mode (no QtInteractor) so they work in CI/headless.
"""

import os

os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")

import pyvista as pv

pv.OFF_SCREEN = True

from pfc_inductor.data_loader import load_cores, load_wires
from pfc_inductor.visual import infer_shape, make_core_mesh, make_winding_mesh


def _first_with_shape(cores, shape_predicate, min_volume_mm3=5000.0):
    return next(c for c in cores if shape_predicate(c) and c.Ve_mm3 > min_volume_mm3)


def test_infer_shape_classifies_known_strings():
    class _Stub:
        def __init__(self, shape):
            self.shape = shape

    assert infer_shape(_Stub("Toroid")) == "toroid"
    assert infer_shape(_Stub("ETD44")) == "etd"
    assert infer_shape(_Stub("PQ 32/30")) == "pq"
    assert infer_shape(_Stub("E 100/60/28")) == "ee"
    assert infer_shape(_Stub("EI 30/15")) == "ee"
    assert infer_shape(_Stub("foobar")) == "generic"


def test_toroid_mesh_has_real_geometry():
    cores = load_cores()
    core = _first_with_shape(cores, lambda c: c.shape == "Toroid" and c.Wa_mm2 > 500)
    mb, kind, info = make_core_mesh(core)
    assert kind == "toroid"
    n_pts = sum(b.n_points for b in mb if b is not None)
    n_cells = sum(b.n_cells for b in mb if b is not None)
    assert n_pts > 100, f"Toroid mesh too sparse: {n_pts} points"
    assert n_cells > 100
    # OD must exceed ID
    assert info["OD_mm"] > info["ID_mm"]
    # HT positive
    assert info["HT_mm"] > 0


def test_ee_mesh_constructive_has_legs_and_back():
    cores = load_cores()
    core = _first_with_shape(cores, lambda c: c.shape == "E")
    mb, kind, _info = make_core_mesh(core)
    assert kind == "ee"
    # 5 prisms per half × 2 halves = 10 blocks (back + 3 legs each)
    blocks = [b for b in mb if b is not None]
    assert len(blocks) == 8  # 1 back + 3 legs per half × 2 halves


def test_pq_mesh_has_center_column():
    cores = load_cores()
    core = _first_with_shape(cores, lambda c: c.shape == "PQ")
    mb, kind, _info = make_core_mesh(core)
    assert kind == "pq"
    # Each half = back + 2 walls + 1 cylinder = 4 blocks; 2 halves = 8
    blocks = [b for b in mb if b is not None]
    assert len(blocks) == 8


def test_winding_mesh_for_toroid():
    cores = load_cores()
    wires = load_wires()
    core = _first_with_shape(cores, lambda c: c.shape == "Toroid" and c.Wa_mm2 > 500)
    wire = next(w for w in wires if w.id == "AWG14")
    _mb, _kind, info = make_core_mesh(core)
    wnd = make_winding_mesh(core, wire, N_turns=30, info=info)
    assert wnd is not None
    assert wnd.n_points > 500


def test_winding_mesh_for_bobbin_shapes():
    cores = load_cores()
    wires = load_wires()
    wire = next(w for w in wires if w.id == "AWG14")
    for shape_str in ("E", "PQ"):
        core = _first_with_shape(cores, lambda c: c.shape == shape_str)
        _mb, kind, info = make_core_mesh(core)
        wnd = make_winding_mesh(core, wire, N_turns=30, info=info)
        assert wnd is not None, f"No winding generated for {kind}"


def test_winding_height_within_window_for_bobbin():
    """Winding must NOT extend into the back plates (visible bug from earlier)."""
    cores = load_cores()
    wires = load_wires()
    wire = next(w for w in wires if w.id == "AWG14")
    core = _first_with_shape(cores, lambda c: c.shape == "PQ")
    _mb, _kind, info = make_core_mesh(core)
    wnd = make_winding_mesh(core, wire, N_turns=30, info=info)
    H = info["H"]
    back_t = info["back_t"]
    z_max_allowed = H / 2 - back_t * 0.5  # generous tolerance
    pts = wnd.points
    assert pts[:, 2].max() <= z_max_allowed, (
        f"Winding crosses into back plate: max z = {pts[:, 2].max()}, allowed = {z_max_allowed}"
    )
    assert pts[:, 2].min() >= -z_max_allowed
