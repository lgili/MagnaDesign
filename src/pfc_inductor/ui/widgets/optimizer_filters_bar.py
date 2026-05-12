"""Shared filter bar for the simple + cascade optimizers.

Three multi-select chips (Materials / Cores / Wires) and one
objective combo. Defaults are wide-open: empty chip selection
means "include every catalogue item the topology allows", so the
engineer can run a sweep without configuring anything.

Why this exists
---------------

Both optimizer surfaces previously offered different — and
narrower — filters:

- The simple optimizer had a single material dropdown ("(sweep
  all)" or one material) and no core / wire filter at all.
- The cascade had no UI filter; it always swept the full
  topology-eligible catalogue.

Engineers who already know which materials they can buy / which
cores fit their geometry need to *constrain* the sweep so the
ranking reflects realistic options. This bar gives them that
control without forcing the more casual user to learn it: the
default is still "sweep everything".

Public API
----------

- :meth:`set_catalogs` — bind the (filtered) catalogue from the
  host page after each ``set_inputs`` round.
- :meth:`selected_materials` / :meth:`selected_cores` /
  :meth:`selected_wires` — ``list[Material|Core|Wire]`` of the
  user's choice. Returns the *full* catalogue when the user
  selected nothing (wildcard).
- :meth:`objective` — current objective key, one of
  :data:`OBJECTIVES` keys.
- Signal :attr:`filters_changed` — fires on any chip change.
- Signal :attr:`objective_changed` — fires when the combo
  changes; payload is the new key.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, Material, Wire
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets.multi_select_chip import MultiSelectChip

# (key, label, hint) — keys must match ``pfc_inductor.optimize.sweep.rank``
# so the simple optimizer can pass the key straight through, and they
# also drive the cascade's display-time re-rank.
OBJECTIVES: tuple[tuple[str, str, str], ...] = (
    (
        "loss",
        "Lowest total loss",
        "Sort by P_total (W). Most engineers default here when thermals dominate.",
    ),
    (
        "volume",
        "Smallest volume",
        "Sort by core volume (cm³). Pick when board area / cost of magnetics dominates.",
    ),
    (
        "temp",
        "Lowest temperature",
        "Sort by hot-spot temperature (°C). Useful when ambient is high or cooling is poor.",
    ),
    ("cost", "Lowest cost", "Sort by total BOM cost (USD). Requires curated cores with cost data."),
    (
        "score",
        "Score (60 % loss + 40 % volume)",
        "Balanced 60/40 weighting — losses still dominate but volume breaks ties.",
    ),
    (
        "score_with_cost",
        "Score 40/30/30 (loss / vol / cost)",
        "Three-way balanced weighting — picks economical, compact, "
        "efficient designs in equal measure.",
    ),
)


class OptimizerFiltersBar(QFrame):
    """Filter row mounted at the top of an optimizer surface."""

    filters_changed = Signal()
    objective_changed = Signal(str)
    weights_changed = Signal()
    """Fires when any of the three score-weight sliders changes.

    The host listens to this in addition to ``objective_changed`` to
    re-rank the visible table without re-running the sweep — score
    weights live on top of the cached ``self._results``.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("OptimizerFiltersBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(self._qss())

        # Cached catalogues so we can resolve chip ids → objects when
        # the host calls ``selected_*``.
        self._materials: dict[str, Material] = {}
        self._cores: dict[str, Core] = {}
        self._wires: dict[str, Wire] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # ---- Row 1: chips --------------------------------------------
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)

        self.chip_materials = self._labelled_chip(
            chip_row,
            "Materials:",
            "materials",
        )
        self.chip_cores = self._labelled_chip(
            chip_row,
            "Cores:",
            "cores",
        )
        self.chip_wires = self._labelled_chip(
            chip_row,
            "Wires:",
            "wires",
        )
        chip_row.addStretch(1)

        for chip in (self.chip_materials, self.chip_cores, self.chip_wires):
            chip.selection_changed.connect(
                lambda _ids: self.filters_changed.emit(),
            )

        outer.addLayout(chip_row)

        # ---- Row 2: objective combo ----------------------------------
        obj_row = QHBoxLayout()
        obj_row.setSpacing(8)

        obj_label = QLabel("Optimize for:")
        obj_label.setProperty("role", "muted")
        obj_row.addWidget(obj_label)

        self.cmb_objective = QComboBox()
        self.cmb_objective.setMinimumWidth(280)
        for key, label, hint in OBJECTIVES:
            self.cmb_objective.addItem(label, key)
            # ``setItemData(role=Qt.ToolTipRole)`` adds per-item
            # tooltips so users can hover each option without
            # scanning the docs.
            idx = self.cmb_objective.count() - 1
            self.cmb_objective.setItemData(idx, hint, Qt.ItemDataRole.ToolTipRole)
        self.cmb_objective.currentIndexChanged.connect(self._on_objective_changed)
        obj_row.addWidget(self.cmb_objective)

        obj_row.addStretch(1)
        outer.addLayout(obj_row)

        # ---- Row 3: weight sliders (only visible for ``score`` keys)
        # The composite score combines normalised loss + volume +
        # (optionally) cost. Hardcoding the weights (60/40 default,
        # 40/30/30 with cost) is fine for the canonical case but
        # experienced engineers want to nudge the balance — "I care
        # 70 % about loss because this is a continuous-duty inductor"
        # / "I care more about cost because the BOM is the bottleneck".
        # Three sliders, one per axis, summed-normalized so the user
        # can drag freely without thinking about totals.
        from PySide6.QtWidgets import QSlider

        self._weights_row = QHBoxLayout()
        self._weights_row.setSpacing(8)
        self._weights_label = QLabel("Weights:")
        self._weights_label.setProperty("role", "muted")
        self._weights_row.addWidget(self._weights_label)

        def _make_slider(label_text: str, initial: int) -> tuple[QLabel, QSlider, QLabel]:
            lbl = QLabel(label_text)
            lbl.setProperty("role", "muted")
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(initial)
            sl.setFixedWidth(120)
            sl.setToolTip(
                f"{label_text} weight in the composite score. "
                "Drag to adjust without re-running the sweep."
            )
            val = QLabel(f"{initial}%")
            val.setFixedWidth(36)
            val.setProperty("role", "muted")
            sl.valueChanged.connect(lambda v: val.setText(f"{v}%"))
            sl.valueChanged.connect(lambda _v: self.weights_changed.emit())
            return lbl, sl, val

        self._lbl_w_loss, self.sl_w_loss, self._val_w_loss = _make_slider("Loss", 60)
        self._lbl_w_vol, self.sl_w_vol, self._val_w_vol = _make_slider("Volume", 40)
        self._lbl_w_cost, self.sl_w_cost, self._val_w_cost = _make_slider("Cost", 0)
        for w in (
            self._lbl_w_loss,
            self.sl_w_loss,
            self._val_w_loss,
            self._lbl_w_vol,
            self.sl_w_vol,
            self._val_w_vol,
            self._lbl_w_cost,
            self.sl_w_cost,
            self._val_w_cost,
        ):
            self._weights_row.addWidget(w)
        self._weights_row.addStretch(1)
        outer.addLayout(self._weights_row)
        # Initial visibility — defaults to "Loss" objective so weights
        # are hidden until the user picks a score variant.
        self._sync_weights_row_visibility()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_catalogs(
        self,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
    ) -> None:
        """Bind the topology-filtered catalogue. Empty selection ==
        wildcard — the chip labels read "All N {kind}".
        """
        self._materials = {m.id: m for m in materials}
        self._cores = {c.id: c for c in cores}
        self._wires = {w.id: w for w in wires}

        self.chip_materials.set_items(
            [(m.id, _material_label(m), _material_tooltip(m)) for m in materials],
        )
        self.chip_cores.set_items(
            [(c.id, _core_label(c), _core_tooltip(c)) for c in cores],
        )
        self.chip_wires.set_items(
            [(w.id, _wire_label(w), _wire_tooltip(w)) for w in wires],
        )

    def selected_materials(self) -> list[Material]:
        """Resolve the chip selection back to ``Material`` objects.
        Returns the full catalogue when the chip is wildcard."""
        if self.chip_materials.is_all():
            return list(self._materials.values())
        return [self._materials[i] for i in self.chip_materials.selected() if i in self._materials]

    def selected_cores(self) -> list[Core]:
        if self.chip_cores.is_all():
            return list(self._cores.values())
        return [self._cores[i] for i in self.chip_cores.selected() if i in self._cores]

    def selected_wires(self) -> list[Wire]:
        if self.chip_wires.is_all():
            return list(self._wires.values())
        return [self._wires[i] for i in self.chip_wires.selected() if i in self._wires]

    def objective(self) -> str:
        return str(self.cmb_objective.currentData() or "loss")

    def set_objective(self, key: str) -> None:
        for i in range(self.cmb_objective.count()):
            if self.cmb_objective.itemData(i) == key:
                self.cmb_objective.setCurrentIndex(i)
                return

    # ------------------------------------------------------------------
    def _labelled_chip(
        self,
        parent_layout: QHBoxLayout,
        caption: str,
        plural: str,
    ) -> MultiSelectChip:
        cap = QLabel(caption)
        cap.setProperty("role", "muted")
        parent_layout.addWidget(cap)
        chip = MultiSelectChip(label_plural=plural)
        parent_layout.addWidget(chip)
        return chip

    def _on_objective_changed(self, _idx: int) -> None:
        # Toggle visibility of the weights row before emitting so the
        # GUI repaints in a single tick.
        self._sync_weights_row_visibility()
        self.objective_changed.emit(self.objective())

    def _sync_weights_row_visibility(self) -> None:
        """Hide the weight sliders unless the user picked a score
        objective — for ``loss`` / ``volume`` / ``temp`` / ``cost``
        the sliders are noise (their values don't affect anything).
        """
        is_score = self.objective() in ("score", "score_with_cost")
        # Cost slider only matters for the cost-aware variant.
        show_cost = self.objective() == "score_with_cost"
        for w in (
            self._weights_label,
            self._lbl_w_loss,
            self.sl_w_loss,
            self._val_w_loss,
            self._lbl_w_vol,
            self.sl_w_vol,
            self._val_w_vol,
        ):
            w.setVisible(is_score)
        for w in (self._lbl_w_cost, self.sl_w_cost, self._val_w_cost):
            w.setVisible(show_cost)

    def weights(self) -> tuple[float, float, float]:
        """Return ``(w_loss, w_vol, w_cost)`` as 0-100 ints (the host
        is expected to normalize). The cost weight is 0 for the
        plain ``score`` objective."""
        if self.objective() == "score_with_cost":
            return (
                float(self.sl_w_loss.value()),
                float(self.sl_w_vol.value()),
                float(self.sl_w_cost.value()),
            )
        return (
            float(self.sl_w_loss.value()),
            float(self.sl_w_vol.value()),
            0.0,
        )

    @staticmethod
    def _qss() -> str:
        p = get_theme().palette
        r = get_theme().radius
        return (
            f"QFrame#OptimizerFiltersBar {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"  border-radius: {r.card}px;"
            f"}}"
        )


