"""Three-way cross-check of the line-reactor waveforms.

Compares our analytical model against two independent simulators:

1. **ngspice** — open-source SPICE; netlist below describes a real
   diode-bridge + DC-link cap + reactor circuit.
2. **Pulsim** — pure-Python power-electronics simulator
   (``github.com/lgili/Pulsim``). Same topology, runtime API instead of
   netlist text.

For each topology (1-phase 220 V / 1 A_rms, 3-phase 380 V_LL / ~3 A_rms,
both with L = 10 mH per phase) we plot the line current alongside our
analytical model and the harmonic spectrum, with all available
simulators overlaid. ngspice is required; Pulsim is optional — if it
fails to converge (rectifier circuits with idealised diodes are
notoriously hard) we just skip that trace and note the failure.

Outputs:

  data/spice_comparison/
    spice_1ph_220V_1A_10mH.png       waveform + spectrum overlay
    spice_3ph_380V_30A_10mH.png      waveform + spectrum overlay
    spice_compare_summary.csv        h=1..15 amplitudes per simulator

Run:

    .venv/bin/python scripts/spice_compare_line_reactor.py

Requires:
    - ngspice on PATH (`brew install ngspice` / `apt install ngspice`).
    - Optional: ``Pulsim`` (``uv pip install git+https://github.com/lgili/Pulsim``).
"""
from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pfc_inductor.models import Spec  # noqa: E402  type: ignore[import-not-found]
from pfc_inductor.topology import line_reactor as lr  # noqa: E402  type: ignore[import-not-found]


OUT_DIR = REPO_ROOT / "data" / "spice_comparison"
# ngspice's wrdata splits paths on whitespace, so we keep its working
# files under a no-space tmp dir.
TMP_DIR = Path("/tmp/pfc_spice_compare")


# ---------------------------------------------------------------------------
# Netlist builders
# ---------------------------------------------------------------------------
def netlist_1ph(
    Vrms: float, f_line: float, L_H: float, C_F: float, R_load: float,
    *, t_stop_s: float, t_step_s: float = 5e-6,
) -> str:
    """1-phase full-bridge rectifier with input reactor and DC-link cap.

    AC source feeds n_a and n_b (floating across the bridge legs).
    Bridge: D1/D2 to n_p (positive bus), D3/D4 from n_n (negative bus).
    n_n is grounded for SPICE matrix conditioning. A small bleeder
    resistor across the cap avoids initial-condition divergence.
    """
    V_pk = math.sqrt(2.0) * Vrms
    # Pre-charge to ~85% of peak so the cap reaches steady-state charge
    # quickly without massive inrush. With L=10 mH the natural transient
    # then settles in 3–5 line cycles.
    Vdc0 = 0.85 * math.sqrt(2.0) * Vrms
    # Single-phase with floating AC: V_ac is between n_a and n_b. We
    # ground n_n hard (R_gnd = 1 µΩ) to give the matrix a reference
    # — no parasitic current flows through the ground connection because
    # the AC source itself is floating, so the only DC path is through
    # the bridge → load → bridge.
    return (
        "* 1-phase rectifier with input reactor\n"
        f"V_ac n_a n_b SIN(0 {V_pk:.3f} {f_line:.3f})\n"
        f"L_in n_a n_L1 {L_H:.6e}\n"
        f"R_L1 n_L1 n_aL 0.05\n"
        ".model DBR D(Is=2.5e-9 N=1.6 Rs=0.02 Cjo=10p Bv=600)\n"
        "D1 n_aL n_p DBR\n"
        "D2 n_b  n_p DBR\n"
        "D3 n_n  n_aL DBR\n"
        "D4 n_n  n_b  DBR\n"
        f"R_esr n_p n_pX 0.1\n"
        f"C_dc n_pX n_n {C_F:.6e} IC={Vdc0:.1f}\n"
        f"R_load n_p n_n {R_load:.3f}\n"
        "R_bleed n_p n_n 100k\n"
        "R_gnd n_n 0 1u\n"
        ".options abstol=1e-9 reltol=1e-3 chgtol=1e-12 method=trap\n"
        f".tran {t_step_s:.2e} {t_stop_s:.3e} 0 {t_step_s:.2e} uic\n"
        ".end\n"
    )


