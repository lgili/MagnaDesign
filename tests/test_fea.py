"""FEA validation tests — focus on parts that don't need a live FEMM install."""
import tempfile
from pathlib import Path

import pytest

from pfc_inductor.data_loader import find_material, load_cores, load_materials
from pfc_inductor.design import design
from pfc_inductor.fea import (
    FEMMNotAvailable,
    active_backend,
    is_femm_available,
    is_femmt_available,
    validate_design,
)
from pfc_inductor.fea.legacy.femm_geometry import (
    FEAJobInputs,
    build_lua_script,
    write_lua_script,
)
from pfc_inductor.fea.legacy.femm_postprocess import (
    ResultsParseError,
    parse_results_file,
)
from pfc_inductor.fea.probe import install_hint
from pfc_inductor.models import Spec


@pytest.fixture(scope="module")
def design_inputs():
    mats = load_materials()
    cores = load_cores()
    mat = find_material(mats, "magnetics-60_highflux")
    core = next(c for c in cores
                if c.shape == "Toroid" and c.Wa_mm2 > 500 and c.Ae_mm2 > 50
                and c.default_material_id == "magnetics-60_highflux")
    spec = Spec(Vin_min_Vrms=85.0, Vin_max_Vrms=265.0, Vin_nom_Vrms=220.0,
                Vout_V=400.0, Pout_W=800.0, eta=0.97,
                f_sw_kHz=65.0, ripple_pct=30.0)
    from pfc_inductor.data_loader import load_wires
    wires = load_wires()
    wire = next(w for w in wires if w.id == "AWG14")
    result = design(spec, core, wire, mat)
    return spec, core, wire, mat, result


def test_probe_returns_bool():
    assert isinstance(is_femm_available(), bool)


def test_install_hint_returns_string():
    """When a backend is active, install_hint is empty; otherwise gives
    platform-specific install instructions."""
    hint = install_hint()
    assert isinstance(hint, str)
    if active_backend() == "none":
        assert len(hint) > 20


def test_lua_script_for_toroid_contains_required_calls(design_inputs):
    spec, core, wire, mat, result = design_inputs
    inputs = FEAJobInputs(
        core=core, material=mat, N_turns=result.N_turns,
        I_pk_A=result.I_line_pk_A,
        output_dir=Path(tempfile.gettempdir()),
    )
    script = build_lua_script(inputs)
    # All the FEMM Lua API calls we depend on must be present in the script.
    for token in [
        "newdocument(0)", "mi_probdef(", "mi_addmaterial",
        "mi_addboundprop", "mi_addcircprop",
        "mi_addnode", "mi_addsegment", "mi_addblocklabel",
        "mi_setblockprop", "mi_analyze", "mi_loadsolution",
        "mo_getcircuitproperties", "mo_getb",
        'string.format("L_H=%',
    ]:
        assert token in script, f"Missing Lua token: {token!r}"


def test_lua_script_paths_use_temp_output_dir(design_inputs):
    spec, core, wire, mat, result = design_inputs
    with tempfile.TemporaryDirectory() as td:
        inputs = FEAJobInputs(
            core=core, material=mat, N_turns=result.N_turns,
            I_pk_A=result.I_line_pk_A, output_dir=Path(td),
        )
        path = write_lua_script(inputs)
        assert path.exists()
        text = path.read_text()
        assert str(inputs.fem_path.as_posix()) in text
        assert str(inputs.results_path.as_posix()) in text


def test_lua_script_is_valid_lua_syntax(design_inputs):
    """Best-effort syntax check: balanced parens and no obvious malformation."""
    spec, core, wire, mat, result = design_inputs
    inputs = FEAJobInputs(
        core=core, material=mat, N_turns=result.N_turns,
        I_pk_A=result.I_line_pk_A,
        output_dir=Path(tempfile.gettempdir()),
    )
    s = build_lua_script(inputs)
    assert s.count("(") == s.count(")"), "Unbalanced parentheses"
    assert s.count("{") == s.count("}"), "Unbalanced braces"


def test_parse_results_file(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text(
        "L_H=3.87e-04\n"
        "flux_linkage_Wb=5.42e-03\n"
        "I_test_A=14.000\n"
        "B_pk_T=3.300e-01\n"
        "mu_eff_used=42.5\n"
        "N_turns=52\n"
    )
    r = parse_results_file(p)
    assert abs(r["L_H"] - 3.87e-04) < 1e-12
    assert r["N_turns"] == 52
    assert r["I_test_A"] == 14.000


def test_parse_results_missing_keys(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("L_H=1.0\n")  # missing required keys
    with pytest.raises(ResultsParseError):
        parse_results_file(p)


def test_validate_raises_when_no_backend(design_inputs):
    """If no FEA backend is available, validate_design must raise."""
    if active_backend() != "none":
        pytest.skip(f"FEA backend {active_backend()} active on this host")
    spec, core, wire, mat, result = design_inputs
    with pytest.raises(FEMMNotAvailable):
        validate_design(spec, core, wire, mat, result)


def test_active_backend_returns_known_value():
    assert active_backend() in ("femmt", "femm", "none")


def test_femmt_probe_returns_bool():
    assert isinstance(is_femmt_available(), bool)


def test_non_toroid_unsupported_in_v1(design_inputs):
    spec, _, wire, mat, result = design_inputs
    cores = load_cores()
    ee_core = next(c for c in cores if c.shape == "E" and c.Ve_mm3 > 5000)
    ee_mat = find_material(load_materials(), ee_core.default_material_id)
    inputs = FEAJobInputs(
        core=ee_core, material=ee_mat, N_turns=result.N_turns,
        I_pk_A=result.I_line_pk_A,
        output_dir=Path(tempfile.gettempdir()),
    )
    with pytest.raises(NotImplementedError):
        build_lua_script(inputs)


def test_signal_silence_unblocks_worker_thread():
    """Reproduces the ``ValueError: signal only works in main thread of the
    main interpreter`` regression that bit users when clicking
    Validar (FEA) — gmsh.initialize() registers SIGINT handlers
    unconditionally, so the FEMMT call has to silence ``signal.signal``
    while it runs on the Qt worker thread.
    """
    import signal
    import threading

    from pfc_inductor.fea.femmt_runner import _silence_signal_in_worker_thread

    captured: list[BaseException] = []

    def worker() -> None:
        try:
            with _silence_signal_in_worker_thread():
                # Without the patch this raises ValueError immediately.
                signal.signal(signal.SIGINT, signal.SIG_IGN)
            # Outside the patch we must restore the real signal.signal,
            # so calling it from a non-main thread raises again.
            try:
                signal.signal(signal.SIGINT, signal.SIG_IGN)
            except ValueError:
                pass
            else:
                captured.append(RuntimeError("signal.signal not restored"))
        except BaseException as e:
            captured.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert not captured, f"signal patch leaked: {captured[0]!r}"
