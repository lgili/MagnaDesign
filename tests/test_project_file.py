"""Round-trip + edge-case tests for the ``.pfc`` project format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pfc_inductor.models import Spec
from pfc_inductor.project import (
    PROJECT_FILE_EXTENSION,
    ProjectFile,
    ProjectSelection,
    empty_state,
    filter_existing,
    load_project,
    push_recent,
    save_project,
)


def test_project_file_default_state_is_clean() -> None:
    p = empty_state()
    assert p.name == "Untitled Project"
    assert p.selection.material_id == ""
    assert p.selection.core_id == ""
    assert p.selection.wire_id == ""
    assert p.spec.topology == "boost_ccm"


def test_round_trip_preserves_every_field(tmp_path: Path) -> None:
    """A non-trivial state, serialized then loaded, must match exactly."""
    spec = Spec(
        topology="boost_ccm",
        Vin_min_Vrms=110.0,
        Vin_max_Vrms=240.0,
        Vin_nom_Vrms=220.0,
        f_line_Hz=60.0,
        Vout_V=400.0,
        Pout_W=850.0,
        eta=0.965,
        f_sw_kHz=80.0,
        ripple_pct=25.0,
        T_amb_C=45.0,
        T_max_C=120.0,
        Ku_max=0.55,
        Bsat_margin=0.20,
    )
    state = ProjectFile.from_session(
        name="850W Reactor",
        spec=spec,
        material_id="dongxing-50h800",
        core_id="dongxing-ei4117-50h800",
        wire_id="awg14",
    )
    path = tmp_path / "design.pfc"
    save_project(path, state)
    loaded = load_project(path)

    assert loaded.name == "850W Reactor"
    assert loaded.selection.material_id == "dongxing-50h800"
    assert loaded.selection.core_id == "dongxing-ei4117-50h800"
    assert loaded.selection.wire_id == "awg14"
    assert loaded.spec.Pout_W == 850.0
    assert loaded.spec.f_sw_kHz == 80.0


def test_save_appends_extension_when_missing(tmp_path: Path) -> None:
    bare = tmp_path / "no_extension"
    final = save_project(bare, empty_state())
    assert final.suffix == PROJECT_FILE_EXTENSION


def test_load_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "broken.pfc"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_project(p)


def test_load_rejects_non_object_root(tmp_path: Path) -> None:
    p = tmp_path / "list_root.pfc"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_project(p)


def test_load_ignores_unknown_fields(tmp_path: Path) -> None:
    """Forward-compat: future versions may add fields. Unknown keys
    must not break the loader — Pydantic ``extra='ignore'``."""
    p = tmp_path / "future.pfc"
    p.write_text(
        json.dumps(
            {
                "version": "99.0",
                "name": "From the Future",
                "spec": Spec().model_dump(mode="json"),
                "selection": ProjectSelection().model_dump(mode="json"),
                "future_only_field": [1, 2, 3],
            }
        ),
        encoding="utf-8",
    )
    state = load_project(p)
    assert state.name == "From the Future"


def test_push_recent_dedups_and_caps() -> None:
    r: list[str] = []
    for i in range(7):
        r = push_recent(r, f"/tmp/p{i}.pfc")
    assert len(r) == 5
    assert r[0] == "/tmp/p6.pfc"
    r = push_recent(r, "/tmp/p3.pfc")
    assert r[0] == "/tmp/p3.pfc"
    assert r.count("/tmp/p3.pfc") == 1


def test_filter_existing_drops_missing(tmp_path: Path) -> None:
    real = tmp_path / "exists.pfc"
    real.write_text("{}", encoding="utf-8")
    fake = tmp_path / "ghost.pfc"
    surviving = filter_existing([str(real), str(fake)])
    assert surviving == [str(real)]
