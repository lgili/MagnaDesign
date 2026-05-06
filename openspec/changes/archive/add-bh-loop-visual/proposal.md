# Add B–H operating loop visualization

## Why

Engineers reading a flux density plot vs. time miss the *shape* of the
operating loop in the B–H plane — the area enclosed corresponds to the
hysteresis loss per cycle, and the trajectory shows how close the design
is to saturation. PLECS, JMAG and Maxwell all expose this view; we don't.

For powder cores with strong DC bias rolloff, the loop is offset to the
right (high H, B following the soft saturation curve). Showing this loop
overlaid on the material's quasi-static B–H curve is a one-glance health
check: if the loop intrudes into the knee, the design is over-saturating.

## What changes

- New plot tab "Loop B–H": dynamic B(t) vs H(t) at the design operating
  point, plotted on top of the material's static B–H curve.
- Two traces: one for the line-frequency envelope (slow loop), one for the
  switching ripple (small loop riding on the envelope).
- Reference curves: anhysteretic B–H (from rolloff μ%(H)·μ_0·H integrated)
  and Bsat horizontal line.
- Annotations: peak (H, B), saturation margin %, hysteresis area =
  per-cycle loss density.

## Impact

- Affected capabilities: NEW `bh-visualization`
- Affected modules: NEW `pfc_inductor/visual/bh_loop.py`,
  `ui/plot_panel.py` (new tab), small change in `physics/rolloff.py` to
  expose the anhysteretic B(H) curve as a callable.
- No new deps. matplotlib is enough.
- Small change, mostly visualization wiring.
