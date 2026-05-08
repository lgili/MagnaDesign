"""Bidirectional adapters between our internal models and MAS-shaped models.

Custom fields and calibrations that don't have direct MAS equivalents are
preserved under the `x-pfc-inductor` namespace, so a round-trip
(internal → MAS → internal) is faithful.
"""

from __future__ import annotations

from typing import Any

from pfc_inductor.models import (
    Core,
    LossDatapoint,
    Material,
    RolloffParams,
    SteinmetzParams,
    Wire,
)
from pfc_inductor.models.mas.types import (
    MasCore,
    MasCoreDimensions,
    MasCoreLoss,
    MasCoreShape,
    MasMaterial,
    MasPermeability,
    MasSaturation,
    MasSteinmetzCoeffs,
    MasWire,
)


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------
def material_to_mas(m: Material) -> MasMaterial:
    """Convert internal Material → MAS-shaped object.

    Steinmetz convention: MAS expects k/alpha/beta with reference frequency
    in Hz and reference flux in T. We convert from our (kHz, mT) anchored
    form on the way out.
    """
    sat = [
        MasSaturation(temperature_C=25.0, magnetic_flux_density_T=m.Bsat_25C_T),
        MasSaturation(temperature_C=100.0, magnetic_flux_density_T=m.Bsat_100C_T),
    ]
    losses: list[MasCoreLoss] = []
    if m.steinmetz is not None:
        losses.append(
            MasCoreLoss(
                method="steinmetz",
                coefficients=MasSteinmetzCoeffs(
                    k=m.steinmetz.Pv_ref_mWcm3,
                    alpha=m.steinmetz.alpha,
                    beta=m.steinmetz.beta,
                ),
                reference_frequency_Hz=m.steinmetz.f_ref_kHz * 1000.0,
                reference_flux_density_T=m.steinmetz.B_ref_mT / 1000.0,
            )
        )

    ext: dict[str, Any] = {"id": m.id}
    if m.rolloff is not None:
        ext["rolloff"] = m.rolloff.model_dump(mode="json")
    if m.steinmetz is not None:
        ext["steinmetz_meta"] = {
            "f_min_kHz": m.steinmetz.f_min_kHz,
            "f_max_kHz": m.steinmetz.f_max_kHz,
        }
    if m.cost_per_kg is not None:
        ext["cost_per_kg"] = m.cost_per_kg
    if m.cost_currency:
        ext["cost_currency"] = m.cost_currency
    if m.loss_datapoints:
        ext["loss_datapoints"] = [dp.model_dump(mode="json") for dp in m.loss_datapoints]

    return MasMaterial(
        name=m.name,
        manufacturer=m.vendor,
        family=m.family,
        type=m.type,
        permeability=MasPermeability(initial_value=m.mu_initial),
        saturation=sat,
        core_losses_methods=losses,
        density_kg_m3=m.rho_kg_m3,
        notes=m.notes,
        x_pfc_inductor=ext,
    )


def material_from_mas(doc: MasMaterial) -> Material:
    """Convert MAS-shaped object → internal Material."""
    bsat_25 = next(
        (s.magnetic_flux_density_T for s in doc.saturation if abs(s.temperature_C - 25) < 1),
        0.4,
    )
    bsat_100 = next(
        (s.magnetic_flux_density_T for s in doc.saturation if abs(s.temperature_C - 100) < 1),
        bsat_25 * 0.85,
    )

    sm = next(
        (m for m in doc.core_losses_methods if m.method == "steinmetz"),
        None,
    )
    ext = doc.x_pfc_inductor or {}
    sm_meta = ext.get("steinmetz_meta", {}) if isinstance(ext, dict) else {}
    if sm is not None and sm.coefficients is not None:
        steinmetz = SteinmetzParams(
            Pv_ref_mWcm3=sm.coefficients.k,
            f_ref_kHz=(sm.reference_frequency_Hz or 100_000.0) / 1000.0,
            B_ref_mT=(sm.reference_flux_density_T or 0.1) * 1000.0,
            alpha=sm.coefficients.alpha,
            beta=sm.coefficients.beta,
            f_min_kHz=sm_meta.get("f_min_kHz", 1.0),
            f_max_kHz=sm_meta.get("f_max_kHz", 500.0),
        )
    else:
        steinmetz = SteinmetzParams(
            Pv_ref_mWcm3=200.0,
            alpha=1.4,
            beta=2.5,
        )

    rolloff_data = ext.get("rolloff") if isinstance(ext, dict) else None
    rolloff = RolloffParams(**rolloff_data) if rolloff_data else None

    ldp = ext.get("loss_datapoints", []) if isinstance(ext, dict) else []
    loss_datapoints = [LossDatapoint(**dp) for dp in ldp]

    mat_id = ext.get("id") if isinstance(ext, dict) else None
    if not mat_id:
        mat_id = f"{_slug(doc.manufacturer)}-{_slug(doc.name)}"

    return Material(
        id=mat_id,
        vendor=doc.manufacturer,
        family=doc.family or "",
        name=doc.name,
        type=doc.type,
        mu_initial=doc.permeability.initial_value,
        Bsat_25C_T=bsat_25,
        Bsat_100C_T=bsat_100,
        rho_kg_m3=doc.density_kg_m3 or 5000.0,
        steinmetz=steinmetz,
        rolloff=rolloff,
        loss_datapoints=loss_datapoints,
        cost_per_kg=ext.get("cost_per_kg") if isinstance(ext, dict) else None,
        cost_currency=ext.get("cost_currency", "USD") if isinstance(ext, dict) else "USD",
        notes=doc.notes,
    )


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
def core_to_mas(c: Core) -> MasCore:
    ext = {"id": c.id}
    if c.cost_per_piece is not None:
        ext["cost_per_piece"] = c.cost_per_piece
    if c.mass_g is not None:
        ext["mass_g"] = c.mass_g
    return MasCore(
        name=c.part_number,
        manufacturer=c.vendor,
        shape=MasCoreShape(
            name=c.part_number,
            family=c.shape,
        ),
        dimensions=MasCoreDimensions(
            Ae_mm2=c.Ae_mm2,
            le_mm=c.le_mm,
            Ve_mm3=c.Ve_mm3,
            Wa_mm2=c.Wa_mm2,
            MLT_mm=c.MLT_mm,
            OD_mm=c.OD_mm,
            ID_mm=c.ID_mm,
            HT_mm=c.HT_mm,
        ),
        material_name=c.default_material_id,
        inductance_factor_nH=c.AL_nH,
        gap_length_mm=c.lgap_mm,
        notes=c.notes,
        x_pfc_inductor=ext,
    )


