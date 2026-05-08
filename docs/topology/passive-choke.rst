Passive choke
=============

A line-frequency PFC choke without active switching — the
input is a diode bridge + smoothing capacitor, the choke
shapes the input current to a tighter window than the
unfiltered diode-bridge would draw.

Operating regime
----------------

50 / 60 Hz line frequency; the choke sees a quasi-rectangular
current pulse during the cap-charging window. The DC-bias H
is high (large peak current) but the AC excursion ΔB is small
— so saturation drives the design, not core loss.

Where it lives in the code
--------------------------

``pfc_inductor/topology/passive_choke.py`` shares 80 % of the
maths with the line reactor but with different default
ranges (smaller L, larger I_rated). The harmonic spectrum is
the same 6k±1 / 2k±1 shape as the line reactor; the
compliance dispatcher routes both topologies through the same
``evaluate_compliance`` call.

When to choose passive choke vs. line reactor
---------------------------------------------

Same physics, different design intent:

- **Line reactor** — explicit harmonic-attenuation target.
  Spec.L_req_mH is the design knob; user thinks in %Z.
- **Passive choke** — implicit cap-charge-shape target. The
  spec drives ``Pout`` and the choke just has to clear the
  Bsat envelope at the worst-case operating point.

The two topologies are kept separate because the GUI's
worst-case operating-point selection differs (the line reactor
worst case sits at the rectifier's rms current peak; the
passive choke at the cap-charge transient peak).
