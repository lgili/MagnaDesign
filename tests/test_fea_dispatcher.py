"""Per-shape FEA backend dispatcher tests."""
from __future__ import annotations

from pfc_inductor.fea import (
    backend_fidelity,
    is_femm_available,
    is_femmt_available,
    select_backend_for_shape,
)


def test_dispatcher_returns_known_value():
    for shape in ("toroid", "ee", "etd", "pq", "generic", "unknown"):
        assert select_backend_for_shape(shape) in ("femmt", "femm", "none")


def test_fidelity_table_consistency():
    """When the chosen backend matches the shape's preferred one, fidelity
    must be 'high'. Otherwise 'approx'. 'none' iff no backend at all."""
    if not is_femmt_available() and not is_femm_available():
        for shape in ("toroid", "ee", "etd"):
            assert backend_fidelity(shape, "none") == "none"
        return

    # toroide: FEMM is high-fidelity, FEMMT is approx
    assert backend_fidelity("toroid", "femm") == "high"
    assert backend_fidelity("toroid", "femmt") == "approx"

    # bobbin: FEMMT is high-fidelity, FEMM is approx
    for shape in ("ee", "etd", "pq"):
        assert backend_fidelity(shape, "femmt") == "high"
        assert backend_fidelity(shape, "femm") == "approx"


def test_dispatcher_prefers_femm_for_toroide_when_available(monkeypatch):
    """If both backends are available, toroide should pick FEMM (high)."""
    monkeypatch.delenv("PFC_FEA_BACKEND", raising=False)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femm_available",
                        lambda: True)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femmt_available",
                        lambda: True)
    assert select_backend_for_shape("toroid") == "femm"


def test_dispatcher_prefers_femmt_for_bobbin_when_available(monkeypatch):
    monkeypatch.delenv("PFC_FEA_BACKEND", raising=False)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femm_available",
                        lambda: True)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femmt_available",
                        lambda: True)
    for shape in ("ee", "etd", "pq"):
        assert select_backend_for_shape(shape) == "femmt"


def test_dispatcher_falls_back_when_preferred_missing(monkeypatch):
    """Toroide with FEMM missing should fall back to FEMMT."""
    monkeypatch.delenv("PFC_FEA_BACKEND", raising=False)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femm_available",
                        lambda: False)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femmt_available",
                        lambda: True)
    assert select_backend_for_shape("toroid") == "femmt"

    # And bobbin with FEMMT missing falls back to FEMM
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femm_available",
                        lambda: True)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femmt_available",
                        lambda: False)
    for shape in ("ee", "etd", "pq"):
        assert select_backend_for_shape(shape) == "femm"


def test_dispatcher_returns_none_when_nothing_available(monkeypatch):
    monkeypatch.delenv("PFC_FEA_BACKEND", raising=False)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femm_available",
                        lambda: False)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femmt_available",
                        lambda: False)
    for shape in ("toroid", "ee", "etd", "pq", "generic"):
        assert select_backend_for_shape(shape) == "none"


def test_env_var_forces_backend(monkeypatch):
    """`PFC_FEA_BACKEND` overrides the per-shape preference."""
    monkeypatch.setenv("PFC_FEA_BACKEND", "femmt")
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femm_available",
                        lambda: True)
    monkeypatch.setattr("pfc_inductor.fea.probe.is_femmt_available",
                        lambda: True)
    # Even toroide gets FEMMT when forced
    assert select_backend_for_shape("toroid") == "femmt"

    monkeypatch.setenv("PFC_FEA_BACKEND", "femm")
    # Even EE gets FEMM when forced
    assert select_backend_for_shape("ee") == "femm"