# ---------------------------------------------------------------------------
# Label / tooltip helpers — kept module-level so they're easy to unit-test
# and re-use from other places that render catalogue rows.
# ---------------------------------------------------------------------------
def _material_label(m: Material) -> str:
    """Vendor + name; shorten if vendor is repeated in the name."""
    vendor = (m.vendor or "").strip()
    name = (m.name or "").strip()
    if vendor and not name.lower().startswith(vendor.lower()):
        return f"{vendor} — {name}"
    return name or m.id


def _material_tooltip(m: Material) -> str:
    parts = [f"id: {m.id}"]
    if getattr(m, "type", None):
        parts.append(f"type: {m.type}")
    if getattr(m, "mu_initial", None):
        parts.append(f"μᵢ ≈ {m.mu_initial:.0f}")
    return "  ·  ".join(parts)


def _core_label(c: Core) -> str:
    pn = (c.part_number or c.id).strip()
    fam = (getattr(c, "family", "") or "").strip()
    if fam and fam not in pn:
        return f"{pn} ({fam})"
    return pn


def _core_tooltip(c: Core) -> str:
    parts = [f"id: {c.id}"]
    OD_mm = getattr(c, "OD_mm", None)
    if OD_mm:
        parts.append(f"OD ≈ {OD_mm:.1f} mm")
    Ae = getattr(c, "Ae_mm2", None)
    if Ae:
        parts.append(f"Ae ≈ {Ae:.1f} mm²")
    return "  ·  ".join(parts)


def _wire_label(w: Wire) -> str:
    return getattr(w, "id", str(w))


def _wire_tooltip(w: Wire) -> str:
    parts = [f"id: {w.id}"]
    kind = getattr(w, "kind", None)
    if kind:
        parts.append(f"kind: {kind}")
    return "  ·  ".join(parts)
