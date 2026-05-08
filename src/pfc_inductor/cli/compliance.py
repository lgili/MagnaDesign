"""``magnadesign compliance`` subcommand.

Runs the standards dispatcher on a `.pfc` project and either:

- prints the overall verdict + per-standard conclusions
  (default JSON, ``--pretty`` flips to a human table), and / or
- writes a PDF compliance report to ``--out``.

Exit codes
----------

- ``0`` — every applicable standard PASSES (or returns
  ``MARGINAL`` when ``--allow-marginal`` is set).
- ``2`` (``COMPLIANCE_FAIL``) — at least one standard returned
  ``FAIL`` or ``MARGINAL`` without the allow flag.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.cli.utils import load_session, wrap_design_error
from pfc_inductor.compliance import evaluate


def register(group: click.Group) -> None:
    group.add_command(_compliance_cmd)


@click.command(name="compliance")
@click.argument(
    "project_file",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
)
@click.option(
    "--region",
    type=click.Choice(["EU", "US", "BR", "Worldwide"], case_sensitive=False),
    default="Worldwide",
    show_default=True,
    help="Drives which standards apply. Today only IEC 61000-3-2 "
    "is wired (EU / Worldwide / BR all route through Class D).",
)
@click.option(
    "--edition",
    type=click.Choice(["4.0", "5.0"]),
    default="5.0",
    show_default=True,
    help="IEC 61000-3-2 edition. 5.0 (post-2018) tightens the high-order harmonic factor.",
)
@click.option(
    "--out",
    "pdf_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="When provided, write a PDF compliance report to this "
    "path. Otherwise only the JSON / pretty summary prints.",
)
@click.option(
    "--allow-marginal/--strict",
    default=False,
    show_default=True,
    help="With ``--allow-marginal`` a MARGINAL verdict still exits "
    "with code 0; default ``--strict`` treats MARGINAL as FAIL "
    "(suitable for go / no-go release gates).",
)
@click.option(
    "--pretty/--json",
    default=False,
    help="Render summary as a key-value table (--pretty) or as JSON (default).",
)
@click.pass_context
@wrap_design_error
def _compliance_cmd(
    ctx: click.Context,
    project_file: Path,
    region: str,
    edition: str,
    pdf_path: Optional[Path],
    allow_marginal: bool,
    pretty: bool,
) -> int:
    """Run regulatory checks on PROJECT_FILE.

    Combines the engine's harmonic spectrum with the
    standards-side limit tables (``pfc_inductor.standards``)
    and emits a single verdict per applicable standard plus
    an overall verdict the calling CI script can branch on.
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
            f"Open the project in the GUI to pick the missing items.",
        )

    # Run the engine first — the dispatcher needs a DesignResult
    # to extract the harmonic spectrum from. We import here so
    # the CLI startup stays Qt-free until the GUI path opts in.
    from pfc_inductor.design import design as run_design

    result = run_design(
        loaded.spec,
        loaded.selected_core,
        loaded.selected_wire,
        loaded.selected_material,
    )

    bundle = evaluate(
        loaded.spec,
        loaded.selected_core,
        loaded.selected_wire,
        loaded.selected_material,
        result,
        project_name=loaded.project.name,
        region=region,  # type: ignore[arg-type]  # narrowed below
        edition=edition,  # type: ignore[arg-type]
    )

    payload = {
        "project": bundle.project_name,
        "topology": bundle.topology,
        "region": bundle.region,
        "overall": bundle.overall,
        "standards": [
            {
                "standard": s.standard,
                "edition": s.edition,
                "scope": s.scope,
                "conclusion": s.conclusion,
                "summary": s.summary,
                "rows": [
                    {
                        "label": label,
                        "value": value,
                        "limit": limit,
                        "margin_pct": margin,
                        "passed": passed,
                    }
                    for (label, value, limit, margin, passed) in s.rows
                ],
                "notes": list(s.notes),
            }
            for s in bundle.standards
        ],
    }

    if pdf_path is not None:
        from pfc_inductor.compliance.pdf_writer import write_compliance_pdf

        try:
            from importlib.metadata import version as _version

            app_version = _version("magnadesign")
        except Exception:
            app_version = ""
        out = write_compliance_pdf(
            bundle,
            pdf_path,
            app_version=app_version,
        )
        click.echo(f"PDF → {out}", err=True)
        payload["pdf_path"] = str(out)

    if pretty:
        _emit_pretty(payload)
    else:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")

    overall = bundle.overall
    if overall == "PASS":
        ctx.exit(int(ExitCode.OK))
    if overall == "MARGINAL" and allow_marginal:
        ctx.exit(int(ExitCode.OK))
    if overall == "NOT APPLICABLE":
        # Nothing was evaluated — exit code 0 with a stderr
        # warning so the CI script can decide whether silence
        # is acceptable.
        click.echo(
            "::warning::No applicable standards for this topology + region combination.",
            err=True,
        )
        ctx.exit(int(ExitCode.OK))
    # ``ctx.exit`` raises ``click.exceptions.Exit`` so control
    # never falls past the early-returns above. The trailing
    # ``ctx.exit`` here covers the FAIL / MARGINAL-strict path.
    ctx.exit(int(ExitCode.COMPLIANCE_FAIL))
    return int(ExitCode.COMPLIANCE_FAIL)  # unreachable; satisfies type


def _emit_pretty(payload: dict) -> None:
    click.echo(f"project   {payload['project']}")
    click.echo(f"topology  {payload['topology']}")
    click.echo(f"region    {payload['region']}")
    click.echo("")
    overall = payload["overall"]
    marker = {"PASS": "✓", "MARGINAL": "~", "FAIL": "✗"}.get(overall, "?")
    click.echo(f"overall   {marker} {overall}")
    click.echo("")

    for std in payload["standards"]:
        click.echo(f"  {std['standard']} ({std['edition']})")
        click.echo(f"    {std['conclusion']}: {std['summary']}")
        # Show only the worst 5 rows so terminal output stays
        # scannable; the full table is in the JSON / PDF.
        worst = sorted(
            std["rows"],
            key=lambda r: r["margin_pct"],
        )[:5]
        for row in worst:
            mark = "✓" if row["passed"] else "✗"
            click.echo(
                f"    {mark} {row['label']:8s}  "
                f"{row['value']:>9s}  "
                f"limit {row['limit']:>9s}  "
                f"margin {row['margin_pct']:+.1f} %"
            )
        click.echo("")
    if "pdf_path" in payload:
        click.echo(f"PDF       {payload['pdf_path']}")
