# AC Line Reactor Topology Capability

## ADDED Requirements

### Requirement: Compute line reactor inductance from % impedance

The application SHALL size an AC line reactor by target percentage of
line base impedance, supporting single-phase and three-phase systems
at 50 or 60 Hz.

#### Scenario: 3-phase 380 V / 30 A drive at 5% impedance

- **GIVEN** spec topology is `line_reactor`, n_phases = 3,
  Vin_nom_Vrms = 380 (L-L), I_rated_Arms = 30, pct_impedance = 5,
  f_line_Hz = 60
- **WHEN** the design engine runs
- **THEN** the required inductance is approximately 0.97 mH
- **AND** the predicted voltage drop at rated current is 5%

#### Scenario: 1-phase 220 V / 15 A at 8% impedance

- **GIVEN** topology `line_reactor`, n_phases = 1,
  Vin_nom_Vrms = 220, I_rated_Arms = 15, pct_impedance = 8,
  f_line_Hz = 60
- **WHEN** the design engine runs
- **THEN** the required inductance is approximately 3.1 mH

### Requirement: Compute peak flux from fundamental at line frequency

The line reactor B_pk SHALL be derived from the fundamental flux at
line frequency, not from DC bias rolloff curves which apply only to
powder cores under DC magnetisation.

#### Scenario: B_pk vs N for typical silicon-steel reactor

- **GIVEN** a line reactor design with V_L_rms = 11 V (5% drop on
  220 V), f_line = 60 Hz, Ae = 1000 mm² and N = 30 turns
- **WHEN** the engine computes B_pk
- **THEN** B_pk equals approximately 1.4 T
- **AND** the engine warns when B_pk exceeds the material Bsat margin

### Requirement: Provide THD estimate from selected impedance

The result SHALL include an empirical THD estimate so the engineer
sees the harmonic-mitigation trade-off when picking %Z.

#### Scenario: Higher %Z reduces THD prediction

- **GIVEN** two designs identical except `pct_impedance = 3` and
  `pct_impedance = 8`
- **WHEN** the engine runs both
- **THEN** the 3% design reports THD around 43%
- **AND** the 8% design reports THD around 26%
- **AND** the 8% design also reports a higher voltage drop

### Requirement: Skip irrelevant calculations for line reactor

The engine SHALL skip switching-frequency ripple, AC copper loss
(Dowell) and DC bias rolloff calculations for line reactor designs,
since none of those apply at 50/60 Hz with silicon-steel cores.

#### Scenario: Switching frequency fields ignored

- **GIVEN** a line reactor spec with `f_sw_kHz = 65` (default)
- **WHEN** the engine runs
- **THEN** the result reports `I_ripple_pk_pk_A = 0`
- **AND** `losses.P_cu_ac_W = 0`
- **AND** `losses.P_core_ripple_W = 0`
