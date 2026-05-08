"""``magnadesign mfg-spec`` subcommand — vendor manufacturing spec.

Builds the manufacturing-spec payload for a `.pfc` project and
writes either a PDF (vendor-quotable) or XLSX (ERP-friendly)
artefact based on the output extension. Designed for the
"engineer hands the design to a magnetics vendor" workflow.

Examples
--------

::

    magnadesign mfg-spec project.pfc --out spec.pdf
    magnadesign mfg-spec project.pfc --out spec.xlsx
    magnadesign mfg-spec project.pfc --out spec.pdf --designer "Jane Doe" --revision B.1
"""
from __future__ import annotations

from pathlib import Path

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.design import design as run_design


def register(group: click.Group) -> None:
    """Register the ``mfg-spec`` subcommand on the parent group."""
    group.add_command(_mfg_spec_cmd)


@click.command(name="mfg-spec")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Destination file. Extension drives format: "
         "`.pdf` → ReportLab vendor-quotable PDF, "
         "`.xlsx` → openpyxl ERP-friendly workbook.",
)
@click.option(
    "--designer",
    default="—",
    help="Designer name embedded into the cover page.",
)
@click.option(
    "--revision",
    default="A.0",
    help="Revision string for the title block + signature page.",
)
@click.option(
    "--project-name",
    "project_name_override",
    default=None,
    help="Override the project name used on the cover page. "
         "Defaults to the `.pfc` file's `name` attribute.",
)
@wrap_design_error
def _mfg_spec_cmd(
    project_file: Path,
    output_path: Path,
    designer: str,
    revision: str,
    project_name_override: str | None,
) -> int:
    """Generate the vendor manufacturing spec for PROJECT_FILE.

    The output extension picks the format:

    \b
    - ``*.pdf``   → 4-page vendor-quotable PDF (cover, construction,
                   acceptance plan, sign-off).
    - ``*.xlsx``  → workbook with Specs / BOM / Tests sheets for
                   ERP ingest.

    Selection IDs in the project must resolve against the bundled
    catalogue; otherwise the command reports a usage error.
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

    result = run_design(
        loaded.spec,
        loaded.selected_core,
        loaded.selected_wire,
        loaded.selected_material,
    )

    project_name = project_name_override or loaded.project.name

    # Build the payload — pure function, no IO.
    from pfc_inductor.manufacturing import build_mfg_spec
    spec_pack = build_mfg_spec(
        spec=loaded.spec,
        core=loaded.selected_core,
        wire=loaded.selected_wire,
        material=loaded.selected_material,
        result=result,
        project_name=project_name,
        designer=designer,
        revision=revision,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = _detect_format(output_path)
    if fmt == "pdf":
        from pfc_inductor.manufacturing.pdf_writer import write_mfg_spec_pdf
        written = write_mfg_spec_pdf(spec_pack, output_path)
    elif fmt == "xlsx":
        from pfc_inductor.manufacturing.excel_writer import (
            write_mfg_spec_xlsx,
        )
        written = write_mfg_spec_xlsx(spec_pack, output_path)
    else:
        raise click.UsageError(
            f"Unsupported output extension {output_path.suffix!r}. "
            f"Use `.pdf` or `.xlsx`.",
        )

    click.echo(f"Wrote {fmt.upper()} manufacturing spec → {written}",
               err=True)
    if spec_pack.notes:
        for note in spec_pack.notes:
            click.echo(f"  ! {note}", err=True)
    return ExitCode.OK


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".xlsx":
        return "xlsx"
    return "unknown"
