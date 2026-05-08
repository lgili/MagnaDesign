"""A snapshot of one design for side-by-side comparison."""

from __future__ import annotations

from dataclasses import dataclass

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire


@dataclass
class CompareSlot:
    spec: Spec
    core: Core
    wire: Wire
    material: Material
    result: DesignResult

    @property
    def label(self) -> str:
        return f"{self.material.name} + {self.core.part_number} + {self.wire.id}"

    @property
    def short_label(self) -> str:
        return f"{self.core.part_number}\n{self.material.name} / {self.wire.id}"
