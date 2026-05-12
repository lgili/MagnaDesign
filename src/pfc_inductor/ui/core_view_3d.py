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

from PySide6.QtCore import (
    QEasingCurve,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, Material, Wire
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.viewer3d import (
    BottomActions,
    OrientationCube,
    SideToolbar,
    ViewChips,
)

# ``pfc_inductor.visual`` pulls in pyvista (and pyvista pulls in vtk),
# which together cost ~400 ms of cold-import time. The functions below
# are only needed at scene-build time, AFTER ``_ensure_plotter`` has
# constructed the ``QtInteractor`` — i.e. several event-loop ticks
# after the main window paints. Importing them lazily here keeps
# ``import pfc_inductor.ui.main_window`` (~1.4 s before this change)
# below the threshold where the splash sits visible for noticeable
# time. The first ``refresh()`` call pays the import cost; subsequent
# calls hit Python's import cache and are free.
if False:  # pragma: no cover — typing-only import for IDEs / pyright
    from pfc_inductor.visual import (  # noqa: F401
        make_bobbin_mesh,
        make_core_mesh,
        make_winding_leads,
        make_winding_mesh,
        set_camera_to_view,
        winding_fit_info,
    )


def _can_use_3d() -> bool:
    """VTK + Qt OpenGL crash hard under offscreen platforms — disable then."""
    plat = os.environ.get("QT_QPA_PLATFORM", "").lower()
    if plat in ("offscreen", "minimal", "vnc"):
        return False
    return True


def _material_colors() -> dict[str, str]:
    """Map ``Material.type`` → RGB hex, sourced from the theme-invariant
    :class:`Viz3D <pfc_inductor.ui.theme.Viz3D>` palette so a powder core
    looks the same in light and dark themes (it should — the colour is a
    property of the magnetic material, not the UI)."""
    v = get_theme().viz3d
    return {
        "powder": v.material_powder,
        "ferrite": v.material_ferrite,
        "nanocrystalline": v.material_nanocrystalline,
        "amorphous": v.material_amorphous,
        "silicon-steel": v.material_silicon_steel,
        "default": v.material_default,
    }


class CoreView3D(QWidget):
    """Embedded VTK render of core + helical winding + overlay HUD."""

    camera_changed = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # The VTK ``QtInteractor`` import + construction together cost
        # 100–800 ms on a cold start — it has to spin up an OpenGL
        # context, register vtkRenderer / vtkRenderWindow, and pull in
        # all of pyvistaqt's submodules. Doing that inside ``__init__``
        # was THE single biggest contributor to the "splash sits for 3 s"
        # complaint: the dashboard mounts a ``Viz3DCard`` in the default
        # workspace tab, so every cold launch paid the cost before the
        # first paint event could even fire.
        #
        # The fix here is to keep ``__init__`` cheap (just a tiny
        # placeholder ``QLabel``) and defer the QtInteractor + scene
        # setup to the first ``showEvent``. The user gets a painted
        # dashboard immediately, sees "Carregando visualizador 3D…" for
        # one frame, then VTK fills in. If the user never switches to
        # this tab (or runs offscreen), we never pay the cost at all.
        self.plotter = None
        self._fallback: Optional[QLabel] = None
        self._plotter_init_attempted = False  # set by ``_ensure_plotter``
        self._init_pending_text = "Carregando visualizador 3D…"
        # When ``_can_use_3d()`` returns False (offscreen / minimal /
        # vnc platforms) we short-circuit to the permanent fallback
        # message right away — no point scheduling a deferred init
        # that can never succeed. This also keeps test suites under
        # ``QT_QPA_PLATFORM=offscreen`` behaving exactly as before.
        if not _can_use_3d():
            self._mount_fallback("Visualizador 3D indisponível em modo offscreen.")
        else:
            self._mount_fallback(self._init_pending_text)

        # ---- overlays --------------------------------------------------
        # Overlays are cheap (chips / cube / toolbar are pure-Qt widgets)
        # and they live on top of the plotter region, so we build them
        # eagerly. They can render without the plotter being ready —
        # there's just no scene to point at yet.
        self._build_overlays()
        # The camera observer attaches to ``self.plotter.iren`` so it
        # has to wait until the deferred init finishes; ``_ensure_plotter``
        # calls it then. The early call here is now a no-op (it
        # already guards on ``self.plotter is None``) — kept for the
        # offscreen path where it just returns immediately.
        self._install_camera_observer()

        self._current: Optional[tuple[Core, Wire, int, Material]] = None
        self._rotate_timer = QTimer(self)
        self._rotate_timer.timeout.connect(self._tick_rotation)

        # Mesh tracking for layer toggles.
        self._actor_core: list = []
        self._actor_winding = None
        self._actor_bobbin: list = []
        # ``bobbin`` flipped to True now that the former (carretel) renders
        # as a real 3-part assembly (former tube + 2 flanges) instead of
        # just two floating discs. Hides via the SideToolbar layer toggle.
        self._layer_state = {"winding": True, "bobbin": True, "airgap": True}

        # Section / measure widgets reused across toggles.
        self._section_widget = None
        self._measure_widget = None

    # ==================================================================
    # Initial scene setup
    # ==================================================================
    def _setup_renderer(self):
        v = get_theme().viz3d
        self.plotter.set_background(v.bg_bottom, top=v.bg_top)

        # MSAA — 8× multi-sample. VTK's default render window has
        # ``MultiSamples=0`` which means *no* edge antialiasing; the
        # result is the visibly jagged outlines users complained
        # about on the bundled ``.app`` ("fica feio quando compilado").
        # ``ren_win.SetMultiSamples(8)`` enables hardware MSAA at the
        # OpenGL FBO level — much higher quality than FXAA on geometric
        # edges, with negligible runtime cost on modern GPUs. We keep
        # FXAA enabled below for the texture / line-cap edges MSAA
        # doesn't cover.
        try:
            self.plotter.ren_win.SetMultiSamples(8)
        except Exception:
            pass

        # SSAA hangs the renderer on macOS 26.4 / Apple Silicon (VTK 9.x
        # + Cocoa-OpenGL combo): the bundled app sits at 0 % CPU inside
        # ``vtkSSAAPass::Render → vtkOpenGLRenderer::Clear`` and never
        # paints the first frame, which the user reports as "the app
        # doesn't open". FXAA is the cheapest safe alternative — single-
        # pass post-processing, no offscreen FBO juggling — and the
        # ``try`` block makes the entire AA step opt-out so a future VTK
        # regression on any OS doesn't deadlock the whole UI again.
        try:
            self.plotter.enable_anti_aliasing("fxaa")
        except Exception:
            pass
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
            position="upper_edge",
            color=get_theme().viz3d.text_dim,
            font_size=10,
        )

    # ==================================================================
    # Deferred-init plumbing
    # ==================================================================
    def _mount_fallback(self, message: str) -> None:
        """Show ``message`` in a centered ``QLabel`` while the real
        plotter isn't ready yet (or won't ever be — offscreen platform).

        Used twice: during ``__init__`` to paint immediately, and (briefly)
        as the visual "Carregando…" hint that gets replaced once VTK
        finishes booting in the deferred init step.
        """
        if self._fallback is None:
            self._fallback = QLabel()
            self._fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._fallback.setStyleSheet("color: #888; font-size: 12px;")
            self._outer.addWidget(self._fallback, 1)
        self._fallback.setText(message)
        self._fallback.show()

    def _drop_fallback(self) -> None:
        """Remove the placeholder label once the plotter is ready."""
        if self._fallback is not None:
            self._fallback.hide()
            self._outer.removeWidget(self._fallback)
            self._fallback.deleteLater()
            self._fallback = None

    def _ensure_plotter(self) -> None:
        """Construct the ``QtInteractor``, wire it into the layout, and
        replay any pre-init scene state.

        Idempotent on the result of the first call: a second invocation
        is a no-op because either ``self.plotter`` is already set OR
        the construction failed and we fell back to the error label.
        """
        if self.plotter is not None:
            return
        try:
            from PySide6.QtWidgets import QSizePolicy
            from pyvistaqt import QtInteractor

            self.plotter = QtInteractor(self)
            self.plotter.interactor.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
            )
            # Drop the "Carregando…" label BEFORE adding the interactor
            # so the layout's stretch factor lands on a single child.
            self._drop_fallback()
            self._outer.addWidget(self.plotter.interactor, 1)
            self._setup_renderer()
            # Wire the camera observer now that ``self.plotter.iren``
            # exists — the early call from ``__init__`` was a no-op.
            self._install_camera_observer()
            # Re-raise the overlay HUD AFTER the QtInteractor mounts —
            # the interactor's render-window child is added last to
            # ``self._outer`` and therefore lands on top in Qt's
            # widget Z-order, hiding the chips / cube / toolbar /
            # action-bar that were created back in ``__init__``. A
            # ``raise_()`` per overlay puts them back above the GL
            # surface. (The legacy eager-init path didn't hit this
            # because the interactor was constructed BEFORE the
            # overlays, so the overlays' initial Z-order put them
            # on top automatically.)
            for w in (self.chips, self.cube, self.toolbar, self.action_bar):
                if w is not None:
                    w.raise_()
            # Reposition after the layout change — the interactor
            # may have grown the widget's interior rect.
            self._reposition_overlays()
            # Replay scene: if ``update_view`` was called before init,
            # ``_current`` is set and we redraw against it; otherwise
            # show the standard placeholder.
            if self._current is not None:
                try:
                    self.refresh()
                except Exception:
                    pass
            else:
                try:
                    self._show_placeholder()
                except Exception:
                    pass
        except Exception as e:
            self.plotter = None
            self._mount_fallback(f"Visualizador 3D indisponível: {type(e).__name__}: {e}")

    # ==================================================================
    # Overlays
    # ==================================================================
    def _build_overlays(self) -> None:
        """Create the four overlay panels and stack them on top of the
        QtInteractor. They're parented to ``self`` so they can be
        repositioned in :meth:`resizeEvent`."""
        # Overlay widgets are parented to ``self`` (not the interactor)
        # so they can be repositioned in resizeEvent without fighting
        # the QtInteractor's child layout.
        self.chips = ViewChips(parent=self)
        self.chips.view_changed.connect(self.set_view)

        self.cube = OrientationCube(parent=self)
        self.cube.view_requested.connect(self.set_view)
        # Cube tracks camera orbits so its visible faces stay
        # synchronised with the live scene.
        self.camera_changed.connect(self.cube.update_from_camera)

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
        # First time the widget becomes visible, also schedule the
        # heavy VTK init on the next event-loop tick. Using
        # ``QTimer.singleShot(0, …)`` instead of inline init means the
        # placeholder paints first, the user sees movement, and only
        # then does the 100–800 ms ``QtInteractor`` construction land.
        # On subsequent shows (e.g. switching tabs back to the
        # dashboard) the ``_plotter_init_attempted`` guard prevents a
        # re-init.
        if not self._plotter_init_attempted and _can_use_3d():
            self._plotter_init_attempted = True
            QTimer.singleShot(0, self._ensure_plotter)

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
                "focal": tuple(cam.focal_point),
                "up": tuple(cam.up),
            }
        except Exception:
            return
        self.camera_changed.emit(payload)

    # ==================================================================
    # Public API: scene update
    # ==================================================================
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
        self._actor_core = []
        self._actor_winding = None
        self._actor_bobbin = []
        # Lazy import — pyvista + vtk together cost ~400 ms on cold
        # start; we don't pay that until ``refresh()`` actually has a
        # core to render. The first call here hits Python's import
        # machinery; subsequent calls are no-ops thanks to ``sys.modules``.
        from pfc_inductor.visual import (
            make_bobbin_mesh,
            make_core_mesh,
            make_winding_leads,
            make_winding_mesh,
            winding_fit_info,
        )

        try:
            mb, kind, info = make_core_mesh(core)
            wnd = make_winding_mesh(core, wire, N_turns, info)
            leads = (
                make_winding_leads(core, wire, N_turns, info)
                if self._layer_state.get("winding", True)
                else None
            )
            bobbin = (
                make_bobbin_mesh(core, wire, N_turns, info)
                if self._layer_state.get("bobbin", False)
                else None
            )
            fit = winding_fit_info(core, wire, N_turns, info)
        except Exception as e:
            self.plotter.add_text(
                f"Erro ao gerar mesh:\n{e}",
                position="upper_edge",
                color=get_theme().viz3d.text_error,
                font_size=10,
            )
            return
        # Cache the fit dict so callers (e.g. the dashboard's "fit
        # check" chip) can read it without redoing the math.
        self._last_fit = fit

        colors = _material_colors()
        core_color = colors.get(material.type, colors["default"])
        is_closed_shell = kind in ("ee", "etd", "pq")
        if material.type == "silicon-steel":
            core_kwargs = dict(metallic=0.65, roughness=0.45, specular=0.6, specular_power=20)
        elif material.type == "ferrite":
            core_kwargs = dict(metallic=0.05, roughness=0.40, specular=0.5, specular_power=18)
        elif material.type == "amorphous":
            core_kwargs = dict(metallic=0.7, roughness=0.30, specular=0.7, specular_power=25)
        else:
            core_kwargs = dict(metallic=0.05, roughness=0.65, specular=0.20, specular_power=10)
        opacity = 0.62 if is_closed_shell else 1.0

        for block in mb:
            if block is None:
                continue
            actor = self.plotter.add_mesh(
                block,
                color=core_color,
                smooth_shading=True,
                ambient=0.20,
                diffuse=0.85,
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
                    color=get_theme().viz3d.bobbin,
                    smooth_shading=True,
                    ambient=0.30,
                    diffuse=0.80,
                    specular=0.20,
                    specular_power=12,
                    metallic=0.0,
                    roughness=0.7,
                    pbr=False,
                )
                self._actor_bobbin.append(act)

        if wnd is not None and self._layer_state["winding"]:
            # Tinge the winding ``danger`` when the requested N_turns
            # overflowed the bobbin window — gives the engineer a
            # one-glance "this design doesn't fit" signal that the
            # tabular Bobinamento card can't deliver.
            #
            # Default colour comes from ``viz3d.wire_enamel`` (theme-
            # invariant) — real magnet wire is satin sienna brown,
            # not the polished-copper one would see on bare conductor.
            # ``palette.copper`` is reserved for cut-end stubs where
            # the lacquer is intentionally stripped.
            wire_color = get_theme().viz3d.wire_enamel
            if not fit["fits"]:
                wire_color = get_theme().palette.danger
            # Material kwargs tuned for **enameled** copper, not raw:
            #   metallic 0.85 → 0.55  (lacquer breaks the metal sheen)
            #   roughness 0.18 → 0.45 (satin, not glossy)
            #   specular  0.95 → 0.55 (no harsh highlight)
            self._actor_winding = self.plotter.add_mesh(
                wnd,
                color=wire_color,
                smooth_shading=True,
                ambient=0.25,
                diffuse=0.70,
                specular=0.55,
                specular_power=24,
                metallic=0.55,
                roughness=0.45,
                pbr=False,
            )
            # Wire leads — short stubs poking out of the bobbin so the
            # winding reads as "wound part" instead of "printed pattern".
            if leads is not None:
                for blk in leads:
                    if blk is None:
                        continue
                    self.plotter.add_mesh(
                        blk,
                        color=wire_color,
                        smooth_shading=True,
                        ambient=0.25,
                        diffuse=0.70,
                        specular=0.55,
                        specular_power=24,
                        metallic=0.55,
                        roughness=0.45,
                        pbr=False,
                    )
            if not fit["fits"]:
                self.plotter.add_text(
                    f"⚠ {fit['actual']} de {fit['requested']} voltas cabem "
                    f"({fit['layers']} camadas, "
                    f"{fit['turns_per_layer']}/camada)",
                    position="upper_left",
                    color=get_theme().viz3d.text_error,
                    font_size=9,
                )

        # self.plotter.reset_camera()
        # Apply the chips' active preset.
        try:
            self.set_view(self.chips.active())
        except Exception:
            pass
        self.plotter.render()

    # ==================================================================
    # Public API: camera presets
    # ==================================================================
    def set_view(self, view: str, *, animated: bool = True) -> None:
        """Animate the camera to a named canonical view.

        ``animated=True`` (default) interpolates ``camera_position``
        over 300 ms via :class:`QVariantAnimation` with an out-cubic
        easing curve. ``animated=False`` snaps instantly — used by
        the test suite to avoid flakiness from async timers.
        """
        if self.plotter is None:
            return
        # Lazy import — see ``refresh()`` for the rationale.
        from pfc_inductor.visual import set_camera_to_view

        try:
            self.chips.set_active(view)
        except Exception:
            pass
        if not animated:
            try:
                set_camera_to_view(self.plotter, view)
                self.plotter.render()
            except Exception:
                pass
            return
        # Capture start camera state, compute target, interpolate.
        try:
            cam = self.plotter.camera
            start_pos = tuple(cam.position)
            start_focal = tuple(cam.focal_point)
            start_up = tuple(cam.up)
            # Apply the target then read its state back.
            set_camera_to_view(self.plotter, view)
            target_pos = tuple(cam.position)
            target_focal = tuple(cam.focal_point)
            target_up = tuple(cam.up)
            # Restore start so the interpolation begins from the
            # original frame.
            cam.position = start_pos
            cam.focal_point = start_focal
            cam.up = start_up
        except Exception:
            # If we can't read the camera, fall back to a snap.
            try:
                set_camera_to_view(self.plotter, view)
                self.plotter.render()
            except Exception:
                pass
            return

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(300)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _lerp(a: tuple, b: tuple, t: float) -> tuple:
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

        def _on_value(t: float) -> None:
            if self.plotter is None:
                return
            try:
                self.plotter.camera.position = _lerp(start_pos, target_pos, t)
                self.plotter.camera.focal_point = _lerp(
                    start_focal,
                    target_focal,
                    t,
                )
                self.plotter.camera.up = _lerp(start_up, target_up, t)
                self.plotter.render()
            except Exception:
                pass

        anim.valueChanged.connect(_on_value)
        # Hold a reference so GC doesn't kill the animation mid-flight.
        self._view_anim = anim
        anim.start()

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
        """Animate core blocks outward by 8 mm (or back to origin).

        Cosmetic — does not affect mesh geometry. Uses a 250 ms
        ``QVariantAnimation`` with an ease-out curve so the motion
        feels intentional rather than abrupt.
        """
        if self.plotter is None or not self._actor_core:
            return
        # Capture current positions and target positions per actor.
        starts: list[tuple[float, float, float]] = []
        targets: list[tuple[float, float, float]] = []
        for actor in self._actor_core:
            try:
                pos = tuple(actor.GetPosition())  # (x, y, z)
            except Exception:
                pos = (0.0, 0.0, 0.0)
            starts.append(pos)
            tx = 8.0 if on else 0.0
            targets.append((tx, pos[1], pos[2]))

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(250)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_value(t: float) -> None:
            if self.plotter is None:
                return
            for i, actor in enumerate(self._actor_core):
                s = starts[i]
                tgt = targets[i]
                try:
                    actor.SetPosition(
                        s[0] + (tgt[0] - s[0]) * t,
                        s[1] + (tgt[1] - s[1]) * t,
                        s[2] + (tgt[2] - s[2]) * t,
                    )
                except Exception:
                    pass
            try:
                self.plotter.render()
            except Exception:
                pass

        anim.valueChanged.connect(_on_value)
        self._explode_anim = anim
        anim.start()

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
            self,
            f"Exportar {fmt.upper()}",
            f"viewer3d.{fmt}",
            f"{fmt.upper()} (*.{fmt})",
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
