"""Visualização 3D card — embeds an existing :class:`CoreView3D` widget.

The card itself only frames the viewer; chrome controls (orientation
cube, view chips, side toolbar, bottom action bar) come from the
``refactor-3d-viewer-controls`` change.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.core_view_3d import CoreView3D
from pfc_inductor.ui.widgets import Card


class _Viz3DBody(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._viewer = CoreView3D(parent=self)
        v.addWidget(self._viewer, 1)

    @property
    def viewer(self) -> CoreView3D:
        return self._viewer

    def update_from_design(self, result: DesignResult, spec: Spec,
                           core: Core, wire: Wire,
                           material: Material) -> None:
        self._viewer.update_view(core, wire, result.N_turns, material)

    def clear(self) -> None:
        # Resetting to placeholder when there's no design yet.
        self._viewer._show_placeholder() if self._viewer.plotter is not None else None


class Viz3DCard(Card):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        body = _Viz3DBody()
        super().__init__("Visualização 3D", body, parent=parent)
        self._vbody = body
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    @property
    def viewer(self) -> CoreView3D:
        return self._vbody.viewer

    def update_from_design(self, *args, **kwargs) -> None:
        self._vbody.update_from_design(*args, **kwargs)

    def clear(self) -> None:
        self._vbody.clear()
