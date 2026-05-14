# 05 — Saturation & Rolloff (`μ_eff(H, B, f)`)

**Status**: LIVE
**Code**: `physics/saturation.py`, `pfc_inductor/physics/rolloff.py` (shared with engine)
**Tests**: `tests/test_direct_phase_2_3_2_4_3_1.py`

Magnetic materials don't have a single `μ_r` — the value depends on
DC bias `H`, instantaneous `B`, frequency `f`, and temperature `T`.
This file documents how the direct backend models each effect, when
to apply which, and where to find the catalog data.

## Symbols

| Symbol | Meaning | Units |
|---|---|---|
| `μ_0` | vacuum permeability | 4π×10⁻⁷ H/m |
| `μ_i` | initial (low-signal) relative permeability | — |
| `μ_r,eff` | effective relative permeability at operating point | — |
| `μ_pct` | rolloff fraction (`μ_r,eff / μ_i`) ∈ (0, 1] | — |
| `H` | applied magnetic field (DC bias) | A/m or Oe |
| `B` | flux density in core | T |
| `B_sat` | saturation flux density | T |
| `μ'`, `μ''` | real / imaginary parts of complex permeability | — |
| `OE_PER_AM` | conversion factor A/m → Oe | 0.012566 |

## 1. Why a material has three regimes

The catalog `Material` block can specify any combination of:

| Catalog field | Models | Applies to |
|---|---|---|
| `mu_initial` | flat low-signal `μ` | always; baseline |
| `rolloff` (a, b, c fit) | DC-bias decay `μ(H)` | **powder** (HighFlux, MPP, Kool-Mu) |
| `Bsat_100C_T` (+ knee model) | soft saturation knee | ferrite (no explicit μ(H)) |
| `complex_mu_r` (f-table) | frequency-dependent loss + dispersion | high-frequency ferrite |

The right model depends on the **operating regime** of the design:

- Low-frequency reactor at line freq (60 Hz): `mu_initial` is enough.
- Boost-PFC inductor under DC bias: `rolloff` (powder) **or** soft
  knee (ferrite) on top of `mu_initial`.
- AC inductor near MHz: `complex_mu_r` for proper `L_ac` and core
  loss.

## 2. DC-bias rolloff (powder cores)

Magnetics, Micrometals, and Hitachi all publish "%μ vs H" curves for
their powder cores. The fit used in the catalog is the classical
3-parameter form:

```
                      1
   μ_pct(H_Oe)  =   ─────────────────
                    a  +  b · H^c


   μ_r,eff      =   μ_pct · μ_initial
```

Typical values from the catalog YAML for Magnetics HighFlux 125µi:

```yaml
rolloff:
  a: 0.974
  b: 0.000196
  c: 1.95
```

Gives `μ_pct ≈ 0.72` at `H = 50 Oe` (a typical PFC operating point),
matching the datasheet curve to within 2 %.

### 2a. Computing `H` from `(N, I, l_e)`

For aggregate (1-D-circuit) models, `H` is the average along the
magnetic path:

```
H_avg  =  N · I / l_e        (A/m)
H_Oe   =  H_avg · OE_PER_AM  (≈ H_avg / 79.58)
```

For toroidal cores the actual H varies as `1/r`, but Magnetics's
rolloff fits are calibrated against `H_avg` (a deliberate choice in
their datasheet), so the aggregate form is the right input.

### 2b. Self-consistent solve

In an ideal world, `H = N·I/l_e` doesn't depend on `μ`, so a single
pass gives `μ_r,eff`. In reality, `B = μ_r,eff · μ_0 · H` and the
"effective `H`" depends on flux distribution — but for the aggregate
model (which is what the catalog rolloff is fit against), one pass
converges by construction.

The wrapper `solve_self_consistent_mu` (`saturation.py:115`) exists
for future B-dependent `μ(B)` paths but currently runs a single pass.

## 3. Ferrite soft-knee (no rolloff data)

MnZn ferrites (3C90, 3C94, N87, N97) don't publish `μ(H)` curves
because they're designed for AC service where the swing dominates.
For DC-biased operation we use a polynomial knee:

```
                            1
   μ_eff / μ_i  =   ─────────────────────
                    1  +  (B / B_sat)^N


   N  ≈  4 – 6        (sharper knee = larger N)
```

At `B = 0.7 · B_sat`, `μ_eff ≈ 0.84 · μ_i` (gentle drop).
At `B = B_sat`, `μ_eff = 0.5 · μ_i` (knee).
At `B = 1.2 · B_sat`, `μ_eff ≈ 0.21 · μ_i` (fully saturated).

`ferrite_saturation_factor` (`saturation.py:143`). Used by the
transient solver (`physics/transient.py`) and the PDF report's
saturation-margin warning. The reluctance solver does NOT apply this
by default — instead, it flags `B_pk > 0.8 · B_sat` as a design
warning so the user picks a different core.

