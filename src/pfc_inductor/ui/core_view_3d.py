"""3D viewer widget for the selected core + winding (PyVista/pyvistaqt)."""
from __future__ import annotations
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QCheckBox,
)

from pfc_inductor.models import Core, Wire, Material
from pfc_inductor.visual import (
    make_core_mesh, make_winding_mesh, make_bobbin_mesh,
)


def _can_use_3d() -> bool:
    """VTK + Qt OpenGL crash hard under offscreen platforms — disable then."""
    plat = os.environ.get("QT_QPA_PLATFORM", "").lower()
    if plat in ("offscreen", "minimal", "vnc"):
        return False
    return True


# Material colours (RGB hex). Powder cores: dusty silver-grey.
# Ferrites: dark anthracite. Nanocrystalline: bluish steel.
_COLORS = {
    "powder": "#b9a98c",         # warm sandy iron
    "ferrite": "#3a3838",
    "nanocrystalline": "#5d6c7a",
    "amorphous": "#6e7178",
    "silicon-steel": "#a4a39e",
    "default": "#888888",
}
_COPPER = "#c98a4b"
_COPPER_BRIGHT = "#ff9a5a"


class CoreView3D(QWidget):
    """Embedded VTK render of core + helical winding."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        self.lbl_info = QLabel("—")
        self.lbl_info.setStyleSheet("color: #555; font-size: 11px;")
        self.btn_reset = QPushButton("Reset câmera")
        self.btn_reset.setMaximumWidth(120)
        self.btn_reset.clicked.connect(self._reset_camera)
        self.chk_winding = QCheckBox("Mostrar bobinagem")
        self.chk_winding.setChecked(True)
        self.chk_winding.toggled.connect(lambda _v: self.refresh())
        self.chk_rotate = QCheckBox("Girar automático")
        self.chk_rotate.setChecked(False)
        self.chk_rotate.toggled.connect(self._toggle_autorotate)
        toolbar.addWidget(self.lbl_info, 1)
        toolbar.addWidget(self.chk_winding)
        toolbar.addWidget(self.chk_rotate)
        toolbar.addWidget(self.btn_reset)
        outer.addLayout(toolbar)

        self.plotter = None
        self._fallback = None
        if _can_use_3d():
            try:
                from pyvistaqt import QtInteractor
                self.plotter = QtInteractor(self)
                outer.addWidget(self.plotter.interactor, 1)
                self._setup_renderer()
                # Failure to draw the placeholder text must not kill the
                # whole widget — at worst the user sees an empty viewport
                # until they pick a core.
                try:
                    self._show_placeholder()
                except Exception:
                    pass
            except Exception as e:
                self.plotter = None
                self._fallback = QLabel(
                    f"Visualizador 3D indisponível: {type(e).__name__}: {e}"
                )
        else:
            self._fallback = QLabel(
                "Visualizador 3D indisponível em modo offscreen."
            )
        if self._fallback is not None:
            self._fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._fallback.setStyleSheet("color: #888; font-size: 12px;")
            outer.addWidget(self._fallback, 1)
            for w in (self.btn_reset, self.chk_winding, self.chk_rotate):
                w.setEnabled(False)

        self._current: Optional[tuple[Core, Wire, int, Material]] = None
        self._rotate_timer = QTimer(self)
        self._rotate_timer.timeout.connect(self._tick_rotation)

    def _setup_renderer(self):
        self.plotter.set_background("#f0f3f7", top="#cdd6e0")
        self.plotter.enable_anti_aliasing("ssaa")
        try:
            self.plotter.enable_lightkit()
        except Exception:
            pass
        self.plotter.show_axes()

    def _show_placeholder(self):
        self.plotter.clear()
        self.plotter.add_text(
            "Selecione um núcleo para visualizar em 3D.",
            position="upper_edge", color="#666666", font_size=10,
        )

    def update_view(self, core: Core, wire: Wire, N_turns: int, material: Material):
        """Rebuild the scene for the given selection."""
        self._current = (core, wire, N_turns, material)
        if self.plotter is not None:
            self.refresh()

    def refresh(self):
        if self.plotter is None:
            return
        if self._current is None:
            self._show_placeholder()
            return
        core, wire, N_turns, material = self._current
        self.plotter.clear()
        try:
            mb, kind, info = make_core_mesh(core)
            wnd = make_winding_mesh(core, wire, N_turns, info)
            # We don't render the plastic bobbin: the multi-layer
            # winding alone is the visual focus, and a translucent
            # bobbin shell ends up occluding the top of the winding
            # at typical camera angles. Generation kept for export.
            bobbin = None
        except Exception as e:
            self.plotter.add_text(
                f"Erro ao gerar mesh:\n{e}",
                position="upper_edge", color="#a01818", font_size=10,
            )
            return

        core_color = _COLORS.get(material.type, _COLORS["default"])
        # Closed-shell shapes get slight translucency so the bobbin /
        # winding stays visible inside.
        is_closed_shell = kind in ("ee", "etd", "pq")
        # Material-specific PBR-like parameters: silicon-steel reads as
        # brushed metal, ferrite as anthracite gloss, powder as matte
        # composite. ``pbr=True`` gives a much more believable read on
        # surfaces with curvature.
        if material.type == "silicon-steel":
            core_kwargs = dict(metallic=0.65, roughness=0.45,
                               specular=0.6, specular_power=20)
        elif material.type == "ferrite":
            core_kwargs = dict(metallic=0.05, roughness=0.40,
                               specular=0.5, specular_power=18)
        elif material.type == "amorphous":
            core_kwargs = dict(metallic=0.7, roughness=0.30,
                               specular=0.7, specular_power=25)
        else:  # powder, composite, default
            core_kwargs = dict(metallic=0.05, roughness=0.65,
                               specular=0.20, specular_power=10)
        opacity = 0.62 if is_closed_shell else 1.0
        for block in mb:
            if block is None:
                continue
            self.plotter.add_mesh(
                block,
                color=core_color,
                smooth_shading=True,
                ambient=0.20, diffuse=0.85,
                opacity=opacity,
                pbr=False,
                **core_kwargs,
            )

        # Plastic bobbin (off-white nylon) — only for bobbin shapes.
        if bobbin is not None and self.chk_winding.isChecked():
            for blk in bobbin:
                if blk is None:
                    continue
                self.plotter.add_mesh(
                    blk,
                    color="#e8e2d0",   # warm ivory nylon
                    smooth_shading=True,
                    ambient=0.30, diffuse=0.80,
                    specular=0.20, specular_power=12,
                    metallic=0.0, roughness=0.7,
                    pbr=False,
                )

        if wnd is not None and self.chk_winding.isChecked():
            self.plotter.add_mesh(
                wnd,
                color=_COPPER,
                smooth_shading=True,
                ambient=0.22, diffuse=0.55,
                specular=0.95, specular_power=40,
                metallic=0.85, roughness=0.18,
                pbr=False,
            )

        info_str = self._format_info(core, kind, info, N_turns)
        self.lbl_info.setText(info_str)
        self.plotter.reset_camera()
        # Per-shape camera defaults for best framing.
        if kind == "toroid":
            self.plotter.camera.azimuth = 30
            self.plotter.camera.elevation = 22
        else:
            self.plotter.camera.azimuth = 25
            self.plotter.camera.elevation = 8
        self.plotter.render()

    def _format_info(self, core: Core, kind: str, info: dict, N: int) -> str:
        if kind == "toroid":
            return (f"Toroide • OD={info.get('OD_mm', 0):.1f} ID={info.get('ID_mm', 0):.1f} "
                    f"HT={info.get('HT_mm', 0):.1f} mm • N={N}")
        if kind in ("ee", "etd", "pq"):
            return (f"{kind.upper()} • W={info.get('W', 0):.1f} H={info.get('H', 0):.1f} "
                    f"D={info.get('D', 0):.1f} mm • N={N}")
        return f"Forma genérica • Ve={core.Ve_mm3/1000:.1f} cm³ • N={N}"

    def _reset_camera(self):
        if self.plotter is None:
            return
        self.plotter.reset_camera()
        self.plotter.camera.azimuth = 30
        self.plotter.camera.elevation = 18
        self.plotter.render()

    def _toggle_autorotate(self, on: bool):
        if self.plotter is None:
            return
        if on:
            self._rotate_timer.start(40)
        else:
            self._rotate_timer.stop()

    def _tick_rotation(self):
        if self.plotter is None:
            self._rotate_timer.stop()
            return
        try:
            self.plotter.camera.azimuth += 0.6
            self.plotter.render()
        except Exception:
            self._rotate_timer.stop()

    def closeEvent(self, e):
        try:
            self._rotate_timer.stop()
            if self.plotter is not None:
                self.plotter.close()
        except Exception:
            pass
        super().closeEvent(e)
