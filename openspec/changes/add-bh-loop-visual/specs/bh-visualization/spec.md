# B–H Visualization Capability

## ADDED Requirements

### Requirement: Anhysteretic B(H) curve for any material

The system SHALL expose the static (anhysteretic) B(H) curve for any
material in the database, computed from `μ_fraction(H) · μ_0 · μ_initial · H`
using the calibrated rolloff curve where present, or the linear `μ_0 · μ_r ·
H` fallback for ferrites and nanocrystalline materials.

#### Scenario: Powder core anhysteretic curve

- **GIVEN** a Magnetics High Flux 60µ material with calibrated rolloff
- **WHEN** `B_anhysteretic_T(material, H_Oe=200)` is called
- **THEN** the returned B is between 0.4 and 1.0 T (post-rolloff,
  approaching Bsat)
- **AND** at H=0 the result is 0.0 T

### Requirement: Operating-point B–H loop rendering

The system SHALL render, on the result panel, the B–H trajectory of the
inductor at the design operating point, overlaid on the material's static
B–H curve and the Bsat limit.

#### Scenario: View B–H loop for current design

- **GIVEN** a feasible design is shown
- **WHEN** the user opens the "Loop B–H" tab
- **THEN** the plot shows:
  - the static B–H curve as a reference line
  - a slow loop traced over one half line cycle
  - a small ripple loop overlaid at the location of peak ripple
  - a horizontal Bsat line clearly marked
  - a numeric annotation of the hysteresis-loop area in J/m³

#### Scenario: Saturation visualization

- **GIVEN** a design where the analytic B_pk exceeds Bsat
- **WHEN** the loop is rendered
- **THEN** the trajectory is drawn up to Bsat and marked with a red "X"
  annotation at the breach location
- **AND** a textual warning "Loop entra em saturação" is shown
