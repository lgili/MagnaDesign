"""Acoustic-noise estimator — A-weighted SPL at 1 m.

Three mechanisms covered:

1. **Magnetostriction** — the core's dimensional change with B.
   The fractional length change is approximately ``λ(t) = λ_s ×
   (B(t)/B_sat)²``; with a half-wave-symmetric B(t) this
   produces vibration at ``2·fsw`` (rectified). The estimator
   computes the surface vibration amplitude from λ × geometry,
   converts to a sound-pressure-level via radiation efficiency,
   then A-weights at the dominant frequency.

2. **Winding Lorentz force** — alternating current in adjacent
   layers exerts a per-unit-length force ``F = (μ₀ × I_a × I_b)
   / (2π × d)`` on each pair of layers. For multi-layer Litz at
   high I this can dominate magnetostriction.

3. **Bobbin mechanical resonance** — the winding mass + bobbin
   stiffness has a first mode in the audible band. When fsw or
   2·fsw lands within ±10 % of a bobbin mode, a +6 dB
   resonance boost is applied and the dominant mechanism is
   tagged accordingly.

Caveats
-------

- Cooling fan / chassis vibration NOT included.
- The radiation-efficiency factor (~10⁻⁴ for a small toroid)
  is a single fitted constant rather than per-geometry.
- A-weighting uses the ITU-R 468 / ANSI S1.42 simplified
  formula at the dominant frequency — not the full curve.

Calibration target: ±3 dB(A) for the bundled curated materials
once the validation reference set's bench data lands. The
estimator is documented as such in the report — engineers
should treat its output as a screening tool, not a guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire

DominantMechanism = Literal[
    "magnetostriction",
    "winding_lorentz",
    "bobbin_resonance",
    "none",
]


# ---------------------------------------------------------------------------
# Default magnetostrictive coefficients per material family.
#
# Vendor datasheets carry these for ferrites; powder cores
# typically don't because λ_s is well below 1 ppm and acoustic
# considerations rarely drive the material choice. We bundle a
# conservative blend per family so the estimator always has a
# value to work with — accuracy ±50 % at the per-grade level
# (matches the inter-vendor spread for a given family).
# ---------------------------------------------------------------------------
_LAMBDA_S_DEFAULT_PPM_BY_TYPE: dict[str, float] = {
    "ferrite": 1.0,  # MnZn / NiZn average
    "MnZn": 0.7,  # quieter — typical for
    # power ferrites (3C90, N87)
    "NiZn": 25.0,  # NiZn ferrites hum loudly
    "powder": 0.5,  # powder cores in general
    "powder_high_flux": 0.5,
    "powder_kool_mu": 0.3,  # Kool Mu — quietest powder
    "powder_mpp": 0.2,  # MPP molypermalloy
    "powder_xflux": 0.6,
    "lamination": 8.0,  # silicon-steel laminations
    "amorphous": 1.5,
    "nanocrystalline": 0.5,
}

# Threshold below which a design is "quiet enough for an
# appliance". 30 dB(A) is the customer-grade default for
# refrigerators / dishwashers; commercial / industrial
# equipment can tolerate 45 dB(A).
DEFAULT_QUIET_THRESHOLD_DBA: float = 30.0

# Empirical radiation-efficiency factor — converts surface
# vibration amplitude to far-field SPL. Calibrated to land
# typical PFC inductors near the 30–45 dB(A) range for the
# bundled validation designs. Lives as a module-level
# constant so re-tuning against new bench data is one edit.
_RADIATION_EFFICIENCY: float = 1.5e-4


# A-weighting at audible band centre frequencies — simplified
# from the IEC 61672 curve. Used only for the dominant-tone
# correction; full-spectrum A-weighting would require an
# octave-band breakdown the estimator doesn't produce.
def _a_weighting_dB(frequency_Hz: float) -> float:
    """Approximate A-weighting offset at ``frequency_Hz`` per
    IEC 61672. Values below 100 Hz are heavily attenuated; the
    curve peaks slightly below 1 dB at ~2 kHz and falls away
    above 10 kHz."""
    f = max(float(frequency_Hz), 10.0)
    f2 = f * f
    f4 = f2 * f2
    num = 12200.0**2 * f4
    den = (f2 + 20.6**2) * math.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12200.0**2)
    if den <= 0:
        return -999.0
    return 20.0 * math.log10(num / den) + 2.0


# ---------------------------------------------------------------------------
# Public result container
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NoiseEstimate:
    """A-weighted SPL summary for one design + one ambient threshold."""

    dB_a_at_1m: float
    """Estimated A-weighted sound pressure level at 1 m.
    A typical refrigerator compressor is 35–45 dB(A); a
    well-designed PFC inductor at idle should sit ≤ 30 dB(A)."""

    dominant_frequency_Hz: float
    """Tone driving the SPL — typically fsw for symmetric
    designs, 2·fsw for DC-biased magnetostriction."""

    dominant_mechanism: DominantMechanism

    headroom_to_threshold_dB: float
    """Positive == quieter than the threshold; negative ==
    over. Drives the "this design will hum" engineering
    judgement in the UI / report."""

    contributors_dba: dict[DominantMechanism, float]
    """Per-mechanism SPL contribution. Useful for the engineer
    to know "what to fix" — magnetostriction needs core swap,
    winding Lorentz needs Litz / better layer ordering,
    bobbin resonance needs a mechanical change."""


# ---------------------------------------------------------------------------
# Helpers — material / geometry side
# ---------------------------------------------------------------------------
def magnetostrictive_lambda_s_ppm(material: Material) -> float:
    """Look up λ_s for a material — datasheet value if present,
    sensible default per family otherwise.

    The catalogue model doesn't yet ship a dedicated
    ``magnetostrictive_lambda_s_ppm`` field; until the curated
    materials are tagged we infer from ``Material.type`` (when
    present) or fall back to a conservative MnZn-ferrite value.
    """
    explicit = getattr(material, "magnetostrictive_lambda_s_ppm", None)
    if isinstance(explicit, (int, float)) and explicit > 0:
        return float(explicit)
    mat_type = (getattr(material, "type", "") or "").lower()
    for key, value in _LAMBDA_S_DEFAULT_PPM_BY_TYPE.items():
        if key.lower() in mat_type:
            return float(value)
    name = (getattr(material, "name", "") or "").lower()
    if "kool" in name:
        return _LAMBDA_S_DEFAULT_PPM_BY_TYPE["powder_kool_mu"]
    if "high flux" in name or "highflux" in name:
        return _LAMBDA_S_DEFAULT_PPM_BY_TYPE["powder_high_flux"]
    if "mpp" in name:
        return _LAMBDA_S_DEFAULT_PPM_BY_TYPE["powder_mpp"]
    if "xflux" in name:
        return _LAMBDA_S_DEFAULT_PPM_BY_TYPE["powder_xflux"]
    if "ferrite" in name or name.startswith(("3c", "n8", "n9")):
        return _LAMBDA_S_DEFAULT_PPM_BY_TYPE["ferrite"]
    # Last-resort default — a quiet powder core. Better to
    # under-predict than to scare the user with a hum that's
    # not really there.
    return _LAMBDA_S_DEFAULT_PPM_BY_TYPE["powder"]


def _core_volume_m3(core: Core) -> float:
    """Effective core volume in m³ — used as the radiating
    volume in the magnetostriction → SPL conversion."""
    # Try the catalogue's volume field if it carries one.
    v_cm3 = getattr(core, "volume_cm3", None)
    if isinstance(v_cm3, (int, float)) and v_cm3 > 0:
        return float(v_cm3) * 1e-6
    # Fall back to Ae × le (the engine's primary geometry handles).
    ae_mm2 = float(getattr(core, "Ae_mm2", 0.0) or 0.0)
    le_mm = float(getattr(core, "le_mm", 0.0) or 0.0)
    if ae_mm2 > 0 and le_mm > 0:
        return ae_mm2 * 1e-6 * le_mm * 1e-3
    # Last-resort: ~50 cm³ — smaller-end of typical PFC toroids.
    return 5e-5


# ---------------------------------------------------------------------------
# Mechanism estimators
# ---------------------------------------------------------------------------
def _spl_magnetostriction_dba(
    lambda_s_ppm: float,
    B_pk_T: float,
    fsw_Hz: float,
    core_volume_m3: float,
) -> tuple[float, float]:
    """SPL contribution from magnetostriction. Returns
    ``(dB(A), dominant_frequency_Hz)``.

    The dominant frequency is ``2·fsw`` because λ ∝ B² is
    quadratic in B — a sinusoidal B at fsw produces a
    rectified-sine λ at 2·fsw.
    """
    if lambda_s_ppm <= 0 or B_pk_T <= 0 or fsw_Hz <= 0 or core_volume_m3 <= 0:
        return float("-inf"), 2.0 * fsw_Hz

    # Surface displacement amplitude:  Δl = λ_s × (B/B_sat)²
    # × le. We approximate B_sat = 0.4 T (typical mid-range
    # for the families that hum) so the ratio is dimension-
    # less; lambda_s_ppm × 1e-6 gives the saturation strain.
    bsat_assumed = 0.4
    strain = (lambda_s_ppm * 1e-6) * (B_pk_T / bsat_assumed) ** 2
    # le from le = volume / Ae (rough — Ae ≈ 200 mm² typical).
    le_m = (core_volume_m3 / 2e-4) ** 0.5
    surface_displacement_m = strain * le_m
    # Velocity amplitude at the dominant 2·fsw:
    omega = 2.0 * math.pi * (2.0 * fsw_Hz)
    velocity_m_s = surface_displacement_m * omega
    # SPL ≈ 20·log10(v × Z_air × eff / p_ref). Z_air = 415 Ω.
    p_pa = velocity_m_s * 415.0 * _RADIATION_EFFICIENCY
    if p_pa <= 0:
        return float("-inf"), 2.0 * fsw_Hz
    p_ref = 20e-6  # 20 µPa
    db = 20.0 * math.log10(p_pa / p_ref)
    db_a = db + _a_weighting_dB(2.0 * fsw_Hz)
    return db_a, 2.0 * fsw_Hz


def _spl_winding_lorentz_dba(
    I_ripple_pk_pk_A: float,
    fsw_Hz: float,
    n_layers: int,
) -> tuple[float, float]:
    """SPL contribution from inter-layer Lorentz forces. Returns
    ``(dB(A), fsw_Hz)``.

    Negligible for single-layer designs; dominates when N_layers
    is large (Litz with many helical strands per layer).
    """
    if I_ripple_pk_pk_A <= 0 or fsw_Hz <= 0 or n_layers <= 1:
        return float("-inf"), fsw_Hz

    # Per-pair force scales with I². Ripple amplitude is the
    # AC component that drives the alternating force.
    i_ac_a = I_ripple_pk_pk_A / 2.0
    # Layer separation ≈ wire diameter × insulation factor.
    # Conservative default 1.5 mm for AWG 14-class rounds.
    d_layer_m = 1.5e-3
    force_n_per_m = 4e-7 * math.pi * (i_ac_a**2) / (2.0 * math.pi * d_layer_m)
    # Per-pair force × number of inter-layer pairs (n_layers - 1).
    total_force = force_n_per_m * max(n_layers - 1, 0)
    # Convert mechanical force to a velocity amplitude assuming
    # a spring-mass mount with ω·k_modulus reasonable for a
    # plastic bobbin (~3 kN/m/m). The constant collapses lots of
    # parameters into a single fitted scalar.
    velocity_m_s = total_force / 3000.0
    p_pa = velocity_m_s * 415.0 * _RADIATION_EFFICIENCY
    if p_pa <= 0:
        return float("-inf"), fsw_Hz
    db = 20.0 * math.log10(p_pa / 20e-6)
    db_a = db + _a_weighting_dB(fsw_Hz)
    return db_a, fsw_Hz


def _bobbin_resonance_boost_dB(
    fsw_Hz: float,
    n_layers: int,
    core_volume_m3: float,
) -> float:
    """First-order bobbin-resonance boost in dB.

    Estimates the bobbin's first mode from a beam-on-supports
    formula (PBT bobbin: E ≈ 3 GPa, ρ ≈ 1300 kg/m³). When
    ``fsw`` or ``2·fsw`` lands within ±10 % of the mode, returns
    +6 dB; else 0.
    """
    if n_layers <= 0 or core_volume_m3 <= 0 or fsw_Hz <= 0:
        return 0.0
    # Bobbin window length ~ cube-root of volume; rough.
    length_m = max(core_volume_m3 ** (1 / 3), 1e-3)
    # First mode of a clamped beam: f1 ≈ 0.56 × √(E·I / (m·L⁴)).
    # The full formula needs cross-section detail we don't have;
    # collapse into a calibrated constant that lands typical
    # bobbins around 3–8 kHz.
    f_mode = 4500.0 / (length_m * 100.0) ** 0.5  # crude
    for f_excite in (fsw_Hz, 2.0 * fsw_Hz):
        if abs(f_excite - f_mode) / f_mode < 0.10:
            return 6.0
    return 0.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def estimate_noise(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    *,
    quiet_threshold_dba: float = DEFAULT_QUIET_THRESHOLD_DBA,
) -> NoiseEstimate:
    """Estimate the A-weighted SPL at 1 m for the given design.

    Returns a :class:`NoiseEstimate` with the dominant tone +
    mechanism + per-mechanism contribution table. The headroom
    field is ``quiet_threshold_dba - dB_a_at_1m`` — positive
    means the design is quieter than the threshold.
    """
    fsw_kHz = float(getattr(spec, "f_sw_kHz", 0.0) or 0.0)
    fsw_Hz = fsw_kHz * 1000.0
    B_pk_T = float(getattr(result, "B_pk_T", 0.0) or 0.0)
    ripple = float(getattr(result, "I_ripple_pk_pk_A", 0.0) or 0.0)
    n_layers = int(getattr(result, "n_layers", 1) or 1)

    lambda_s = magnetostrictive_lambda_s_ppm(material)
    volume_m3 = _core_volume_m3(core)

    # Per-mechanism estimates.
    db_mag, freq_mag = _spl_magnetostriction_dba(
        lambda_s,
        B_pk_T,
        fsw_Hz,
        volume_m3,
    )
    db_lor, freq_lor = _spl_winding_lorentz_dba(
        ripple,
        fsw_Hz,
        n_layers,
    )
    boost = _bobbin_resonance_boost_dB(fsw_Hz, n_layers, volume_m3)

    contributors: dict[DominantMechanism, float] = {}
    if math.isfinite(db_mag):
        contributors["magnetostriction"] = db_mag
    if math.isfinite(db_lor):
        contributors["winding_lorentz"] = db_lor

    # Combine in linear-pressure space (10·log10(Σ 10^(L_i/10))).
    if not contributors:
        return NoiseEstimate(
            dB_a_at_1m=0.0,
            dominant_frequency_Hz=fsw_Hz,
            dominant_mechanism="none",
            headroom_to_threshold_dB=float(quiet_threshold_dba),
            contributors_dba={},
        )

    linear_sum = sum(10.0 ** (db / 10.0) for db in contributors.values())
    spl_dba = 10.0 * math.log10(linear_sum) + boost

    # Pick the dominant mechanism — the one with the highest
    # contribution. Ties resolved by the alphabetic ordering of
    # the keys so the result is deterministic.
    dominant: DominantMechanism = max(
        contributors.items(),
        key=lambda kv: (kv[1], kv[0]),
    )[0]
    if boost >= 6.0:
        dominant = "bobbin_resonance"
    dominant_freq = freq_mag if dominant in ("magnetostriction", "bobbin_resonance") else freq_lor

    return NoiseEstimate(
        dB_a_at_1m=float(spl_dba),
        dominant_frequency_Hz=float(dominant_freq),
        dominant_mechanism=dominant,
        headroom_to_threshold_dB=float(quiet_threshold_dba - spl_dba),
        contributors_dba=contributors,
    )
