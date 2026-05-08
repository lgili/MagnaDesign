"""Plot panel: current waveform, loss breakdown, rolloff and 3D core view."""
from __future__ import annotations

import math
from typing import Optional

import matplotlib
import numpy as np

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from pfc_inductor.models import Core, DesignResult, Material, Wire
from pfc_inductor.ui.core_view_3d import CoreView3D
from pfc_inductor.visual import compute_bh_trajectory


class _Canvas(FigureCanvasQTAgg):
    def __init__(self, parent: Optional[QWidget] = None, n_axes: int = 1):
        self.fig = Figure(figsize=(7, 4.5), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)
        if n_axes == 1:
            self.ax = self.fig.add_subplot(111)
            self.axes = [self.ax]
        else:
            self.axes = [self.fig.add_subplot(n_axes, 1, i + 1) for i in range(n_axes)]


class PlotPanel(QWidget):
    """Tabbed plots: inductor current waveform / loss bar chart / rolloff curve."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.canvas_iL = _Canvas(self, n_axes=1)
        self.canvas_loss = _Canvas(self, n_axes=1)
        self.canvas_bh = _Canvas(self, n_axes=1)
        self.canvas_rolloff = _Canvas(self, n_axes=1)
        self.view_3d = CoreView3D(self)

        self.tabs.addTab(self.view_3d, "Core 3D")
        self.tabs.addTab(self.canvas_iL, "Inductor current")
        self.tabs.addTab(self.canvas_loss, "Losses")
        self.tabs.addTab(self.canvas_bh, "B–H loop")
        self.tabs.addTab(self.canvas_rolloff, "μ% vs H (rolloff)")

    def update_plots(
        self,
        r: DesignResult,
        rolloff_curve: Optional[tuple[np.ndarray, np.ndarray]] = None,
        H_op_Oe: Optional[float] = None,
        *,
        core: Optional[Core] = None,
        wire: Optional[Wire] = None,
        material: Optional[Material] = None,
    ):
        # ---- Inductor / line-reactor current waveform ----
        is_line_reactor = r.pct_impedance_actual is not None
        # Rebuild the figure layout based on topology:
        # - line_reactor: 2 subplots (waveform on top, spectrum below)
        # - other: 1 subplot (existing inductor envelope)
        self.canvas_iL.fig.clear()
        if is_line_reactor and r.waveform_t_s and r.waveform_iL_A:
            ax_top = self.canvas_iL.fig.add_subplot(2, 1, 1)
            ax_bot = self.canvas_iL.fig.add_subplot(2, 1, 2)
            self.canvas_iL.axes = [ax_top, ax_bot]
            self.canvas_iL.ax = ax_top
            self._plot_line_reactor(r, ax_top, ax_bot)
        else:
            ax = self.canvas_iL.fig.add_subplot(1, 1, 1)
            self.canvas_iL.axes = [ax]
            self.canvas_iL.ax = ax
            if r.waveform_t_s and r.waveform_iL_A:
                t_ms = np.array(r.waveform_t_s) * 1000.0
                iL_pk = np.array(r.waveform_iL_A)
                ax.plot(t_ms, iL_pk, label="iL peak (envelope + ripple)", linewidth=1.5)
                ax.fill_between(t_ms, 0, iL_pk, alpha=0.15)
                ax.set_xlabel("t [ms]")
                ax.set_ylabel("iL [A]")
                ax.set_title("Inductor current — half line cycle")
                ax.grid(True, alpha=0.4)
                ax.legend(loc="upper right")
            else:
                ax.text(0.5, 0.5, "No waveform (pick boost CCM or line reactor)",
                        ha="center", va="center", transform=ax.transAxes)
        self.canvas_iL.draw()

        # ---- Loss bar chart ----
        ax = self.canvas_loss.ax
        ax.clear()
        L = r.losses
        labels = ["Cu DC", "Cu AC", "Core (line)", "Core (ripple)"]
        values = [L.P_cu_dc_W, L.P_cu_ac_W, L.P_core_line_W, L.P_core_ripple_W]
        colors = ["#3a78b5", "#7eaee0", "#b53a3a", "#e07e7e"]
        bars = ax.bar(labels, values, color=colors)
        ax.set_ylabel("Loss [W]")
        ax.set_title(f"Losses (total = {L.P_total_W:.2f} W)")
        ax.grid(True, axis="y", alpha=0.4)
        for b, v in zip(bars, values, strict=False):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=9)
        self.canvas_loss.draw()

        # ---- B–H operating loop ----
        ax = self.canvas_bh.ax
        ax.clear()
        if core is not None and material is not None:
            try:
                tr = compute_bh_trajectory(r, core, material)
            except Exception as e:
                tr = None
                ax.text(0.5, 0.5, f"Could not compute B–H:\n{e}",
                        ha="center", va="center", transform=ax.transAxes,
                        color="#a01818")
            if tr is not None:
                # Static curve in light gray
                ax.plot(tr["H_static_Oe"], tr["B_static_T"] * 1000.0,
                        color="#bbb", linewidth=1.2, label="Static curve")
                # Bsat horizontal line
                ax.axhline(tr["Bsat_T"] * 1000.0, color="#a01818",
                           linestyle="--", alpha=0.6, linewidth=1.0,
                           label=f"Bsat (100°C) = {tr['Bsat_T']*1000:.0f} mT")
                # Slow envelope trace
                ax.plot(tr["H_envelope_Oe"], tr["B_envelope_T"] * 1000.0,
                        color="#3a78b5", linewidth=1.8, alpha=0.9,
                        label="Line envelope")
                # Ripple overlay
                if tr["H_ripple_Oe"] is not None:
                    ax.plot(tr["H_ripple_Oe"], tr["B_ripple_T"] * 1000.0,
                            color="#e07e3a", linewidth=2.6, alpha=0.85,
                            label="Ripple fsw (no pico)")
                # Operating-point peak marker
                ax.scatter([tr["H_pk_Oe"]], [tr["B_pk_T"] * 1000.0],
                           color="#a01818", s=70, zorder=5,
                           edgecolor="white", linewidth=1.5,
                           label=f"Pico ({tr['H_pk_Oe']:.0f} Oe, "
                                 f"{tr['B_pk_T']*1000:.0f} mT)")
                ax.set_xlabel("H [Oe]")
                ax.set_ylabel("B [mT]")
                ax.set_title("Loop B–H no operating point")
                ax.grid(True, alpha=0.4)
                ax.legend(loc="lower right", fontsize=8)
                # Cap y axis a hair above Bsat for visual headroom
                ymax = max(tr["Bsat_T"] * 1100.0, tr["B_pk_T"] * 1100.0)
                ax.set_ylim(0, ymax)
        else:
            ax.text(0.5, 0.5, "Selecione um núcleo e material",
                    ha="center", va="center", transform=ax.transAxes,
                    color="#888")
        self.canvas_bh.draw()

        # ---- Rolloff curve ----
        ax = self.canvas_rolloff.ax
        ax.clear()
        if rolloff_curve is not None:
            H, mu = rolloff_curve
            ax.semilogx(H, mu * 100, linewidth=1.8)
            if H_op_Oe is not None:
                ax.axvline(H_op_Oe, color="r", linestyle="--", alpha=0.6,
                           label=f"H operação = {H_op_Oe:.1f} Oe")
                ax.axhline(r.mu_pct_at_peak * 100, color="r", linestyle=":", alpha=0.6,
                           label=f"μ% = {r.mu_pct_at_peak*100:.1f}%")
                ax.legend(loc="lower left")
            ax.set_xlabel("H [Oe]")
            ax.set_ylabel("μ% (% inicial)")
            ax.set_title("Rolloff de permeabilidade vs DC bias")
            ax.set_ylim(0, 105)
            ax.grid(True, which="both", alpha=0.4)
        else:
            ax.text(0.5, 0.5, "Material sem rolloff (ferrite/nano sem dados)",
                    ha="center", va="center", transform=ax.transAxes)
        self.canvas_rolloff.draw()

        # ---- 3D core view ----
        if core is not None and wire is not None and material is not None:
            self.view_3d.update_view(core, wire, r.N_turns, material)

    # ------------------------------------------------------------------
    # Line-reactor specialised plot (waveform + IEC compliance)
    # ------------------------------------------------------------------
    def _plot_line_reactor(self, r: DesignResult, ax_top, ax_bot) -> None:
        """Top: i_a(t) over 2 line cycles. Bottom: harmonics in Amps RMS
        with IEC 61000-3-2 Class D limits overlaid for pass/fail readout.
        """
        from pfc_inductor.standards import iec61000_3_2 as iec
        from pfc_inductor.topology import line_reactor as lr

        t_arr = np.array(r.waveform_t_s)
        i_a = np.array(r.waveform_iL_A)

        # ---- top: time-domain waveform ----
        t_ms = t_arr * 1000.0
        I_rms = float(np.sqrt(np.mean(i_a * i_a)))
        ax_top.plot(t_ms, i_a, color="#3a78b5", linewidth=1.6,
                    label=f"I_rms = {I_rms:.1f} A   I_pk = {i_a.max():.1f} A")
        ax_top.axhline(0, color="#999", linewidth=0.6)
        ax_top.set_xlabel("t [ms]")
        ax_top.set_ylabel("i_a [A]")
        ax_top.set_title("Corrente de linha (fase A)")
        ax_top.grid(True, alpha=0.4)
        ax_top.legend(loc="upper right", fontsize=8)

        # ---- harmonic spectrum from FFT ----
        n_axis, pct_fund, thd_fft = lr.harmonic_spectrum(
            t_arr, i_a, f_line_Hz=60.0, n_harmonics=39,
        )

        # Convert %-of-fundamental to amps RMS.
        # I_total² = I_1² · (1 + Σ_{h>1}(pct_h)²)  ⇒ I_1 = I_total / √(1+Σ pct²)
        sum_sq = float(np.sum((pct_fund[1:] / 100.0) ** 2))
        I1_rms = I_rms / math.sqrt(1.0 + sum_sq) if (1.0 + sum_sq) > 0 else 0.0
        harmonics_A: dict[int, float] = {
            int(h): (pct_fund[i] / 100.0) * I1_rms
            for i, h in enumerate(n_axis)
        }

        # ---- IEC 61000-3-2 Class D limits ----
        Pi_W = r.Pi_W or 0.0
        compliance = iec.evaluate_compliance(harmonics_A, Pi_W)
        limits = iec.class_d_limits(Pi_W) if Pi_W > 0 else {}

        # ---- bottom: bar chart in mA with limits overlaid ----
        # Show only odd harmonics 3..39 plus the fundamental for context.
        plot_orders = [1] + iec.ODD_HARMONICS
        plot_amps = [harmonics_A.get(int(h), 0.0) for h in plot_orders]
        plot_amps_mA = [a * 1000.0 for a in plot_amps]

        # Color: fundamental green, others by pass/fail vs limit.
        colors: list[str] = []
        for h, amp in zip(plot_orders, plot_amps, strict=False):
            if h == 1:
                colors.append("#1c7c3b")
            else:
                lim = limits.get(int(h), 0.0)
                if lim <= 0 or amp <= lim:
                    colors.append("#3a78b5")   # pass: blue
                else:
                    colors.append("#a01818")   # fail: red

        bars = ax_bot.bar(plot_orders, plot_amps_mA, width=0.7, color=colors,
                          label="Predito (RMS)")

        # Overlay limit line (dashed) — Class D limits for n=3..39 only
        if limits:
            lim_orders = sorted(limits.keys())
            lim_vals_mA = [limits[n] * 1000.0 for n in lim_orders]
            ax_bot.plot(lim_orders, lim_vals_mA,
                        color="#a06700", linestyle="--", marker="o",
                        markersize=4, linewidth=1.5,
                        label="IEC 61000-3-2 Classe D")

        ax_bot.set_xlabel("Ordem harmônica")
        ax_bot.set_ylabel("Corrente [mA RMS]")
        verdict = ("✓ Passa" if compliance.passes else "✗ Reprova")
        worst = compliance.limiting_harmonic
        worst_str = (
            f"  ·  pior: h={worst} ({compliance.margin_min_pct:+.1f}%)"
            if worst else ""
        )
        # Class D applies for Pi between 75 W and 600 W. Above 600 W,
        # IEC Class A limits apply (different formulas) — flag the user.
        scope_note = ""
        if Pi_W > 600.0:
            scope_note = "  ⚠ Pi > 600 W: fora do escopo Classe D; use Classe A"
        elif Pi_W < 75.0:
            scope_note = "  ⚠ Pi < 75 W: fora do escopo Classe D"
        ax_bot.set_title(
            f"IEC 61000-3-2 Classe D  ·  Pi = {Pi_W:.0f} W  ·  "
            f"{verdict}{worst_str}  ·  THD esp. {thd_fft:.1f}%{scope_note}"
        )
        ax_bot.set_xticks(plot_orders[::2])
        ax_bot.grid(True, axis="y", alpha=0.4)
        ax_bot.legend(loc="upper right", fontsize=8)
        # Annotate the dominant harmonics with their value
        for b, h, v_mA in zip(bars, plot_orders, plot_amps_mA, strict=False):
            if v_mA < 5:
                continue   # skip negligible bars
            ax_bot.text(b.get_x() + b.get_width()/2, v_mA * 1.02,
                        f"{v_mA:.0f}", ha="center", va="bottom", fontsize=7)
        # Y-range: tall enough to show both the highest bar and the
        # IEC limit curve.
        candidates_mA: list[float] = list(plot_amps_mA)
        if limits:
            candidates_mA.extend(v * 1000.0 for v in limits.values())
        candidates_mA.append(10.0)
        ax_bot.set_ylim(0, max(candidates_mA) * 1.15)
