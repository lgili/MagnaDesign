"""Cascade band-aware re-ranking — engine helper tests."""
from __future__ import annotations

from dataclasses import replace

import pytest

from pfc_inductor.data_loader import (
    ensure_user_data,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design as run_design
from pfc_inductor.models import FswModulation, Spec
from pfc_inductor.optimize.cascade.band_aware import band_aware_rerank
from pfc_inductor.optimize.cascade.store import CandidateRow


@pytest.fixture(scope="module")
def catalogues():
    ensure_user_data()
    return load_materials(), load_cores(), load_wires()


@pytest.fixture(scope="module")
def banded_spec():
    """Boost-PFC with a 4–25 kHz VFD band."""
    return Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=10, ripple_pct=20, T_amb_C=40,
        fsw_modulation=FswModulation(
            fsw_min_kHz=4, fsw_max_kHz=25,
            profile="uniform", n_eval_points=3,
        ),
    )


@pytest.fixture(scope="module")
def candidate_rows(catalogues, banded_spec):
    """Two synthetic CandidateRow entries pointing at the same
    reference design — the rerank should pick the same triple
    twice but substitute band-worst-case losses."""
    mats, cores, wires = catalogues
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    nominal = run_design(banded_spec, core, wire, mat)
    base = CandidateRow(
        candidate_key=f"{core.id}|{mat.id}|{wire.id}|10|0",
        core_id=core.id, material_id=mat.id, wire_id=wire.id,
        N=int(nominal.N_turns), gap_mm=0.0,
        highest_tier=1, feasible_t0=True,
        loss_t1_W=float(nominal.losses.P_total_W),
        temp_t1_C=float(nominal.T_winding_C),
        cost_t1_USD=None,
    )
    # Second row: stale "magic" loss to confirm the rerank
    # actually substitutes the band-worst value.
    fake = replace(base, loss_t1_W=0.001, temp_t1_C=10.0)
    return [base, fake]


def test_band_aware_rerank_substitutes_worst_loss(
    catalogues, banded_spec, candidate_rows,
) -> None:
    """The fake row that claimed loss=0.001 W gets corrected to
    the actual band-worst loss after the rerank — engineering
    contract: the helper never hides regressions behind a
    stale store value."""
    mats, cores, wires = catalogues
    eligible = mats
    rows = band_aware_rerank(
        candidate_rows, banded_spec,
        cores_by_id={c.id: c for c in cores},
        wires_by_id={w.id: w for w in wires},
        materials_by_id={m.id: m for m in eligible},
    )
    # Both rows referenced the same design, so post-rerank both
    # should carry the same loss_t1_W (the band-worst value).
    assert len(rows) == 2
    assert rows[0].loss_t1_W is not None
    assert rows[1].loss_t1_W is not None
    assert rows[0].loss_t1_W == pytest.approx(
        rows[1].loss_t1_W, rel=1e-6,
    )
    # And it's strictly larger than the nominal-fsw value the
    # base row carried — the band-worst case is at the band
    # edges, not the centre.
    assert rows[0].loss_t1_W > candidate_rows[0].loss_t1_W * 0.9


def test_band_aware_rerank_skips_when_spec_has_no_band(
    catalogues, candidate_rows,
) -> None:
    """A spec without ``fsw_modulation`` returns the rows
    unchanged — no engine call, no allocation."""
    spec_no_band = Spec(
        topology="boost_ccm", Pout_W=600,
        Vin_min_Vrms=85, Vin_max_Vrms=265, Vout_V=400,
        f_sw_kHz=10, ripple_pct=20, T_amb_C=40,
    )
    mats, cores, wires = catalogues
    out = band_aware_rerank(
        candidate_rows, spec_no_band,
        cores_by_id={c.id: c for c in cores},
        wires_by_id={w.id: w for w in wires},
        materials_by_id={m.id: m for m in mats},
    )
    assert out == candidate_rows


def test_band_aware_rerank_handles_missing_catalog_entry(
    catalogues, banded_spec,
) -> None:
    """A row whose core_id isn't in the catalogue (catalogue
    churned between run + rerank) falls through unchanged
    rather than raising."""
    mats, _cores, wires = catalogues
    mystery_row = CandidateRow(
        candidate_key="mystery|x|y|0|0",
        core_id="not-in-catalogue", material_id="x", wire_id="y",
        N=10, gap_mm=0.0, highest_tier=1, feasible_t0=True,
        loss_t1_W=2.0, temp_t1_C=80.0,
    )
    out = band_aware_rerank(
        [mystery_row], banded_spec,
        cores_by_id={},  # empty — nothing matches
        wires_by_id={w.id: w for w in wires},
        materials_by_id={m.id: m for m in mats},
    )
    # Row returned unchanged.
    assert len(out) == 1
    assert out[0].loss_t1_W == 2.0
    assert out[0].core_id == "not-in-catalogue"


def test_band_aware_rerank_sorts_ascending_by_loss(
    catalogues, banded_spec,
) -> None:
    """Output is sorted ascending by post-rerank loss so
    callers can hand it straight to the UI."""
    mats, cores, wires = catalogues
    mat = next(m for m in mats if m.id == "magnetics-60_highflux")
    core = next(c for c in cores
                if c.id == "magnetics-c058777a2-60_highflux")
    wire = next(w for w in wires if w.id == "AWG14")
    rows = [
        CandidateRow(
            candidate_key=f"r{i}", core_id=core.id,
            material_id=mat.id, wire_id=wire.id,
            N=50 + i, gap_mm=0.0,
            highest_tier=1, feasible_t0=True,
            loss_t1_W=10.0 - i,  # arbitrary decreasing order
            temp_t1_C=80.0,
        )
        for i in range(3)
    ]
    out = band_aware_rerank(
        rows, banded_spec,
        cores_by_id={c.id: c for c in cores},
        wires_by_id={w.id: w for w in wires},
        materials_by_id={m.id: m for m in mats},
    )
    losses = [r.loss_t1_W for r in out]
    assert losses == sorted(losses), (
        "post-rerank rows must be sorted ascending by loss"
    )
