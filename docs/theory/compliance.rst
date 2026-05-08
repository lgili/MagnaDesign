Compliance derivations
======================

MagnaDesign's compliance dispatcher
(:mod:`pfc_inductor.compliance`) runs three regulatory checks
today; each chapter below derives the limit table from the
authoritative standard text.

IEC 61000-3-2 (Class D harmonics)
---------------------------------

Class D applies to single-phase equipment ≤ 16 A per phase
whose input current waveform falls inside the special envelope
(PCs, TVs, lighting, diode-rectifier-cap drives — the bulk of
this app's reactor target population).

Per-harmonic limit:

.. math::

   I_n^{\\max} = \\min\\left(
     \\mathrm{Factor}_n \\cdot \\frac{P_i}{1\\,000},\\;
     I_{\\mathrm{abs}, n}
   \\right)

where ``Factor_n`` is in mA/W and ``P_i`` is the apparent input
power in W. Table 3 of the standard fixes the factors for
``n ∈ {3, 5, 7, 9, 11}``; for ``n = 13..39`` (odd) the factor
decays as ``num/n`` where the numerator depends on the edition:

- **Edition 4.0** (≤ 2018): ``num = 3.85``.
- **Edition 5.0** (post-2018): ``num = 3.65``. (Tighter.)

Implementation: :mod:`pfc_inductor.standards.iec61000_3_2`.
Limit-table anchors verified by ``tests/test_iec61000_3_2.py``.

EN 55032 (conducted EMI, 150 kHz – 30 MHz)
------------------------------------------

EN 55032:2017 caps the conducted noise voltage at the LISN
across two classes:

- **Class A** — industrial / commercial. 79–73 dBµV QP
  / 66–60 dBµV AV across the band.
- **Class B** — residential / appliance. 10 dB tighter; the
  150 kHz – 500 kHz region uses log-linear decay from
  66 dBµV at 150 kHz to 56 dBµV at 500 kHz.

MagnaDesign ships an analytical envelope:

.. math::

   V_{\\mathrm{LISN}}(n) =
     V_n^{\\mathrm{source}}
     \\cdot \\frac{Z_{\\mathrm{LISN}}}{Z_{\\mathrm{LISN}} + Z_{\\mathrm{Cp}}(n)}
     \\cdot 10^{-\\mathrm{filter\\_atten}/20}

with ``Z_LISN = 50 Ω`` and ``Z_Cp(n) = 1 / (j ω_n Cp)``. The
``filter_attenuation_dB`` parameter (default 60 dB matching a
two-stage CISPR filter) accounts for the input-filter network
the LISN measurement is taken downstream of.

The estimator is documented as **first-order envelope only**.
Real-world certification needs LISN + spectrum-analyser
measurement at the production controller bandwidth. The
calibration target is ±10 dB vs. bench measurement; the
``add-validation-reference-set`` notebooks (Phase 2) close the
loop.

Implementation: :mod:`pfc_inductor.standards.en55032`. Anchors
+ contract tests in ``tests/test_en55032.py``.

UL 1411 (US insulation envelope)
--------------------------------

UL 1411:2024 covers transformers and motor-supplies for
audio / radio / TV-class appliances. The two checks relevant
to a PFC stage:

- **Temperature rise** (§39.2). Class A / B / F / H insulation
  caps the winding rise above ambient at 65 / 90 / 115 / 140 °C
  respectively. The validity envelope tracks the magnet wire's
  recognised insulation system per UL 1446.
- **Hi-pot test voltage** (§40):

  .. math::

     V_{\\mathrm{hipot}} = 2 \\cdot V_{\\mathrm{work}} + 1\\,000\\;
     \\mathrm{Vrms,\\ 60\\ s}

  Required for any winding above 30 V; below that the test is
  typically waived per §40.1.

The dispatcher defaults the insulation class to ``B``
(130 °C-rated magnet wire — the appliance-grade choice). Real
designs may use Class F (155 °C) or H (180 °C) — surfaced via
the upcoming ``Spec.insulation_class`` field.

Implementation: :mod:`pfc_inductor.standards.ul1411`. Anchors
in ``tests/test_ul1411.py``.

What's not in the dispatcher (yet)
----------------------------------

The list grows as the validation reference set lands its
bench data. Queued additions:

- **IEC 60335-1** — touch-current, isolation, hi-pot under
  fault for household appliances. Stub in
  ``add-compliance-report-pdf`` Phase 4.
- **CISPR 14** — radiated + conducted EMI for household
  appliances. Different limit table than EN 55032.
- **IEEE 1547 / IEC 61727** — grid-tie inverter
  interconnection limits. Lights up when
  ``add-lcl-grid-tie-filter`` lands.

Until then, the dispatcher's ``applicable_standards`` returns
the live list per (topology, region) pair so a CI script can
branch on what's checked vs. what's queued.