def core_from_mas(doc: MasCore) -> Core:
    ext = doc.x_pfc_inductor or {}
    core_id = ext.get("id") if isinstance(ext, dict) else None
    if not core_id:
        core_id = f"{_slug(doc.manufacturer)}-{_slug(doc.name)}-{_slug(doc.material_name)}"
    return Core(
        id=core_id,
        vendor=doc.manufacturer,
        shape=doc.shape.family or doc.shape.name,
        part_number=doc.name,
        default_material_id=doc.material_name,
        Ae_mm2=doc.dimensions.Ae_mm2,
        le_mm=doc.dimensions.le_mm,
        Ve_mm3=doc.dimensions.Ve_mm3,
        Wa_mm2=doc.dimensions.Wa_mm2,
        MLT_mm=doc.dimensions.MLT_mm,
        AL_nH=doc.inductance_factor_nH,
        OD_mm=doc.dimensions.OD_mm,
        ID_mm=doc.dimensions.ID_mm,
        HT_mm=doc.dimensions.HT_mm,
        lgap_mm=doc.gap_length_mm,
        cost_per_piece=ext.get("cost_per_piece") if isinstance(ext, dict) else None,
        mass_g=ext.get("mass_g") if isinstance(ext, dict) else None,
        notes=doc.notes,
    )


# ---------------------------------------------------------------------------
# Wire
# ---------------------------------------------------------------------------
def wire_to_mas(w: Wire) -> MasWire:
    return MasWire(
        name=w.id,
        type=w.type,
        awg=w.awg,
        conducting_diameter_mm=w.d_cu_mm,
        insulated_diameter_mm=w.d_iso_mm,
        conducting_area_mm2=w.A_cu_mm2,
        strand_awg=w.awg_strand,
        strand_diameter_mm=w.d_strand_mm,
        number_strands=w.n_strands,
        bundle_diameter_mm=w.d_bundle_mm,
        cost_per_meter=w.cost_per_meter,
        mass_per_meter_g=w.mass_per_meter_g,
        notes=w.notes,
        x_pfc_inductor={"id": w.id},
    )


def wire_from_mas(doc: MasWire) -> Wire:
    ext = doc.x_pfc_inductor or {}
    wid = (ext.get("id") if isinstance(ext, dict) else None) or doc.name
    return Wire(
        id=wid,
        type=doc.type,
        awg=doc.awg,
        d_cu_mm=doc.conducting_diameter_mm,
        d_iso_mm=doc.insulated_diameter_mm,
        A_cu_mm2=doc.conducting_area_mm2,
        awg_strand=doc.strand_awg,
        d_strand_mm=doc.strand_diameter_mm,
        n_strands=doc.number_strands,
        d_bundle_mm=doc.bundle_diameter_mm,
        cost_per_meter=doc.cost_per_meter,
        mass_per_meter_g=doc.mass_per_meter_g,
        notes=doc.notes,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _slug(s: str) -> str:
    out: list[str] = []
    for ch in (s or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in "-_":
            out.append(ch)
        elif ch == " ":
            out.append("-")
    return "".join(out) or "x"
