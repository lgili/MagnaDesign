"""``magnadesign datasheet`` subcommand — write a datasheet to disk.

Resolves a `.pfc` project file, runs the engine, hands the
result to either the native PDF generator
(:func:`pfc_inductor.report.pdf_report.generate_pdf_datasheet`)
or the HTML generator
(:func:`pfc_inductor.report.html_report.generate_html_report`)
based on the output file's extension. Designed for CI pipelines
that need a checked-in datasheet alongside every project commit.

Examples
--------

::

    magnadesign datasheet project.pfc --out datasheet.pdf
    magnadesign datasheet project.pfc --out datasheet.html
    magnadesign datasheet project.pfc --out out.pdf --designer "Jane Doe" --revision B.1

Exit codes
----------

- ``0``  — datasheet written successfully.
- ``4``  — usage error (project not found, selection incomplete).
- ``1``  — generic error (engine crash, IO failure).
"""
from __future__ import annotations

from pathlib import Path

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.design import design as run_design


def register(group: click.Group) -> None:
    """Register the ``datasheet`` subcommand on the parent group."""
    group.add_command(_datasheet_cmd)


@click.command(name="datasheet")
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
         "`.pdf` → ReportLab native PDF, anything else → HTML.",
)
@click.option(
    "--designer",
    default="—",
    help="Designer name embedded into the PDF metadata + footer "
         "(PDF format only).",
)
@click.option(
    "--revision",
    default="A.0",
    help="Revision string for the title block (PDF format only).",
)
@click.option(
    "--title",
    default="PFC Inductor Design",
    help="Document title for the HTML report (HTML format only).",
)
@wrap_design_error
def _datasheet_cmd(
    project_file: Path,
    output_path: Path,
    designer: str,
    revision: str,
    title: str,
) -> int:
    """Generate a datasheet for PROJECT_FILE.

    The output file extension picks the format:

    \b
    - ``*.pdf``  → native ReportLab PDF (3 A4 pages: header,
                   construction, BOM/build/test/validation).
    - any other  → HTML datasheet (single self-contained page,
                   embedded matplotlib charts).

    Selection IDs in the project must resolve against the bundled
    catalogue; otherwise the command reports a usage error
    instead of letting the engine crash deeper in the stack.
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = _detect_format(output_path)

    if fmt == "pdf":
        # Lazy import — pulls reportlab + matplotlib which aren't
        # needed for the lighter subcommands.
        from pfc_inductor.report.pdf_report import generate_pdf_datasheet
        written = generate_pdf_datasheet(
            spec=loaded.spec,
            core=loaded.selected_core,
            material=loaded.selected_material,
            wire=loaded.selected_wire,
            result=result,
            output_path=output_path,
            designer=designer,
            revision=revision,
        )
    else:
        from pfc_inductor.report.html_report import generate_html_report
        written = generate_html_report(
            spec=loaded.spec,
            core=loaded.selected_core,
            material=loaded.selected_material,
            wire=loaded.selected_wire,
            result=result,
            output_path=output_path,
            title=title,
        )

    # Stay quiet on stdout (CI scripts log the path; humans see
    # the file appear). Click already swallows return values, so
    # this is purely for the user staring at the terminal.
    click.echo(f"Wrote {fmt.upper()} datasheet → {written}", err=True)
    return ExitCode.OK


def _detect_format(path: Path) -> str:
    """Return ``"pdf"`` for ``*.pdf``, ``"html"`` for anything
    else. Centralised so the command body stays linear."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    return "html"
