"""``magnadesign report`` subcommand — bundle every artefact for a project.

The "give me everything" command. Runs the engine once, then
emits the datasheet (PDF), the compliance report (PDF, when the
spec maps to a region), and a JSON KPI summary into a single
output directory. Designed for CI pipelines that want to attach
a complete artefact bundle to every project commit.

Output layout::

    <out-dir>/
        datasheet.pdf
        compliance_<REGION>.pdf       # when applicable
        kpi.json                      # headline KPIs (same shape as `magnadesign design`)
        manifest.json                 # generation metadata + file list

The manifest carries the magnadesign version and a per-file SHA-256
so downstream auditors can verify the bundle hasn't been touched
after the run.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.design import design as run_design


def register(group: click.Group) -> None:
    """Register the ``report`` subcommand on the parent group."""
    group.add_command(_report_cmd)


_REGIONS = ("Worldwide", "EU", "BR", "US")


@click.command(name="report")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Destination directory. Created if it doesn't exist.",
)
@click.option(
    "--region",
    type=click.Choice(_REGIONS, case_sensitive=False),
    default=None,
    help="Compliance region. Omit to skip the compliance report.",
)
@click.option(
    "--edition",
    type=click.Choice(["5.0", "4.0"], case_sensitive=False),
    default="5.0",
    help="IEC 61000-3-2 edition for the compliance report.",
)
@click.option(
    "--designer",
    default="—",
    help="Designer name embedded in the datasheet PDF.",
)
@click.option(
    "--revision",
    default="A.0",
    help="Revision string for the datasheet title block.",
)
@wrap_design_error
def _report_cmd(
    project_file: Path,
    out_dir: Path,
    region: Optional[str],
    edition: str,
    designer: str,
    revision: str,
) -> int:
    """Generate the full artefact bundle for PROJECT_FILE.

    Always writes:

    \b
    - ``datasheet.pdf``  — the customer-facing 3-page PDF.
    - ``kpi.json``       — headline KPIs (same shape as ``design``).
    - ``manifest.json``  — version + SHA-256 per artefact.

    Conditionally writes (when ``--region`` is set):

    \b
    - ``compliance_<REGION>.pdf`` — auditable compliance report
                                    against the region's standards.

    Compliance verdict is reflected in the exit code:
    ``COMPLIANCE_FAIL`` (2) when at least one applicable standard
    fails its envelope check; ``OK`` (0) otherwise.
    """
    loaded = load_session(project_file)

    missing: list[str] = []
    if loaded.selected_material is None:
        missing.append("material")
    if loaded.selected_core is None:
        missing.append("core")
    if loaded.selected_wire is None:
        missing.append("wire")
    if missing:
        raise click.UsageError(
            f"Project has no selection for: {', '.join(missing)}. "
            f"Open the project in the GUI to pick the missing items "
            f"or hand-edit the `.pfc` selection block.",
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_design(
        loaded.spec,
        loaded.selected_core,
        loaded.selected_wire,
        loaded.selected_material,
    )

    artefacts: list[Path] = []
    exit_code = ExitCode.OK

    # 1. Datasheet PDF — always.
    from pfc_inductor.report.pdf_report import generate_pdf_datasheet

    datasheet_path = out_dir / "datasheet.pdf"
    generate_pdf_datasheet(
        spec=loaded.spec,
        core=loaded.selected_core,
        material=loaded.selected_material,
        wire=loaded.selected_wire,
        result=result,
        output_path=datasheet_path,
        designer=designer,
        revision=revision,
    )
    artefacts.append(datasheet_path)

    # 2. KPI JSON — same shape as the `design` subcommand.
    kpi_path = out_dir / "kpi.json"
    kpi = _build_kpi_payload(loaded, result)
    kpi_path.write_text(json.dumps(kpi, indent=2))
    artefacts.append(kpi_path)

    # 3. Compliance PDF — only when --region is set.
    if region is not None:
        from pfc_inductor.compliance.dispatcher import (
            evaluate as evaluate_compliance,
        )
        from pfc_inductor.compliance.pdf_writer import (
            write_compliance_pdf,
        )

        bundle = evaluate_compliance(
            loaded.spec,
            loaded.selected_core,
            loaded.selected_wire,
            loaded.selected_material,
            result,
            region=region,
            edition=edition,
            project_name=loaded.project.name,
        )
        compliance_path = out_dir / f"compliance_{region.upper()}.pdf"
        write_compliance_pdf(bundle, compliance_path)
        artefacts.append(compliance_path)
        if bundle.overall == "FAIL":
            exit_code = ExitCode.COMPLIANCE_FAIL

    # 4. Manifest — always last so it captures every file.
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            _build_manifest(artefacts, loaded.project.name, region),
            indent=2,
        )
    )

    click.echo(
        f"Wrote {len(artefacts) + 1} artefact(s) → {out_dir}",
        err=True,
    )
    return exit_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_kpi_payload(loaded: Any, result: Any) -> dict[str, Any]:
    """Mirror of ``cli.design._design_cmd``'s payload — same shape
    so a script consuming both commands sees identical keys."""
    import math

    def _r(v: float, d: int) -> float:
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            return v
        return round(v, d)

    return {
        "project": loaded.project.name,
        "topology": loaded.spec.topology,
        "selection": {
            "material": loaded.selected_material.name,
            "core": loaded.selected_core.part_number,
            "wire": loaded.selected_wire.id,
        },
        "L_target_uH": _r(result.L_required_uH, 2),
        "L_actual_uH": _r(result.L_actual_uH, 2),
        "N_turns": int(result.N_turns),
        "B_pk_mT": _r(result.B_pk_T * 1000.0, 1),
        "T_winding_C": _r(result.T_winding_C, 1),
        "T_rise_C": _r(result.T_rise_C, 1),
        "P_total_W": _r(result.losses.P_total_W, 3),
        "P_cu_W": _r(result.losses.P_cu_total_W, 3),
        "P_core_W": _r(result.losses.P_core_total_W, 3),
        "feasible": bool(result.feasible) if hasattr(result, "feasible") else None,
        "warnings": list(result.warnings) if result.warnings else [],
    }


def _build_manifest(
    artefacts: list[Path],
    project_name: str,
    region: Optional[str],
) -> dict[str, Any]:
    """Build a metadata dict listing every artefact + SHA-256.

    The hashes let an auditor verify the bundle hasn't been
    silently edited — re-running the manifest generation against
    a tampered file mismatches the recorded hash.
    """
    try:
        from importlib.metadata import version as _v

        magnadesign_version = _v("magnadesign")
    except Exception:
        magnadesign_version = "unknown"

    return {
        "project": project_name,
        "magnadesign_version": magnadesign_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "compliance_region": region,
        "artefacts": [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in artefacts
        ],
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