def netlist_3ph(
    V_LL_rms: float, f_line: float, L_H: float, C_F: float, R_load: float,
    *, t_stop_s: float, t_step_s: float = 5e-6,
) -> str:
    """3-phase 6-pulse diode rectifier with per-phase input reactors.

    Three balanced phase voltages at V_phase_rms = V_LL/√3, 120° apart,
    referenced to a common neutral (which we ground). Each phase feeds
    a series reactor and the Graetz bridge (D1..D6).
    """
    V_phase_pk = math.sqrt(2.0) * V_LL_rms / math.sqrt(3.0)
    Vdc0 = 0.85 * V_LL_rms * math.sqrt(2.0)
    # Three-phase: AC sources are already referenced to ground (the 0
    # node), so the matrix has a DC reference. The DC bus floats — do
    # NOT ground n_n, because that would create a parasitic path from
    # AC neutral (=0) into the rectifier output and inflate line currents
    # by an order of magnitude.
    return (
        "* 3-phase 6-pulse rectifier with input reactors\n"
        f"V_a n_a 0 SIN(0 {V_phase_pk:.3f} {f_line:.3f} 0 0 0)\n"
        f"V_b n_b 0 SIN(0 {V_phase_pk:.3f} {f_line:.3f} 0 0 -120)\n"
        f"V_c n_c 0 SIN(0 {V_phase_pk:.3f} {f_line:.3f} 0 0 -240)\n"
        f"L_a n_a n_La {L_H:.6e}\n"
        f"R_La n_La n_aL 0.05\n"
        f"L_b n_b n_Lb {L_H:.6e}\n"
        f"R_Lb n_Lb n_bL 0.05\n"
        f"L_c n_c n_Lc {L_H:.6e}\n"
        f"R_Lc n_Lc n_cL 0.05\n"
        ".model DBR D(Is=2.5e-9 N=1.6 Rs=0.02 Cjo=10p Bv=600)\n"
        "D1 n_aL n_p DBR\n"
        "D2 n_bL n_p DBR\n"
        "D3 n_cL n_p DBR\n"
        "D4 n_n  n_aL DBR\n"
        "D5 n_n  n_bL DBR\n"
        "D6 n_n  n_cL DBR\n"
        f"R_esr n_p n_pX 0.1\n"
        f"C_dc n_pX n_n {C_F:.6e} IC={Vdc0:.1f}\n"
        f"R_load n_p n_n {R_load:.3f}\n"
        "R_bleed n_p n_n 100k\n"
        ".options abstol=1e-9 reltol=1e-3 chgtol=1e-12 method=trap\n"
        f".tran {t_step_s:.2e} {t_stop_s:.3e} 0 {t_step_s:.2e} uic\n"
        ".end\n"
    )