## 4. Complex `μ_r` (frequency-dependent)

For ferrites operated above ~100 kHz, `μ'` (real part) drops and
`μ''` (imaginary part) rises — both contribute to AC inductance and
core loss. The catalog ships a table:

```yaml
complex_mu_r:
  - [10e3,   2200, 5]      # f_Hz, mu_prime, mu_double_prime
  - [100e3,  2150, 12]
  - [500e3,  1900, 80]
  - [1e6,    1300, 300]
```

The interpolation is linear in `log_10(f)`:

```python
def complex_mu_r_at(material, frequency_Hz) -> (μ', μ''):
    pts = sorted(material.complex_mu_r)
    # Below first / above last → clamp
    # Otherwise interpolate in log-f
    log_f = log10(frequency_Hz)
    return linear_interp(log_f, pts in log10-f)
```

`saturation.py:35`. The AC pass in the runner applies this to scale
`L_ac` and adjust core loss:

```
L_ac(f)  =  L_dc · (μ'(f) / μ_initial)
core loss adjustment via μ''/μ'  (loss tangent)
```

## 5. The full decision tree in code

```python
def compute_mu_eff_dc_bias(material, n_turns, current_A, le_m,
                            fallback_mu_r=1.0):
    μ_init = material.mu_initial or material.mu_r or fallback_mu_r or 1.0

    if material.rolloff is None:
        # Si-Fe, ferrite, anything without a μ(H) fit
        return μ_init, 1.0       # no rolloff applied

    # Powder path: aggregate H, lookup rolloff
    H_Am = abs(n_turns * current_A) / max(le_m, 1e-9)
    H_Oe = H_Am * OE_PER_AM
    μ_pct = rolloff_fit(material, H_Oe)
    return μ_init * μ_pct, μ_pct
```

(`saturation.py:74`.)

The companion `complex_mu_r_at(material, f)` runs **independently**
of the DC-bias path — they compose:

```
final L_ac  =  L_dc(N, I_dc) · (μ'(f) / μ_initial)
            =  [A_L · N² · μ_pct(H_dc)] · (μ'(f) / μ_initial)
```

## 6. What "rolloff" doesn't model

- **Temperature**: catalog `mu_initial` is at 25 °C; high-temperature
  decay (~5–15 % at 100 °C for ferrites) is not currently modeled.
  Acceptable because we use `B_sat_100C_T` as the saturation limit,
  which is conservative.
- **Hysteresis**: the rolloff is a single-valued curve; real μ has a
  hysteretic loop. For loss calculation we use Steinmetz separately
  (`pfc_inductor.physics.core_loss`) — see `docs/theory/steinmetz-igse.rst`.
- **Anisotropy**: Si-Fe laminations are anisotropic (grain-oriented vs
  non-oriented), but our catalog ships `μ_initial` for the rolling
  direction only. Cross-grain operation isn't modeled.

## 7. Material-type → which model fires

| `material.type` | DC-bias model | Sat knee | Complex μ |
|---|---|---|---|
| `powder` | rolloff (a, b, c) | implicit in rolloff | rarely populated |
| `ferrite` | none (or knee on demand) | optional | usually populated |
| `silicon-steel` | none | optional (`Bsat_25C/100C`) | none |
| `amorphous` | none | optional | rare |
| `nanocrystalline` | none | optional | sometimes |

`silicon-steel`, `amorphous`, `nanocrystalline` are also caught by
the closed-magnetic-path gate (see `08-engine-vs-direct-parity.md`
§4) — they don't get auto-gapped because they don't need it.

## 8. Code map

| Symbol | Location |
|---|---|
| `compute_mu_eff_dc_bias` | `physics/saturation.py:74` |
| `solve_self_consistent_mu` | `physics/saturation.py:115` |
| `ferrite_saturation_factor` (knee) | `physics/saturation.py:143` |
| `complex_mu_r_at` (log-f interp) | `physics/saturation.py:35` |
| Underlying rolloff fit / lookup | `pfc_inductor/physics/rolloff.py` |
| `_to_Oe` utility | `physics/saturation.py:171` |
| Caller in reluctance fast path | `physics/reluctance_axi.py:280–293` |
| Caller in toroidal solver | `physics/magnetostatic_toroidal.py` |
| Caller in AC pass | `fea/direct/runner.py:399` |

## 9. References

- Magnetics Inc., *Powder Core Catalogue*, "Permeability vs DC
  magnetizing force" curves (basis for the (a, b, c) fit form).
- Ferroxcube, *Soft Ferrite Data Handbook*, ch. 3 (complex μ tables).
- McLyman, *Transformer and Inductor Design Handbook*, ch. 2
  (saturation knee polynomial).
- `pfc_inductor/physics/rolloff.py` docstring — the canonical fit
  derivation.
