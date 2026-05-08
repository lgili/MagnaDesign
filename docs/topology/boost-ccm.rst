Boost-PFC (CCM)
===============

The active boost-PFC inductor — single-phase, line-frequency
input, switching at fsw, output a regulated DC bus. Most
common topology in the catalogue and the default for new
projects.

Operating-point math
--------------------

For ``Vin = Vin_min`` (worst-case current) the boost duty
cycle at instantaneous line voltage ``v(t) = √2 · V_in · sin(ω·t)``
is:

.. math::

   D(t) = 1 - \\frac{|v(t)|}{V_{\\mathrm{out}}}

The instantaneous inductor current ripple amplitude is:

.. math::

   \\Delta i_L(t) = \\frac{|v(t)| \\cdot D(t)}{f_{\\mathrm{sw}} \\cdot L}
                  = \\frac{|v(t)|}{f_{\\mathrm{sw}} \\cdot L}
                  \\cdot \\left(1 - \\frac{|v(t)|}{V_{\\mathrm{out}}}\\right)

This peaks at ``|v(t)| = V_out / 2`` — except when ``V_in_pk <
V_out / 2`` (universal-mains low-line case) where the peak is
clamped to the line peak. The engine evaluates both candidates
and takes the worst.

Required inductance
-------------------

For a target peak-to-peak ripple of ``ripple_pct × I_pk``:

.. math::

   L_{\\mathrm{required}} = \\frac{V_{\\mathrm{out}}}
                          {4 \\cdot f_{\\mathrm{sw}} \\cdot \\Delta i_{\\mathrm{pp,target}}}

The factor of 4 comes from the maximum-ripple operating point
above (50 % duty for the low-V_in case).

Where it lives in the code
--------------------------

``pfc_inductor/topology/boost_ccm.py``:

- :func:`pfc_inductor.topology.boost_ccm.operating_point`
  returns ``(I_line_rms, I_line_pk, I_ripple_pk_pk, D_max,
  V_in_design)``.
- :func:`pfc_inductor.topology.boost_ccm.required_inductance`
  computes ``L_required_uH`` from the spec.
- :func:`pfc_inductor.topology.boost_ccm.line_current_waveform`
  synthesises B(t) over one line cycle for the iGSE integral.

VFD modulation
--------------

When ``Spec.fsw_modulation`` is set, the engine evaluates the
design at every fsw point in the band — see
:doc:`/theory/overview` for the dispatch path. The boost-PFC
operating-point math is fsw-linear (``L`` and ``Δi_L`` are
direct inverses of fsw), so the band's worst-case typically
sits at the band edges:

- **Low fsw** → highest core loss per cycle, highest ΔT,
  loudest acoustic noise (see
  :doc:`/topology/boost-ccm`).
- **High fsw** → highest AC copper loss (Dowell proximity
  squared in fsw); on dense Litz this can dominate.

Compliance regime
-----------------

Boost-PFC stages produce sinusoidal line current by control,
so the engine's analytical IEC 61000-3-2 result is
"trivially compliant" — the dispatcher reports PASS with a
``"LISN measurement still required"`` caveat in the notes.
Real-world distortion comes from the controller's bandwidth
(typically 5–10 kHz) which the engine doesn't model.

EN 55032 conducted EMI is the live constraint: a PFC stage
without an input filter exceeds Class B by tens of dB. The
estimator's default 60 dB filter attenuation matches a
typical two-stage CISPR Class B filter; users can override
when they have a measured attenuation curve.

References
----------

- N. Mohan, T. Undeland, W. Robbins, *Power Electronics:
  Converters, Applications and Design*, 3rd ed., Chap. 8.
- L. H. Dixon, "Average Current-Mode Control of Switching
  Power Supplies," Unitrode Application Note U-140.
