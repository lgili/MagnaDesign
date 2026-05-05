# Tasks — B–H loop visualization

## 1. Curve generation

- [x] 1.1 `physics/rolloff.py::B_anhysteretic_T(material, H_Oe)` — analytic
      B(H) from `μ%(H) · μ_0 · H` (with Oe→A/m conversion). Add unit test.
- [x] 1.2 `visual/bh_loop.py::compute_bh_trajectory(design_result, core,
      material, N_points=500)` — returns:
      - `(H_line, B_line)` — slow loop over half line cycle
      - `(H_ripple, B_ripple)` — fast loop over one switching cycle
        sampled at the design's worst-case ripple location
      - `H_array_static, B_static` — anhysteretic curve up to ~3·H_peak
- [x] 1.3 Saturate clamp: if any trajectory point exceeds Bsat, mark it
      with a red "X" annotation.

## 2. Plot

- [x] 2.1 `ui/plot_panel.py`: add new tab "Loop B–H" between "Perdas" and
      "μ% vs H".
- [x] 2.2 Plot layout (single matplotlib axes):
      - Static B–H curve as light-grey line
      - Bsat horizontal dashed line (red)
      - Slow loop in blue, thicker line, alpha 0.8
      - Fast loop ripple in orange, alpha 0.6
      - Operating point marker (peak H, peak B) as a labelled dot
      - x-axis: H [Oe], y-axis: B [mT]
- [x] 2.3 Title: "Loop B–H no operating point — área = perda hysterese
      por ciclo"
- [x] 2.4 Compute and annotate the hysteresis loop area numerically
      (∮ H dB ≈ trapz over the loop).

## 3. Wire-up

- [x] 3.1 `update_plots` in `plot_panel`: invoke `compute_bh_trajectory`
      and feed the new tab's canvas.
- [x] 3.2 Handle no-rolloff materials (ferrites, nano): skip rolloff and
      use linear B = μ_0·μ_r·H.

## 4. Testing

- [x] 4.1 Test: at H=0, B_anhysteretic = 0 for any material with rolloff.
- [x] 4.2 Test: trajectory for a known toroid design has Bpk close to
      `DesignResult.B_pk_T` (within 5%).
- [x] 4.3 Test: hysteresis loop area for a powder core matches
      `Pv_ref · cycle_period · volume` within an order of magnitude.

## 5. Docs

- [x] 5.1 README: add "B–H loop visualization" to feature list.
