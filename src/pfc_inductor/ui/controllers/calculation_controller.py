"""Calculation controller.

Owns the "read inputs → look up catalog → call ``design()``" pipeline
that ``MainWindow`` used to inline. Pulling it out lets us:

- Unit-test the input-translation logic without ``QApplication``.
- Centralise the Pydantic ``ValidationError`` → :class:`SpecValidationError`
  conversion (was previously open-coded in every handler).
- Give the host (``MainWindow``) a single :class:`Protocol` to satisfy
  for the spec panel, instead of importing the concrete class.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from pfc_inductor.data_loader import find_material
from pfc_inductor.design import design
from pfc_inductor.errors import (
    CatalogError,
    SpecValidationError,
)
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


class SpecPanelLike(Protocol):
    """Structural contract the controller needs from the spec panel.

    Defining it as a ``Protocol`` keeps the controller decoupled from
    the Qt widget — any object satisfying these four methods works,
    including in-process test doubles.
    """

    def get_spec(self) -> Spec: ...
    def get_core_id(self) -> str: ...
    def get_wire_id(self) -> str: ...
    def get_material_id(self) -> str: ...


@dataclass(frozen=True)
class CalculationInputs:
    """The four objects the engine needs to compute a design."""
    spec: Spec
    core: Core
    wire: Wire
    material: Material


class CalculationController:
    """Stateless-ish glue between the spec panel and ``design.engine``.

    Holds references to the in-memory catalogs (materials/cores/wires)
    so the host doesn't have to thread them through every call.
    Catalogs are mutated in place by ``MainWindow._reload_databases``;
    keeping a reference (not a copy) means we always see the latest.
    """

    def __init__(
        self,
        spec_panel: SpecPanelLike,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
    ) -> None:
        self._spec_panel = spec_panel
        self._materials = materials
        self._cores = cores
        self._wires = wires

    # ------------------------------------------------------------------
    # Catalog accessors (used by the host for dialog construction)
    # ------------------------------------------------------------------
    @property
    def materials(self) -> list[Material]:
        return self._materials

    @property
    def cores(self) -> list[Core]:
        return self._cores

    @property
    def wires(self) -> list[Wire]:
        return self._wires

    def replace_catalogs(
        self,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
    ) -> None:
        """Swap the catalog references after a DB reload. The host
        keeps its own references too — both must stay in sync."""
        self._materials = materials
        self._cores = cores
        self._wires = wires

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def find_core(self, core_id: str) -> Core:
        return _find_or_raise(
            self._cores, core_id,
            label="Núcleo",
            hint="Atualize o catálogo (toolbar → Atualizar) ou edite a base de dados.",
        )

    def find_wire(self, wire_id: str) -> Wire:
        return _find_or_raise(
            self._wires, wire_id,
            label="Fio",
            hint="Atualize o catálogo (toolbar → Atualizar) ou edite a base de dados.",
        )

    def find_material(self, material_id: str) -> Material:
        try:
            return find_material(self._materials, material_id)
        except (KeyError, ValueError) as exc:
            raise CatalogError(
                f"Material '{material_id}' não está no catálogo."
            ) from exc

    # ------------------------------------------------------------------
    # Pipelines
    # ------------------------------------------------------------------
    def collect_inputs(self) -> CalculationInputs:
        """Read spec + selections from the panel and resolve catalog
        ids. Translates Pydantic ``ValidationError`` into
        :class:`SpecValidationError` so the UI catches a single base
        type."""
        from pydantic import ValidationError
        try:
            spec = self._spec_panel.get_spec()
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(p) for p in first.get("loc", ())) or "?"
            msg = first.get("msg", "valor inválido")
            raise SpecValidationError(
                f"Spec inválido em '{field}': {msg}",
                hint="Ajuste o campo na coluna esquerda e tente novamente.",
            ) from exc
        except ValueError as exc:
            raise SpecValidationError(str(exc)) from exc

        return CalculationInputs(
            spec=spec,
            core=self.find_core(self._spec_panel.get_core_id()),
            wire=self.find_wire(self._spec_panel.get_wire_id()),
            material=self.find_material(self._spec_panel.get_material_id()),
        )

    def calculate(self) -> tuple[CalculationInputs, DesignResult]:
        """End-to-end recompute. Raises :class:`DesignError` only —
        any other exception is a real bug and propagates."""
        inputs = self.collect_inputs()
        result = design(inputs.spec, inputs.core, inputs.wire, inputs.material)
        return inputs, result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _find_or_raise(
    items: Iterable, item_id: str, *, label: str, hint: str | None = None,
):
    """Linear scan for ``.id == item_id``; raise :class:`CatalogError`
    if not found. Generic so it works for cores, wires, or anything
    else with an ``id`` attribute."""
    for it in items:
        if getattr(it, "id", None) == item_id:
            return it
    raise CatalogError(
        f"{label} '{item_id}' não está no catálogo carregado.", hint=hint,
    )


__all__ = [
    "CalculationController",
    "CalculationInputs",
    "SpecPanelLike",
]