# ---------------------------------------------------------------------------
# Run + parse
# ---------------------------------------------------------------------------
def run_spice(netlist: str, name: str) -> Tuple[np.ndarray, np.ndarray]:
    """Run the netlist in ngspice batch mode and return (t, i_L).

    We prefer ngspice because LTspice on macOS doesn't have a reliable
    batch mode — it opens the GUI even with -b. ngspice is open-source,
    cross-platform, and ships clean CSV output via the ``wrdata``
    command appended at the bottom of the netlist.
    """
    import subprocess
    import shutil as _shutil

    ng = _shutil.which("ngspice")
    if ng is None:
        raise RuntimeError(
            "ngspice not on PATH. Install: `brew install ngspice` (macOS) / "
            "`apt install ngspice` (Linux) / installer from ngspice.sf.net (Win)."
        )

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    cir = TMP_DIR / f"{name}.cir"
    out_csv = TMP_DIR / f"{name}.dat"

    # ngspice batch convention: top-level title + components + .control.
    # We strip the .end if present; the .control block runs the .tran and
    # writes a tab-separated dump that numpy can read directly.
    body = "\n".join(line for line in netlist.splitlines()
                     if line.strip().lower() != ".end")
    # ngspice wrdata interleaves time as a column for *each* requested
    # variable: asking for N variables yields 2·N columns (t, v) per
    # variable. We want just the reactor current — so request only that.
    i_var = "i(L_a)" if "L_a" in netlist else "i(L_in)"
    full = (
        f"{body}\n"
        ".control\n"
        "set noaskquit\n"
        "run\n"
        f"wrdata {out_csv} {i_var}\n"
        "quit\n"
        ".endc\n"
        ".end\n"
    )
    cir.write_text(full, encoding="utf-8")

    proc = subprocess.run(
        [ng, "-b", "-o", str(TMP_DIR / f"{name}.log"), str(cir)],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not out_csv.exists():
        raise RuntimeError(
            f"ngspice failed for {name}: rc={proc.returncode}\n"
            f"stderr (first 500 chars):\n{proc.stderr[:500]}"
        )

    data = np.loadtxt(out_csv)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    t = data[:, 0].astype(float)
    i_L = data[:, 1].astype(float)
    order = np.argsort(t)
    return t[order], i_L[order]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def resample_uniform(t: np.ndarray, y: np.ndarray, dt: float) -> Tuple[np.ndarray, np.ndarray]:
    """LTspice uses adaptive timesteps; we need uniform sampling for FFT."""
    t_uniform = np.arange(t[0], t[-1], dt)
    y_uniform = np.interp(t_uniform, t, y)
    return t_uniform, y_uniform


def harmonic_spectrum(t: np.ndarray, i: np.ndarray, f_line: float,
                      n_harmonics: int = 15) -> Tuple[np.ndarray, float]:
    """Return (peak_pct_of_fundamental[h-1], THD_pct)."""
    n = len(i)
    fft = np.fft.rfft(i)
    freqs = np.fft.rfftfreq(n, t[1] - t[0])
    mag = np.abs(fft) * 2.0 / n
    pct = np.zeros(n_harmonics)
    fund = 0.0
    for h in range(1, n_harmonics + 1):
        idx = int(np.argmin(np.abs(freqs - h * f_line)))
        if h == 1:
            fund = float(mag[idx]) or 1e-9
            pct[0] = 100.0
        else:
            pct[h - 1] = float(mag[idx]) / fund * 100.0
    thd = math.sqrt(float(np.sum((pct[1:] / 100.0) ** 2))) * 100.0
    return pct, thd


def grab_steady_state(t: np.ndarray, y: np.ndarray, f_line: float,
                      n_cycles: int = 5) -> Tuple[np.ndarray, np.ndarray]:
    """Return the last ``n_cycles`` of the simulation (after transients)."""
    T = 1.0 / f_line
    t_min = max(t[0], t[-1] - n_cycles * T)
    mask = t >= t_min
    return t[mask] - t_min, y[mask]


# ---------------------------------------------------------------------------
# Pulsim runs (best-effort — convergence on stiff rectifier circuits is
# tricky; we wrap any failure as ``None`` so the plot still renders.)
# ---------------------------------------------------------------------------
def run_pulsim_1ph(Vrms: float, f_line: float, L_H: float, C_F: float,
                   R_load: float, *, t_stop_s: float, dt: float = 5e-6,
                   ) -> Tuple[np.ndarray, np.ndarray] | None:
    try:
        import pulsim
    except ImportError:
        print("   (Pulsim not installed — pip install git+https://github.com/lgili/Pulsim)")
        return None
    Vdc0 = 0.85 * math.sqrt(2.0) * Vrms
    c = pulsim.Circuit()
    gnd = c.ground()
    n_a = c.add_node("a")
    n_b = c.add_node("b")
    n_aL = c.add_node("aL")
    n_p = c.add_node("p")
    # Full-bridge: V_ac between n_a and n_b (floating); n_n = gnd.
    c.add_sine_voltage_source("Vac", n_a, n_b, math.sqrt(2.0) * Vrms, f_line)
    c.add_inductor("L1", n_a, n_aL, L_H)
    c.add_diode("D1", n_aL, n_p, 1e3, 1e-9)
    c.add_diode("D2", n_b,  n_p, 1e3, 1e-9)
    c.add_diode("D3", gnd,  n_aL, 1e3, 1e-9)
    c.add_diode("D4", gnd,  n_b, 1e3, 1e-9)
    c.add_capacitor("C1", n_p, gnd, C_F, ic=Vdc0)
    c.add_resistor("R1", n_p, gnd, R_load)
    try:
        t_list, states_list, ok, msg = pulsim.run_transient(
            c, 0.0, t_stop_s, dt,
        )
    except Exception as e:
        print(f"   Pulsim raised: {e}")
        return None
    if not ok:
        print(f"   Pulsim did not converge: {msg[:120]}")
        return None
    sig = c.signal_names()
    iL_idx = sig.index("I(L1)")
    states = np.array(states_list)
    return np.array(t_list), states[:, iL_idx]


def run_pulsim_3ph(V_LL: float, f_line: float, L_H: float, C_F: float,
                   R_load: float, *, t_stop_s: float, dt: float = 5e-6,
                   ) -> Tuple[np.ndarray, np.ndarray] | None:
    try:
        import pulsim
    except ImportError:
        return None
    V_phase_pk = math.sqrt(2.0) * V_LL / math.sqrt(3.0)
    Vdc0 = 0.85 * V_LL * math.sqrt(2.0)
    c = pulsim.Circuit()
    gnd = c.ground()
    n_a, n_b, n_c = c.add_node("a"), c.add_node("b"), c.add_node("c")
    n_aL, n_bL, n_cL = c.add_node("aL"), c.add_node("bL"), c.add_node("cL")
    n_p, n_n = c.add_node("p"), c.add_node("n")
    # 3-phase sources: amplitude, freq, offset overload doesn't take
    # phase, so we use SineParams.
    for name, node, phase_deg in (("Va", n_a, 0.0), ("Vb", n_b, -120.0),
                                  ("Vc", n_c, -240.0)):
        sp = pulsim.SineParams()
        sp.amplitude = V_phase_pk
        sp.frequency = f_line
        sp.offset = 0.0
        sp.phase = math.radians(phase_deg)
        c.add_sine_voltage_source(name, node, gnd, sp)
    for name, n_in, n_out in (("La", n_a, n_aL), ("Lb", n_b, n_bL),
                              ("Lc", n_c, n_cL)):
        c.add_inductor(name, n_in, n_out, L_H)
    # Softer diode (lower on-conductance) helps Newton converge in
    # 3-phase rectifiers where 6 diodes commute on tight schedule.
    g_on, g_off = 100.0, 1e-6
    for name, anode, cath in (("D1", n_aL, n_p), ("D2", n_bL, n_p),
                              ("D3", n_cL, n_p), ("D4", n_n, n_aL),
                              ("D5", n_n, n_bL), ("D6", n_n, n_cL)):
        c.add_diode(name, anode, cath, g_on, g_off)
    c.add_capacitor("C1", n_p, n_n, C_F, ic=Vdc0)
    c.add_resistor("R1", n_p, n_n, R_load)
    # Bleeder + ground reference for the floating DC bus to give Newton
    # a stable matrix at t=0.
    c.add_resistor("Rg", n_n, gnd, 1e6)
    try:
        t_list, states_list, ok, msg = pulsim.run_transient(
            c, 0.0, t_stop_s, dt,
        )
    except Exception as e:
        print(f"   Pulsim raised: {e}")
        return None
    if not ok:
        print(f"   Pulsim did not converge: {msg[:120]}")
        return None
    sig = c.signal_names()
    iL_idx = sig.index("I(La)")
    states = np.array(states_list)
    return np.array(t_list), states[:, iL_idx]


# ---------------------------------------------------------------------------
# Main: 1-phase + 3-phase comparison
# ---------------------------------------------------------------------------
def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    L_H = 10e-3   # 10 mH input reactor (as the user requested)
    f_line = 50.0
    summary_rows: list[str] = []
    summary_rows.append("topology,h,spice_pct,model_pct")

    # =====================================================================
    # 1-phase: 220 V/50 Hz, ~1 A_rms target → R_load picked to land there
    # =====================================================================
    print("\n[1/2] 1-phase 220 V / ~1 A_rms / L=10 mH ...")
    Vrms_1 = 220.0
    C_dc_F = 470e-6      # 470 µF — typical for ~200 W residential drive
    # Pick R_load so that DC bus draws ~150 W: V_dc² / R = P → R = V²/P
    # With V_dc ≈ 305 V and P_target = 150 W → R ≈ 620 Ω
    R_load = 620.0
    netlist = netlist_1ph(Vrms_1, f_line, L_H, C_dc_F, R_load,
                          t_stop_s=0.50)
    t_raw, i_raw = run_spice(netlist, "rect_1ph_10mH")
    t_uni, i_uni = resample_uniform(t_raw, i_raw, dt=20e-6)  # 50 kHz
    t_ss, i_ss = grab_steady_state(t_uni, i_uni, f_line, n_cycles=4)
    rms_spice = float(np.sqrt(np.mean(i_ss * i_ss)))
    print(f"   SPICE: I_rms = {rms_spice:.3f} A   I_pk = {float(np.max(np.abs(i_ss))):.2f} A")

    # Build the same operating point in our model (1-phase, %Z = ω·L·I/V)
    omega = 2 * math.pi * f_line
    pct_Z = (omega * L_H * rms_spice) / Vrms_1 * 100.0
    spec_1 = Spec(topology="line_reactor", n_phases=1,
                  Vin_nom_Vrms=Vrms_1, I_rated_Arms=rms_spice,
                  pct_impedance=pct_Z, f_line_Hz=f_line)
    L_mH = lr.required_inductance_mH(spec_1)
    t_mod, i_mod = lr.line_current_waveform(spec_1, L_mH,
                                            n_cycles=5, n_points=len(t_ss))

    spice_pct, thd_spice = harmonic_spectrum(t_ss, i_ss, f_line)
    model_pct, thd_model = harmonic_spectrum(t_mod, i_mod, f_line)

    # Pulsim run (best-effort)
    print("   Pulsim ...")
    pulsim_run = run_pulsim_1ph(Vrms_1, f_line, L_H, C_dc_F, R_load,
                                t_stop_s=0.40, dt=20e-6)
    pulsim_pct: np.ndarray | None = None
    thd_pulsim = 0.0
    if pulsim_run is not None:
        t_p, i_p = pulsim_run
        t_p_uni, i_p_uni = resample_uniform(t_p, i_p, dt=20e-6)
        t_p_ss, i_p_ss = grab_steady_state(t_p_uni, i_p_uni, f_line, n_cycles=4)
        rms_pulsim = float(np.sqrt(np.mean(i_p_ss * i_p_ss)))
        print(f"   Pulsim: I_rms = {rms_pulsim:.3f} A   I_pk = "
              f"{float(np.max(np.abs(i_p_ss))):.2f} A")
        pulsim_pct, thd_pulsim = harmonic_spectrum(t_p_ss, i_p_ss, f_line)

    print(f"   THD: spice={thd_spice:.1f}%  model={thd_model:.1f}%"
          + (f"  pulsim={thd_pulsim:.1f}%" if pulsim_pct is not None else ""))
    print("   h     spice    model" + ("    pulsim" if pulsim_pct is not None else ""))
    for h in (1, 3, 5, 7, 9, 11, 13):
        line = f"   {h:>3}   {spice_pct[h-1]:>5.1f}%  {model_pct[h-1]:>5.1f}%"
        if pulsim_pct is not None:
            line += f"   {pulsim_pct[h-1]:>5.1f}%"
        print(line)
        row = f"1ph,{h},{spice_pct[h-1]:.2f},{model_pct[h-1]:.2f}"
        if pulsim_pct is not None:
            row += f",{pulsim_pct[h-1]:.2f}"
        summary_rows.append(row)

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(10, 7), tight_layout=True)
    ax_top.plot(t_ss * 1000, i_ss, label="ngspice", color="#a01818", linewidth=1.6)
    ax_top.plot(t_mod * 1000, i_mod, label="modelo analítico",
                color="#3a78b5", linewidth=1.4, alpha=0.85)
    if pulsim_pct is not None:
        ax_top.plot(t_p_ss * 1000, i_p_ss, label="Pulsim",
                    color="#1c7c3b", linewidth=1.3, alpha=0.85, linestyle="--")
    ax_top.set_xlabel("t [ms]")
    ax_top.set_ylabel("i_L [A]")
    ax_top.set_title(f"1-fase, 220 V, L=10 mH, C={C_dc_F*1e6:.0f} µF — I_rms ≈ {rms_spice:.2f} A")
    ax_top.grid(True, alpha=0.4); ax_top.legend()

    h_axis = np.arange(1, 16)
    if pulsim_pct is not None:
        width = 0.27
        ax_bot.bar(h_axis - width, spice_pct, width=width, label="ngspice", color="#a01818")
        ax_bot.bar(h_axis,         model_pct, width=width, label="modelo",  color="#3a78b5")
        ax_bot.bar(h_axis + width, pulsim_pct, width=width, label="Pulsim",  color="#1c7c3b")
    else:
        width = 0.4
        ax_bot.bar(h_axis - width/2, spice_pct, width=width, label="ngspice", color="#a01818")
        ax_bot.bar(h_axis + width/2, model_pct, width=width, label="modelo",  color="#3a78b5")
    ax_bot.set_xlabel("Ordem harmônica")
    ax_bot.set_ylabel("% do fundamental")
    ax_bot.set_xticks(h_axis)
    ax_bot.grid(True, axis="y", alpha=0.4); ax_bot.legend()
    title_extra = (
        f"  pulsim={thd_pulsim:.1f}%" if pulsim_pct is not None else ""
    )
    ax_bot.set_title(
        f"Espectro — THD spice={thd_spice:.1f}%  modelo={thd_model:.1f}%{title_extra}"
    )
    fig.savefig(OUT_DIR / "spice_1ph_220V_1A_10mH.png", dpi=120)
    plt.close(fig)
    print(f"   wrote {OUT_DIR / 'spice_1ph_220V_1A_10mH.png'}")

    # =====================================================================
    # 3-phase: 380 V_LL / 50 Hz / 10 mH per-phase
    # =====================================================================
    print("\n[2/2] 3-phase 380 V_LL / L=10 mH per phase ...")
    V_LL = 380.0
    # 470 µF + 10 mH per phase → LC resonance ≈ 73 Hz (well off the
    # fundamental and 6th-harmonic peaks at 50 / 300 Hz).
    C_dc_F_3 = 470e-6
    # V_dc ≈ √2·V_LL = 537 V; P_target = 2 kW → R ≈ 144 Ω
    R_load_3 = 144.0
    netlist = netlist_3ph(V_LL, f_line, L_H, C_dc_F_3, R_load_3,
                          t_stop_s=0.50)
    t_raw, i_raw = run_spice(netlist, "rect_3ph_10mH")
    t_uni, i_uni = resample_uniform(t_raw, i_raw, dt=20e-6)
    t_ss, i_ss = grab_steady_state(t_uni, i_uni, f_line, n_cycles=4)
    rms_spice = float(np.sqrt(np.mean(i_ss * i_ss)))
    print(f"   SPICE: I_rms = {rms_spice:.3f} A   I_pk = {float(np.max(np.abs(i_ss))):.2f} A")

    pct_Z = (omega * L_H * rms_spice) / (V_LL / math.sqrt(3.0)) * 100.0
    spec_3 = Spec(topology="line_reactor", n_phases=3,
                  Vin_nom_Vrms=V_LL, I_rated_Arms=rms_spice,
                  pct_impedance=pct_Z, f_line_Hz=f_line)
    L_mH = lr.required_inductance_mH(spec_3)
    t_mod, i_mod = lr.line_current_waveform(spec_3, L_mH,
                                            n_cycles=5, n_points=len(t_ss))

    spice_pct, thd_spice = harmonic_spectrum(t_ss, i_ss, f_line)
    model_pct, thd_model = harmonic_spectrum(t_mod, i_mod, f_line)

    print("   Pulsim ...")
    pulsim_run = run_pulsim_3ph(V_LL, f_line, L_H, C_dc_F_3, R_load_3,
                                t_stop_s=0.40, dt=20e-6)
    pulsim_pct: np.ndarray | None = None
    thd_pulsim = 0.0
    if pulsim_run is not None:
        t_p, i_p = pulsim_run
        t_p_uni, i_p_uni = resample_uniform(t_p, i_p, dt=20e-6)
        t_p_ss, i_p_ss = grab_steady_state(t_p_uni, i_p_uni, f_line, n_cycles=4)
        rms_pulsim = float(np.sqrt(np.mean(i_p_ss * i_p_ss)))
        print(f"   Pulsim: I_rms = {rms_pulsim:.3f} A   I_pk = "
              f"{float(np.max(np.abs(i_p_ss))):.2f} A")
        pulsim_pct, thd_pulsim = harmonic_spectrum(t_p_ss, i_p_ss, f_line)

    print(f"   THD: spice={thd_spice:.1f}%  model={thd_model:.1f}%"
          + (f"  pulsim={thd_pulsim:.1f}%" if pulsim_pct is not None else ""))
    print("   h     spice    model" + ("    pulsim" if pulsim_pct is not None else ""))
    for h in (1, 3, 5, 7, 9, 11, 13):
        line = f"   {h:>3}   {spice_pct[h-1]:>5.1f}%  {model_pct[h-1]:>5.1f}%"
        if pulsim_pct is not None:
            line += f"   {pulsim_pct[h-1]:>5.1f}%"
        print(line)
        row = f"3ph,{h},{spice_pct[h-1]:.2f},{model_pct[h-1]:.2f}"
        if pulsim_pct is not None:
            row += f",{pulsim_pct[h-1]:.2f}"
        summary_rows.append(row)

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(10, 7), tight_layout=True)
    ax_top.plot(t_ss * 1000, i_ss, label="ngspice (fase A)", color="#a01818", linewidth=1.6)
    ax_top.plot(t_mod * 1000, i_mod, label="modelo analítico",
                color="#3a78b5", linewidth=1.4, alpha=0.85)
    if pulsim_pct is not None:
        ax_top.plot(t_p_ss * 1000, i_p_ss, label="Pulsim",
                    color="#1c7c3b", linewidth=1.3, alpha=0.85, linestyle="--")
    ax_top.set_xlabel("t [ms]")
    ax_top.set_ylabel("i_a [A]")
    ax_top.set_title(f"3-fase, 380 V_LL, L=10 mH/fase, C={C_dc_F_3*1e6:.0f} µF — I_rms ≈ {rms_spice:.2f} A")
    ax_top.grid(True, alpha=0.4); ax_top.legend()
    if pulsim_pct is not None:
        width = 0.27
        ax_bot.bar(h_axis - width, spice_pct, width=width, label="ngspice", color="#a01818")
        ax_bot.bar(h_axis,         model_pct, width=width, label="modelo",  color="#3a78b5")
        ax_bot.bar(h_axis + width, pulsim_pct, width=width, label="Pulsim",  color="#1c7c3b")
    else:
        width = 0.4
        ax_bot.bar(h_axis - width/2, spice_pct, width=width, label="ngspice", color="#a01818")
        ax_bot.bar(h_axis + width/2, model_pct, width=width, label="modelo",  color="#3a78b5")
    ax_bot.set_xlabel("Ordem harmônica")
    ax_bot.set_ylabel("% do fundamental")
    ax_bot.set_xticks(h_axis)
    ax_bot.grid(True, axis="y", alpha=0.4); ax_bot.legend()
    title_extra = (
        f"  pulsim={thd_pulsim:.1f}%" if pulsim_pct is not None else ""
    )
    ax_bot.set_title(
        f"Espectro — THD spice={thd_spice:.1f}%  modelo={thd_model:.1f}%{title_extra}"
    )
    fig.savefig(OUT_DIR / "spice_3ph_380V_30A_10mH.png", dpi=120)
    plt.close(fig)
    print(f"   wrote {OUT_DIR / 'spice_3ph_380V_30A_10mH.png'}")

    (OUT_DIR / "spice_compare_summary.csv").write_text(
        "\n".join(summary_rows) + "\n", encoding="utf-8",
    )
    print(f"\nsummary CSV: {OUT_DIR / 'spice_compare_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
