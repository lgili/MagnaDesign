"""Cross-shape benchmark: direct backend vs FEMMT.

Runs both backends on one representative core per shape we
support and prints a comparison table so we can see at a glance
where the direct backend agrees, lags, or exceeds FEMMT.

Picks one ferrite + one powder core for each major shape family
when both are available.

Usage:
    uv run python scripts/benchmark_shapes_vs_femmt.py
    uv run python scripts/benchmark_shapes_vs_femmt.py --json > out.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any, Optional

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.basicConfig(level=logging.WARNING)


# ─── Bench list ────────────────────────────────────────────────────


def _build_bench_list(catalog_cores: list, catalog_mats: list) -> list[dict[str, Any]]:
    """Pick one core per shape family + a couple ferrite/powder variants.

    Each entry has: id, shape, core, material, n_turns, current_A.
    Test point chosen to be sensible for a 500-W PFC drive (small-
    signal-ish, well below saturation).
    """
    bench: list[dict[str, Any]] = []

    def _pick(core_id: str, n_turns: int, current_A: float, label: str | None = None) -> bool:
        try:
            core = next(c for c in catalog_cores if c.id == core_id)
        except StopIteration:
            print(f"!! Missing in catalog: {core_id}", file=sys.stderr)
            return False
        try:
            mat = next(m for m in catalog_mats if m.id == core.default_material_id)
        except StopIteration:
            print(f"!! Missing material for {core_id}: {core.default_material_id}", file=sys.stderr)
            return False
        bench.append(
            {
                "id": core_id,
                "label": label or core_id,
                "shape": str(core.shape).lower(),
                "core": core,
                "material": mat,
                "n_turns": n_turns,
                "current_A": current_A,
            }
        )
        return True

    # Toroidal — powder (Magnetics HighFlux) — direct uses analytical aggregate
    _pick(
        "magnetics-c058150a2-125_highflux",
        n_turns=50,
        current_A=0.5,
        label="Toroid 125-HighFlux (powder, aggregate)",
    )
    # Toroidal — ferrite (Ferroxcube T) — direct uses geometric ln(OD/ID)
    _pick(
        "mas-ferroxcube-t-t-107-65-18---3c90---ungapped",
        n_turns=20,
        current_A=1.0,
        label="Toroid T 107/65/18 3C90 (ferrite, geometric)",
    )

    # PQ (ferrite)
    _pick("tdkepcos-pq-4040-n87", n_turns=39, current_A=8.0, label="PQ 40/40 N87")
    _pick("tdkepcos-pq-3535-n87", n_turns=39, current_A=8.0, label="PQ 35/35 N87")
    _pick("tdkepcos-pq-5050-n87", n_turns=39, current_A=8.0, label="PQ 50/50 N87")

    # E / EE (ferrite)
    _pick("tdkepcos-e-10555-n87", n_turns=40, current_A=5.0, label="E 105/55 N87")

    # EI
    _pick("dongxing-ei3311-50h800", n_turns=30, current_A=3.0, label="EI 33/11 50H800")

    # ETD
    _pick(
        "mas-ferroxcube-etd-etd-29-16-10---3c90---ungapped",
        n_turns=30,
        current_A=4.0,
        label="ETD 29/16/10 3C90",
    )

    # RM
    _pick(
        "mas-ferroxcube-rm-rm-10-i---3c90---ungapped",
        n_turns=25,
        current_A=2.0,
        label="RM 10/I 3C90",
    )

    # P (pot)
    _pick(
        "mas-ferroxcube-p-p-11-7---3c90---ungapped", n_turns=25, current_A=1.5, label="P 11/7 3C90"
    )

    # EP
    _pick(
        "mas-ferroxcube-ep-ep-10---3c90---ungapped", n_turns=25, current_A=1.5, label="EP 10 3C90"
    )

    # EFD
    _pick(
        "mas-ferroxcube-efd-efd-10-5-3---3c90---gapped-0_350-mm",
        n_turns=20,
        current_A=2.0,
        label="EFD 10/5/3 3C90 (0.35 mm gap)",
    )

    return bench


# ─── Backend runners ───────────────────────────────────────────────


def _resolve_engine_gap_mm(entry: dict[str, Any]) -> Optional[float]:
    """Pick a realistic gap to drive BOTH backends with.

    Strategy:
    1. If the catalog ships ``lgap_mm`` (already-gapped core), use it.
    2. If the core is a powder material with distributed gap
       (no discrete cut), use 0.
    3. Otherwise (ungapped ferrite EE/EI/PQ/etc.) use a sensible
       default of 0.5 mm. This is a typical PFC inductor gap and
       avoids the "engine sized 50 mm" trap that happens when the
       default Spec asks for too much L on a small core.

    The point of this benchmark is backend-vs-backend on the
    same physical geometry — not "does each backend agree with
    the engine's L_required". So we set a fixed, realistic gap
    that both can solve.
    """
    core = entry["core"]
    catalog_gap = getattr(core, "lgap_mm", None)
    if catalog_gap and catalog_gap > 0:
        return float(catalog_gap)

    mat = entry["material"]
    if str(getattr(mat, "type", "")).lower() == "powder":
        return None  # distributed gap, no discrete cut

    # Ferrite without catalog gap → assume a typical small PFC gap.
    return 0.5


def _run_direct_one(
    entry: dict[str, Any], wd: Path, gap_mm: Optional[float] = None
) -> dict[str, Any]:
    """Run the direct backend on one entry."""
    from pfc_inductor.data_loader import load_wires
    from pfc_inductor.fea.direct.runner import run_direct_fea

    wire = next(w for w in load_wires() if "AWG18" in w.id)
    direct_wd = wd / "direct"
    direct_wd.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    try:
        res = run_direct_fea(
            core=entry["core"],
            material=entry["material"],
            wire=wire,
            n_turns=entry["n_turns"],
            current_A=entry["current_A"],
            workdir=direct_wd,
            gap_mm=gap_mm,
        )
        wall = time.perf_counter() - t0
        return {
            "L_uH": res.L_dc_uH,
            "B_pk_T": res.B_pk_T,
            "wall_s": wall,
            "gap_mm": gap_mm,
            "error": None,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "wall_s": time.perf_counter() - t0}


def _run_femmt_one(
    entry: dict[str, Any], wd: Path, gap_mm: Optional[float] = None
) -> dict[str, Any]:
    """Run FEMMT on one entry with an explicit gap.

    Constructs a minimal DesignResult with N, I, and gap_actual_mm
    set directly — skips the design() pipeline so we benchmark
    backends on the same geometry instead of comparing the engine's
    L_required convergence.
    """
    from pfc_inductor.data_loader import load_wires
    from pfc_inductor.fea.femmt_runner import validate_design_femmt
    from pfc_inductor.fea.models import FEMMNotAvailable, FEMMSolveError
    from pfc_inductor.models import Spec

    wire = next(w for w in load_wires() if "AWG18" in w.id)
    femmt_wd = wd / "femmt"
    femmt_wd.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    try:
        spec = Spec()  # type: ignore[call-arg]
        # Need a DesignResult; the simplest path is to run design()
        # and patch the relevant fields. If design() fails, fabricate
        # a stub with only the fields FEMMT consults.
        from pfc_inductor.design import design

        try:
            design_result = design(spec, entry["core"], wire, entry["material"])
        except Exception as exc:
            return {"error": f"design() failed: {exc}", "wall_s": time.perf_counter() - t0}

        # Override with the test point.
        updates = {
            "N_turns": entry["n_turns"],
            "I_line_pk_A": float(entry["current_A"]),
            "gap_actual_mm": float(gap_mm) if gap_mm and gap_mm > 0 else 0.0,
        }
        try:
            if hasattr(design_result, "model_copy"):
                design_result = design_result.model_copy(update=updates)
            else:
                for k, v in updates.items():
                    setattr(design_result, k, v)
        except Exception:
            pass

        res = validate_design_femmt(
            spec=spec,
            core=entry["core"],
            wire=wire,
            material=entry["material"],
            result=design_result,
            output_dir=femmt_wd,
        )
        wall = time.perf_counter() - t0
        return {
            "L_uH": res.L_FEA_uH,
            "B_pk_T": res.B_pk_FEA_T,
            "wall_s": wall,
            "gap_mm": gap_mm,
            "error": None,
        }
    except (FEMMNotAvailable, FEMMSolveError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "wall_s": time.perf_counter() - t0}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "wall_s": time.perf_counter() - t0}


# ─── Report ───────────────────────────────────────────────────────


def _fmt(v: Optional[float], precision: int = 2, unit: str = "") -> str:
    if v is None:
        return "      -"
    return f"{v:>7.{precision}f}{unit}"


def _delta_pct(direct: Optional[float], femmt: Optional[float]) -> Optional[float]:
    if direct is None or femmt is None or femmt == 0:
        return None
    return abs(direct - femmt) / abs(femmt) * 100.0


def render_report(rows: list[dict[str, Any]]) -> None:
    """Render the comparison table to stdout."""
    sep = "─" * 110
    print(f"\n{sep}")
    print(
        f"{'Shape':<8}  {'Case':<46}  "
        f"{'L_dir':>10}  {'L_femmt':>10}  {'|ΔL|%':>7}  "
        f"{'t_dir':>9}  {'t_femmt':>9}"
    )
    print(sep)
    for row in rows:
        d = row["direct"]
        f = row["femmt"]
        L_d = d.get("L_uH") if d.get("error") is None else None
        L_f = f.get("L_uH") if f.get("error") is None else None
        Bd = d.get("B_pk_T") if d.get("error") is None else None
        Bf = f.get("B_pk_T") if f.get("error") is None else None
        delta = _delta_pct(L_d, L_f)
        td = d.get("wall_s", 0.0)
        tf = f.get("wall_s", 0.0)
        l_d_str = _fmt(L_d, 2, " μH") if L_d is not None else "  fail"
        l_f_str = _fmt(L_f, 2, " μH") if L_f is not None else "  fail/none"
        d_str = f"{delta:>6.1f}%" if delta is not None else "   -  "
        td_str = f"{td:>7.3f}s" if td else "   -  "
        tf_str = f"{tf:>7.3f}s" if tf else "   -  "
        print(
            f"{row['shape']:<8}  {row['label'][:46]:<46}  "
            f"{l_d_str:>13}  {l_f_str:>13}  {d_str}  "
            f"{td_str}  {tf_str}"
        )
        # B field detail line (indented)
        bd_str = _fmt(Bd, 4, " T") if Bd is not None else "  -"
        bf_str = _fmt(Bf, 4, " T") if Bf is not None else "  -"
        b_delta = _delta_pct(Bd, Bf)
        b_delta_str = f"{b_delta:>6.1f}%" if b_delta is not None else "   -  "
        print(f"{'':<8}  {'  B_pk:':<46}  {bd_str:>13}  {bf_str:>13}  {b_delta_str}")
        # Errors / notes
        if d.get("error"):
            print(f"          ⚠ direct: {d['error'][:88]}")
        if f.get("error"):
            note = f["error"][:88]
            print(f"          ⚠ femmt:  {note}")
    print(sep)

    # Summary stats
    Ldelta = [_delta_pct(r["direct"].get("L_uH"), r["femmt"].get("L_uH")) for r in rows]
    Ldelta = [d for d in Ldelta if d is not None]
    n_compared = len(Ldelta)
    if n_compared:
        Ldelta_sorted = sorted(Ldelta)
        median = Ldelta_sorted[len(Ldelta_sorted) // 2]
        worst = max(Ldelta_sorted)
        best = min(Ldelta_sorted)
        within_5 = sum(1 for d in Ldelta if d < 5)
        within_15 = sum(1 for d in Ldelta if d < 15)
        within_30 = sum(1 for d in Ldelta if d < 30)
        n_total = len(rows)
        n_direct_ok = sum(1 for r in rows if r["direct"].get("error") is None)
        n_femmt_ok = sum(1 for r in rows if r["femmt"].get("error") is None)

        # Timing
        td_vals = [r["direct"].get("wall_s") for r in rows if r["direct"].get("wall_s")]
        tf_vals = [r["femmt"].get("wall_s") for r in rows if r["femmt"].get("wall_s")]
        td_total = sum(v or 0 for v in td_vals)
        tf_total = sum(v or 0 for v in tf_vals)

        print(f"\n  Summary  ({n_total} cases)")
        print("  ─────────────────────────────────────────────────")
        print(f"  Direct backend ran ok:    {n_direct_ok:>2}/{n_total}")
        print(f"  FEMMT backend ran ok:     {n_femmt_ok:>2}/{n_total}")
        print(f"  Comparable (both succeeded): {n_compared:>2}/{n_total}")
        print()
        print(f"  |ΔL| statistics (over {n_compared} comparable cases):")
        print(f"    best:    {best:>5.1f}%")
        print(f"    median:  {median:>5.1f}%")
        print(f"    worst:   {worst:>5.1f}%")
        print(f"    within 5%:   {within_5}/{n_compared}")
        print(f"    within 15%:  {within_15}/{n_compared}")
        print(f"    within 30%:  {within_30}/{n_compared}")
        print()
        print("  Wall time:")
        print(f"    direct total:  {td_total:>7.2f}s ({td_total / max(n_direct_ok, 1):.3f}s avg)")
        print(f"    femmt total:   {tf_total:>7.2f}s ({tf_total / max(n_femmt_ok, 1):.3f}s avg)")
        if td_total > 0 and tf_total > 0:
            print(f"    speedup:       {tf_total / td_total:>7.1f}× (femmt / direct)")
    print()


# ─── Main ──────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the pretty table.",
    )
    ap.add_argument(
        "--skip-femmt",
        action="store_true",
        help="Run only the direct backend (faster smoke test).",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N benchmark cases.",
    )
    args = ap.parse_args()

    from pfc_inductor.data_loader import load_cores, load_materials

    cores = load_cores()
    mats = load_materials()
    bench = _build_bench_list(cores, mats)
    if args.limit:
        bench = bench[: args.limit]

    print(f"Running {len(bench)} benchmark cases...", file=sys.stderr)
    rows: list[dict[str, Any]] = []
    for i, entry in enumerate(bench):
        print(
            f"  [{i + 1}/{len(bench)}] {entry['label']:<55} ", end="", flush=True, file=sys.stderr
        )
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            # Resolve the engine's auto-sized gap once; pass to BOTH
            # backends so they solve the same physical geometry.
            gap_mm = _resolve_engine_gap_mm(entry)
            direct = _run_direct_one(entry, wd, gap_mm=gap_mm)
            print(
                f"direct {'✓' if direct.get('error') is None else '✗'}",
                end="",
                flush=True,
                file=sys.stderr,
            )
            if args.skip_femmt:
                femmt: dict[str, Any] = {"error": "skipped", "wall_s": 0.0}
            else:
                femmt = _run_femmt_one(entry, wd, gap_mm=gap_mm)
                print(
                    f"  femmt {'✓' if femmt.get('error') is None else '✗'} (gap={gap_mm or 0:.3f}mm)",
                    file=sys.stderr,
                )
            rows.append(
                {
                    "shape": entry["shape"],
                    "id": entry["id"],
                    "label": entry["label"],
                    "gap_mm": gap_mm,
                    "direct": direct,
                    "femmt": femmt,
                }
            )

    if args.json:
        # Strip core/material objects (not JSON-serializable)
        print(json.dumps(rows, indent=2, default=str))
    else:
        render_report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
