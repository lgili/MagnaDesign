"""3D viewer widget for the selected core + winding (PyVista/pyvistaqt).

The widget hosts a ``QtInteractor`` for the live 3D scene and mounts four
overlay HUD panels on top:

- :class:`ViewChips <pfc_inductor.ui.viewer3d.view_chips.ViewChips>` —
  top-left chip group for the canonical Frente / Cima / Lateral / Iso
  presets.
- :class:`OrientationCube
  <pfc_inductor.ui.viewer3d.orientation_cube.OrientationCube>` —
  top-right axis cube; clicking a face snaps to the matching view.
- :class:`SideToolbar <pfc_inductor.ui.viewer3d.side_toolbar.SideToolbar>` —
  vertical right-edge icon stack (fullscreen / screenshot / layers /
  section / measure / settings).
- :class:`BottomActions
  <pfc_inductor.ui.viewer3d.bottom_actions.BottomActions>` — bottom
  labelled actions (Explodir / Corte / Medidas / Exportar).

Overlays sit in a child ``QStackedLayout``-style raised position; mouse
events outside the overlay rectangles still fall through to the
``QtInteractor`` so the user can drag the scene normally.
"""
from __future__ import annotations
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFileDialog,
)

from pfc_inductor.models import Core, Wire, Material
from pfc_inductor.visual import (
    make_core_mesh, make_winding_mesh, make_bobbin_mesh,
    set_camera_to_view,
)
from pfc_inductor.ui.viewer3d import (
    ViewChips, OrientationCube, SideToolbar, BottomActions,
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
    """Embedded VTK render of core + helical winding + overlay HUD."""

    camera_changed = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

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

        # ---- overlays --------------------------------------------------
        self._build_overlays()
        # Wire a camera-change observer so the chips/cube can react.
        self._install_camera_observer()

        self._current: Optional[tuple[Core, Wire, int, Material]] = None
        self._rotate_timer = QTimer(self)
        self._rotate_timer.timeout.connect(self._tick_rotation)

        # Mesh tracking for layer toggles.
        self._actor_core: list = []
        self._actor_winding = None
        self._actor_bobbin: list = []
        self._layer_state = {"winding": True, "bobbin": False, "airgap": True}

        # Section / measure widgets reused across toggles.
        self._section_widget = None
        self._measure_widget = None

    # ==================================================================
    # Initial scene setup
    # ==================================================================
    def _setup_renderer(self):
        self.plotter.set_background("#f0f3f7", top="#cdd6e0")
        self.plotter.enable_anti_aliasing("ssaa")
        try:
            self.plotter.enable_lightkit()
        except Exception:
            pass
        self.plotter.show_axes()

    def _show_placeholder(self):
        if self.plotter is None:
            return
        self.plotter.clear()
        self.plotter.add_text(
            "Selecione um núcleo para visualizar em 3D.",
            position="upper_edge", color="#666666", font_size=10,
        )

    # ==================================================================
    # Overlays
    # ==================================================================
    def _build_overlays(self) -> None:
        """Create the four overlay panels and stack them on top of the
        QtInteractor. They're parented to ``self`` so they can be
        repositioned in :meth:`resizeEvent`."""
        host = self.plotter.interactor if self.plotter is not None else self

        self.chips = ViewChips(parent=self)
        self.chips.view_changed.connect(self.set_view)

        self.cube = OrientationCube(parent=self)
        self.cube.view_requested.connect(self.set_view)

        self.toolbar = SideToolbar(parent=self)
        self.toolbar.fullscreen_requested.connect(self._on_fullscreen)
        self.toolbar.screenshot_requested.connect(self.request_screenshot)
        self.toolbar.layers_requested.connect(self._on_layers_changed)
        self.toolbar.section_toggled.connect(self.request_section)
        self.toolbar.measure_toggled.connect(self.request_measure)
        self.toolbar.settings_requested.connect(lambda: None)  # reserved

        self.action_bar = BottomActions(parent=self)
        self.action_bar.section_toggled.connect(self._sync_section)
        self.action_bar.measure_toggled.connect(self._sync_measure)
        self.action_bar.explode_toggled.connect(self.request_explode)
        self.action_bar.export_requested.connect(self.request_export)

        for w in (self.chips, self.cube, self.toolbar, self.action_bar):
            w.raise_()
            w.show()

        # Initial placement so they appear before the first resize.
        self._reposition_overlays()

    def _reposition_overlays(self) -> None:
        if self.chips is None:
            return
        margin = 12

        # Compact mode: when the viewer is too small (e.g. inside the
        # dashboard's Visualização 3D card), hide the side toolbar and
        # bottom action bar so the chips + cube don't overlap them. The
        # full-bleed Mecânico page restores everything.
        compact = self.width() < 520 or self.height() < 360

        # Top-left: chips
        self.chips.adjustSize()
        self.chips.move(margin, margin)
        self.chips.show()

        # Top-right: cube — hide in *very* compact mode (too narrow even
        # for the chips group + cube side-by-side).
        very_compact = self.width() < 380
        self.cube.setVisible(not very_compact)
        if not very_compact:
            self.cube.move(self.width() - self.cube.width() - margin, margin)

        # Right side: vertical toolbar — only when not compact.
        self.toolbar.setVisible(not compact)
        if not compact:
            self.toolbar.adjustSize()
            self.toolbar.move(
                self.width() - self.toolbar.width() - margin,
                (self.height() - self.toolbar.height()) // 2,
            )

        # Bottom centre: action bar — only when not compact.
        self.action_bar.setVisible(not compact)
        if not compact:
            self.action_bar.adjustSize()
            self.action_bar.move(
                (self.width() - self.action_bar.width()) // 2,
                self.height() - self.action_bar.height() - margin,
            )

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition_overlays()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        # The widget's geometry isn't realised at construction; defer
        # one-shot reposition until after Qt finishes the layout pass.
        QTimer.singleShot(0, self._reposition_overlays)

    # ==================================================================
    # Camera observer
    # ==================================================================
    def _install_camera_observer(self) -> None:
        if self.plotter is None:
            return
        try:
            iren = self.plotter.iren
            iren.add_observer("EndInteractionEvent", self._emit_camera_changed)
        except Exception:
            pass

    def _emit_camera_changed(self, *_args) -> None:
        if self.plotter is None:
            return
        try:
            cam = self.plotter.camera
            payload = {
                "position": tuple(cam.position),
                "focal":    tuple(cam.focal_point),
                "up":       tuple(cam.up),
            }
        except Exception:
            return
        self.camera_changed.emit(payload)

    # ==================================================================
    # Public API: scene update
    # ==================================================================
    def update_view(self, core: Core, wire: Wire, N_turns: int,
                    material: Material):
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
        self._actor_core = []
        self._actor_winding = None
        self._actor_bobbin = []
        try:
            mb, kind, info = make_core_mesh(core)
            wnd = make_winding_mesh(core, wire, N_turns, info)
            bobbin = (
                make_bobbin_mesh(core, wire, N_turns, info)
                if self._layer_state.get("bobbin", False) else None
            )
        except Exception as e:
            self.plotter.add_text(
                f"Erro ao gerar mesh:\n{e}",
                position="upper_edge", color="#a01818", font_size=10,
            )
            return

        core_color = _COLORS.get(material.type, _COLORS["default"])
        is_closed_shell = kind in ("ee", "etd", "pq")
        if material.type == "silicon-steel":
            core_kwargs = dict(metallic=0.65, roughness=0.45,
                               specular=0.6, specular_power=20)
        elif material.type == "ferrite":
            core_kwargs = dict(metallic=0.05, roughness=0.40,
                               specular=0.5, specular_power=18)
        elif material.type == "amorphous":
            core_kwargs = dict(metallic=0.7, roughness=0.30,
                               specular=0.7, specular_power=25)
        else:
            core_kwargs = dict(metallic=0.05, roughness=0.65,
                               specular=0.20, specular_power=10)
        opacity = 0.62 if is_closed_shell else 1.0

        for block in mb:
            if block is None:
                continue
            actor = self.plotter.add_mesh(
                block,
                color=core_color,
                smooth_shading=True,
                ambient=0.20, diffuse=0.85,
                opacity=opacity,
                pbr=False,
                **core_kwargs,
            )
            self._actor_core.append(actor)

        if bobbin is not None and self._layer_state["bobbin"]:
            for blk in bobbin:
                if blk is None:
                    continue
                act = self.plotter.add_mesh(
                    blk,
                    color="#e8e2d0",
                    smooth_shading=True,
                    ambient=0.30, diffuse=0.80,
                    specular=0.20, specular_power=12,
                    metallic=0.0, roughness=0.7,
                    pbr=False,
                )
                self._actor_bobbin.append(act)

        if wnd is not None and self._layer_state["winding"]:
            self._actor_winding = self.plotter.add_mesh(
                wnd,
                color=_COPPER,
                smooth_shading=True,
                ambient=0.22, diffuse=0.55,
                specular=0.95, specular_power=40,
                metallic=0.85, roughness=0.18,
                pbr=False,
            )

        self.plotter.reset_camera()
        # Apply the chips' active preset.
        try:
            self.set_view(self.chips.active())
        except Exception:
            pass
        self.plotter.render()

    # ==================================================================
    # Public API: camera presets
    # ==================================================================
    def set_view(self, view: str) -> None:
        """Snap the camera to a named canonical view."""
        if self.plotter is None:
            return
        try:
            set_camera_to_view(self.plotter, view)
            self.plotter.render()
            self.chips.set_active(view)
        except Exception:
            pass

    # ==================================================================
    # Layer toggles
    # ==================================================================
    def enable_layer(self, layer: str, on: bool) -> None:
        """Toggle visibility of an actor without rebuilding the meshes."""
        if self.plotter is None or layer not in ("winding", "bobbin", "airgap"):
            return
        self._layer_state[layer] = bool(on)
        if layer == "winding" and self._actor_winding is not None:
            self._actor_winding.SetVisibility(1 if on else 0)
        elif layer == "bobbin":
            for act in self._actor_bobbin:
                act.SetVisibility(1 if on else 0)
        elif layer == "airgap":
            # Airgap is a property of the core mesh — toggling it alters
            # the core opacity. Implementation deferred; keep state.
            pass
        self.plotter.render()

    def _on_layers_changed(self, layers: dict) -> None:
        for k, v in layers.items():
            self.enable_layer(k, v)

    # ==================================================================
    # Section / measure / explode / export
    # ==================================================================
    def request_section(self, on: bool) -> None:
        if self.plotter is None or not self._actor_core:
            return
        if on and self._section_widget is None:
            try:
                self._section_widget = self.plotter.add_mesh_clip_plane(
                    self._actor_core[0].GetMapper().GetInput(),
                )
            except Exception:
                self._section_widget = None
        elif not on and self._section_widget is not None:
            try:
                self.plotter.clear_plane_widgets()
            except Exception:
                pass
            self._section_widget = None
        # Sync the bottom-actions checked state.
        if self.action_bar.btn_section.isChecked() != on:
            self.action_bar.btn_section.blockSignals(True)
            self.action_bar.btn_section.setChecked(on)
            self.action_bar.btn_section.blockSignals(False)

    def _sync_section(self, on: bool) -> None:
        # Forward bottom-actions toggle into the side-toolbar state.
        self.toolbar._buttons["crop"].blockSignals(True)
        self.toolbar._buttons["crop"].setChecked(on)
        self.toolbar._buttons["crop"].blockSignals(False)
        self.request_section(on)

    def request_measure(self, on: bool) -> None:
        if self.plotter is None:
            return
        try:
            if on:
                self.plotter.add_measurement_widget(callback=lambda *a: None)
                self._measure_widget = True
            else:
                self.plotter.clear_measure_widgets()
                self._measure_widget = None
        except Exception:
            pass
        if self.action_bar.btn_measure.isChecked() != on:
            self.action_bar.btn_measure.blockSignals(True)
            self.action_bar.btn_measure.setChecked(on)
            self.action_bar.btn_measure.blockSignals(False)

    def _sync_measure(self, on: bool) -> None:
        self.toolbar._buttons["ruler"].blockSignals(True)
        self.toolbar._buttons["ruler"].setChecked(on)
        self.toolbar._buttons["ruler"].blockSignals(False)
        self.request_measure(on)

    def request_explode(self, on: bool) -> None:
        # Cosmetic: shift each core block outward by 8 mm when on.
        if self.plotter is None:
            return
        offset = 8.0 if on else 0.0
        for actor in self._actor_core:
            try:
                actor.SetPosition(offset, 0, 0)
            except Exception:
                pass
        self.plotter.render()

    def request_screenshot(self, path: Optional[str] = None) -> Optional[str]:
        if self.plotter is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Salvar screenshot", "viewer3d.png", "PNG (*.png)"
            )
            if not path:
                return None
        try:
            self.plotter.screenshot(path)
            return path
        except Exception:
            return None

    def request_export(self, fmt: str) -> Optional[str]:
        if self.plotter is None:
            return None
        if fmt == "png":
            return self.request_screenshot()
        path, _ = QFileDialog.getSaveFileName(
            self, f"Exportar {fmt.upper()}",
            f"viewer3d.{fmt}", f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return None
        try:
            if fmt == "stl" and self._actor_core:
                self.plotter.export_obj(path)  # closest available
            elif fmt == "vrml":
                self.plotter.export_vrml(path)
            return path
        except Exception:
            return None

    # ==================================================================
    # Misc: fullscreen / autorotate
    # ==================================================================
    def _on_fullscreen(self) -> None:
        # Toggle the host window's full screen.
        win = self.window()
        if win is None:
            return
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()

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
