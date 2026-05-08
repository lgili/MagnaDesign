"""Variable-frequency-drive (VFD) modulation envelope.

The PFC stage on a compressor inverter / variable-speed drive
operates over a *band* of switching frequencies, not a single
fsw — the modulator dithers fsw to spread EMI, and the
compressor's RPM map drives the band's bounds. A single-point
design picked at, say, 65 kHz can hide failures at the band
edges:

- Low fsw (8 kHz, near the audible band) → highest core loss
  per cycle, audible hum, lowest first-pole impedance.
- Mid fsw (~50 % duty corner) → highest *peak* B because the
  duty crosses 50 % and ripple peaks.
- High fsw (>20 kHz) → AC copper loss dominates; Litz proximity
  effect peaks here.

This module ships the spec-side description of the band. The
engine wrapper that *evaluates* the design across the band
lives in :mod:`pfc_inductor.topology.modulation`.

Profiles
--------

``uniform``
    Evaluate ``n_eval_points`` evenly between ``fsw_min`` and
    ``fsw_max``. Cheapest option; right when the modulator is
    a plain triangular sweep.

``triangular_dither``
    Same set of fsw points as ``uniform`` but weighted toward
    the band edges in the worst-case aggregator (the dither
    spends more time near the limits than the centre).

``rpm_band``
    Compute fsw from the compressor's RPM range via
    :func:`rpm_to_fsw`. Fills in fsw_min / fsw_max from
    ``rpm_min`` / ``rpm_max`` + ``pole_pairs`` so the engineer
    enters the values they actually know (compressor speeds)
    rather than the derived fsw band.

Backward compatibility
----------------------

A ``Spec`` with ``fsw_modulation = None`` (the default) keeps
running through ``design()`` unchanged — every existing `.pfc`
file round-trips identically. Round-trip tests live in
``tests/test_spec_modulation_roundtrip.py``.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


ModulationProfile = Literal["uniform", "triangular_dither", "rpm_band"]


class FswModulation(BaseModel):
    """Description of a switching-frequency band.

    Pydantic v2 model — round-trips through `.pfc` JSON. All
    fields except ``fsw_min_kHz`` / ``fsw_max_kHz`` are optional;
    callers can either set the band directly or let the
    ``rpm_band`` profile derive it from compressor inputs.
    """

    fsw_min_kHz: float = Field(
        ...,
        gt=0.0,
        description="Lower bound of the modulation envelope (kHz).",
    )
    fsw_max_kHz: float = Field(
        ...,
        gt=0.0,
        description="Upper bound of the modulation envelope (kHz).",
    )
    profile: ModulationProfile = Field(
        "uniform",
        description=(
            "How the engine traverses the band. ``uniform`` evenly "
            "samples; ``triangular_dither`` weights the edges; "
            "``rpm_band`` fills the band from the compressor RPM "
            "range below."
        ),
    )
    n_eval_points: int = Field(
        5,
        ge=2,
        le=50,
        description=(
            "Number of fsw points the engine evaluates. 5 is enough "
            "to surface the worst-case envelope on a typical "
            "compressor band; bump to 10–20 for finer resolution."
        ),
    )

    # ---- VFD-specific (only used when ``profile == 'rpm_band'``) ----
    rpm_min: Optional[float] = Field(
        None,
        ge=0.0,
        description=(
            "Compressor minimum speed (RPM). Used with "
            "``pole_pairs`` to derive ``fsw_min_kHz``."
        ),
    )
    rpm_max: Optional[float] = Field(
        None,
        ge=0.0,
        description="Compressor maximum speed (RPM).",
    )
    pole_pairs: Optional[int] = Field(
        None,
        ge=1,
        le=20,
        description=(
            "Motor pole pairs (2 for a typical refrigerator "
            "compressor). Required when profile == 'rpm_band'."
        ),
    )

    @model_validator(mode="after")
    def _check_band(self) -> "FswModulation":
        if self.fsw_max_kHz <= self.fsw_min_kHz:
            raise ValueError(
                f"fsw_max_kHz ({self.fsw_max_kHz}) must exceed "
                f"fsw_min_kHz ({self.fsw_min_kHz})",
            )
        if self.profile == "rpm_band":
            missing: list[str] = []
            if self.rpm_min is None:
                missing.append("rpm_min")
            if self.rpm_max is None:
                missing.append("rpm_max")
            if self.pole_pairs is None:
                missing.append("pole_pairs")
            if missing:
                raise ValueError(
                    f"profile='rpm_band' requires "
                    f"{', '.join(missing)}",
                )
            if self.rpm_max is not None and self.rpm_min is not None:
                if self.rpm_max <= self.rpm_min:
                    raise ValueError(
                        f"rpm_max ({self.rpm_max}) must exceed "
                        f"rpm_min ({self.rpm_min})",
                    )
        return self

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def fsw_points_kHz(self) -> list[float]:
        """Return the fsw points the engine should evaluate.

        For ``uniform`` and ``triangular_dither`` this is a flat
        linear sweep — the *aggregation* (which point dominates
        the worst-case) differs by profile, but the evaluation
        grid is the same. For ``rpm_band`` we also use the
        linear sweep between the derived bounds.
        """
        n = max(int(self.n_eval_points), 2)
        if n == 2:
            return [self.fsw_min_kHz, self.fsw_max_kHz]
        step = (self.fsw_max_kHz - self.fsw_min_kHz) / (n - 1)
        return [self.fsw_min_kHz + i * step for i in range(n)]

    def is_edge_weighted(self) -> bool:
        """Profile aggregator hint — the engine wrapper consults
        this to decide whether worst-case picks the worst point
        across the whole band (False, the default) or only across
        the band edges (True, ``triangular_dither``).
        """
        return self.profile == "triangular_dither"


# ---------------------------------------------------------------------------
# RPM ↔ fsw helper
# ---------------------------------------------------------------------------
def rpm_to_fsw(rpm: float, pole_pairs: int) -> float:
    """Convert a compressor RPM to the PFC stage's switching frequency.

    The relationship in a compressor-inverter PFC isn't fixed — the
    PFC's fsw is independent of the motor's electrical frequency in
    most architectures. This helper assumes the common case where
    the PFC modulator slaves to the motor's electrical frequency
    (the usual choice for cost-sensitive appliance compressors,
    where one timer drives both).

    For dual-loop architectures (independent PFC + inverter timers)
    callers should set ``profile='uniform'`` and supply
    ``fsw_min_kHz`` / ``fsw_max_kHz`` directly instead of letting
    this function derive them.

    Returns the switching frequency in kHz. ``rpm`` of zero
    returns 0 — the engine treats that as below the practical
    minimum and the band's lower bound is then the band's mid-point
    (caller responsibility).
    """
    if rpm <= 0 or pole_pairs <= 0:
        return 0.0
    # Hz = rpm × pole_pairs / 60  (electrical frequency)
    # PFC fsw on a compressor drive runs at ~K × electrical fundamental
    # where K is the carrier ratio (typical 100 for a 50 Hz fundamental
    # → 5 kHz fsw, or 200 for 65 Hz → 13 kHz fsw). We bake K=200 in
    # because that's the universal IEC-compliance-friendly choice for
    # appliance compressors; callers who need a different K should
    # use the ``uniform`` profile.
    K_CARRIER_RATIO = 200
    f_elec_Hz = rpm * pole_pairs / 60.0
    return f_elec_Hz * K_CARRIER_RATIO / 1000.0


def from_rpm_band(
    rpm_min: float,
    rpm_max: float,
    pole_pairs: int,
    *,
    n_eval_points: int = 5,
) -> FswModulation:
    """Convenience constructor: build an ``FswModulation`` from a
    compressor speed band. The user calls this with the values
    they know (RPM range + pole pairs) and the helper fills in
    the derived fsw band.

    Raises ``ValueError`` for non-positive inputs or inverted
    ranges, mirroring the model validator's checks.
    """
    if rpm_min <= 0 or rpm_max <= rpm_min:
        raise ValueError(
            f"invalid RPM band: rpm_min={rpm_min}, rpm_max={rpm_max}",
        )
    if pole_pairs <= 0:
        raise ValueError(f"pole_pairs must be ≥ 1, got {pole_pairs}")
    fsw_min = rpm_to_fsw(rpm_min, pole_pairs)
    fsw_max = rpm_to_fsw(rpm_max, pole_pairs)
    return FswModulation(
        fsw_min_kHz=fsw_min,
        fsw_max_kHz=fsw_max,
        profile="rpm_band",
        n_eval_points=n_eval_points,
        rpm_min=rpm_min,
        rpm_max=rpm_max,
        pole_pairs=pole_pairs,
    )
