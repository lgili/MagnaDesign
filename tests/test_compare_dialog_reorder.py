"""Drag-and-drop reordering tests for ``CompareDialog``.

We don't simulate Qt's drag-and-drop event chain — wiring up
``QDrag`` + synthetic ``QDropEvent`` from a unit test is brittle and
adds nothing over driving ``_on_reorder`` directly with the
target index, which is what the drop event ultimately produces.

The tests check the splice math (the only place a regression can
silently shuffle the user's data) and the auto-REF promotion that
the user explicitly asked for: dragging any column to position 0
makes it the new reference, automatically.
"""

from __future__ import annotations

import os

import pytest

# Force offscreen Qt so the test runs headless on CI / dev machines.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pfc_inductor.compare.slot import CompareSlot
from pfc_inductor.data_loader import (
    find_material,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.design import design
from pfc_inductor.models import Spec
from pfc_inductor.ui.compare_dialog import CompareDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture(scope="module")
def four_slots():
    """Four distinct slots — two materials × two wires — so REF
    promotion produces visibly different metric numbers, which is
    what the user actually cares about."""
    mats, cores, wires = load_materials(), load_cores(), load_wires()
    spec = Spec(
        Vin_min_Vrms=85.0,
        Vin_max_Vrms=265.0,
        Vin_nom_Vrms=220.0,
        Vout_V=400.0,
        Pout_W=800.0,
        eta=0.97,
        f_sw_kHz=65.0,
        ripple_pct=30.0,
    )
    mat_a = find_material(mats, "magnetics-60_highflux")
    mat_b = find_material(mats, "magnetics-60_xflux")
    core = next(
        c
        for c in cores
        if c.default_material_id == "magnetics-60_highflux" and 40000 < c.Ve_mm3 < 100000
    )
    w14 = next(w for w in wires if w.id == "AWG14")
    w16 = next(w for w in wires if w.id == "AWG16")
    combos = [(mat_a, w14), (mat_a, w16), (mat_b, w14), (mat_b, w16)]
    return [
        CompareSlot(
            spec=spec,
            core=core,
            wire=w,
            material=m,
            result=design(spec, core, w, m),
        )
        for (m, w) in combos
    ]


def _populated_dialog(qapp, slots) -> CompareDialog:
    dlg = CompareDialog()
    for s in slots:
        dlg._slots.append(s)
    dlg._refresh_columns()
    return dlg


def _slot_ids(dlg: CompareDialog) -> list[str]:
    return [f"{s.material.id}|{s.wire.id}" for s in dlg._slots]


def test_drop_at_index_zero_promotes_to_ref(qapp, four_slots):
    """Drag the third column to index 0 — it becomes the new REF.
    Verifies the user's stated motivation for this feature."""
    dlg = _populated_dialog(qapp, four_slots)
    initial_ids = _slot_ids(dlg)
    third_column = dlg._columns[2]
    third_id = f"{third_column.slot.material.id}|{third_column.slot.wire.id}"

    dlg._on_reorder(third_column, target_idx=0)
    new_ids = _slot_ids(dlg)

    # The third slot is now first, the others kept their relative order.
    assert new_ids[0] == third_id
    expected_remainder = [i for i in initial_ids if i != third_id]
    assert new_ids[1:] == expected_remainder
    # Leftmost column is the new REF.
    assert dlg._columns[0]._is_leftmost is True
    assert dlg._columns[1]._is_leftmost is False


def test_drop_at_end(qapp, four_slots):
    """Drag the first slot past the last column — it lands at the end."""
    dlg = _populated_dialog(qapp, four_slots)
    initial_ids = _slot_ids(dlg)
    first_column = dlg._columns[0]
    first_id = initial_ids[0]

    # target_idx == len(slots) means "after the last column"
    dlg._on_reorder(first_column, target_idx=len(four_slots))
    new_ids = _slot_ids(dlg)

    assert new_ids[-1] == first_id
    assert new_ids[:-1] == initial_ids[1:]
    # New REF is the slot that was previously at index 1.
    assert new_ids[0] == initial_ids[1]


def test_drop_at_same_position_is_noop(qapp, four_slots):
    """Dropping a column in the gap immediately before or after
    itself shouldn't shuffle ``_slots`` — avoids a wasteful refresh
    + flicker the user perceives as a glitch."""
    dlg = _populated_dialog(qapp, four_slots)
    initial_ids = _slot_ids(dlg)
    second_column = dlg._columns[1]

    # Same-gap drops: target_idx == src_idx (left edge of self) or
    # src_idx + 1 (right edge of self). Both are no-ops.
    dlg._on_reorder(second_column, target_idx=1)
    assert _slot_ids(dlg) == initial_ids
    dlg._on_reorder(second_column, target_idx=2)
    assert _slot_ids(dlg) == initial_ids


def test_drop_middle_slot_to_middle(qapp, four_slots):
    """Move the last column to index 1 — middle reorder, not REF."""
    dlg = _populated_dialog(qapp, four_slots)
    initial_ids = _slot_ids(dlg)
    last_column = dlg._columns[-1]
    last_id = initial_ids[-1]

    dlg._on_reorder(last_column, target_idx=1)
    new_ids = _slot_ids(dlg)

    # REF unchanged.
    assert new_ids[0] == initial_ids[0]
    # Last slot is now at index 1.
    assert new_ids[1] == last_id
    # The originally-second/third slots shifted right by one.
    assert new_ids[2] == initial_ids[1]
    assert new_ids[3] == initial_ids[2]


def test_reorder_unknown_source_is_safe(qapp, four_slots):
    """If a stale column reference (no longer in ``_slots``) is
    passed, the reorder must be a no-op — not crash. Catches the
    edge case where a column got removed mid-drag."""
    dlg = _populated_dialog(qapp, four_slots)
    initial_ids = _slot_ids(dlg)
    stranded_column = dlg._columns[0]
    # Detach the slot.
    dlg._slots.remove(stranded_column.slot)
    # The detached column has nothing to reorder — must be a no-op.
    dlg._on_reorder(stranded_column, target_idx=2)
    # _slots reflects only the remaining 3 (the detached one didn't
    # come back in) and order is preserved.
    assert _slot_ids(dlg) == initial_ids[1:]
