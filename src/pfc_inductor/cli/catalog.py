"""``magnadesign catalog`` subcommand — list catalogue entries.

Three sub-resources: ``materials``, ``cores``, ``wires``. Each
emits the bundled catalogue as JSON (default) or CSV (with
``--csv FILE``). Used to:

- Inspect which catalogue rows are available without opening
  the GUI (``magnadesign catalog cores --filter type=toroid``).
- Snapshot the catalogue into a CSV that an Excel pipeline can
  read (``magnadesign catalog materials --csv mats.csv``).

Filter syntax
-------------

``--filter key=value`` matches rows where ``getattr(row, key)``
contains ``value`` (case-insensitive substring match). Repeat
the flag to AND multiple filters. Unknown keys quietly produce
zero matches — same shape as the GUI's filter bar.

Examples
--------

::

    magnadesign catalog materials
    magnadesign catalog cores --filter type=toroid
    magnadesign catalog cores --filter vendor=Magnetics --csv mag.csv
    magnadesign catalog wires --filter d_cu_mm=1.0
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

import click

from pfc_inductor.cli.exit_codes import ExitCode
from pfc_inductor.data_loader import (
    ensure_user_data,
    load_cores,
    load_materials,
    load_wires,
)


_RESOURCES: dict[str, Any] = {
    "materials": load_materials,
    "cores":     load_cores,
    "wires":     load_wires,
}


def register(group: click.Group) -> None:
    """Register the ``catalog`` subcommand on the parent group."""
    group.add_command(_catalog_cmd)


@click.command(name="catalog")
@click.argument(
    "resource",
    type=click.Choice(list(_RESOURCES.keys()), case_sensitive=False),
)
@click.option(
    "--filter",
    "filters",
    multiple=True,
    help="Repeat as ``--filter key=value``. Case-insensitive "
         "substring match. Multiple filters AND together.",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="When set, write CSV to this path. Otherwise emit JSON "
         "on stdout.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Truncate output to the first N rows (after filtering).",
)
def _catalog_cmd(
    resource: str,
    filters: tuple[str, ...],
    csv_path: Optional[Path],
    limit: Optional[int],
) -> int:
    """List catalogue entries for RESOURCE.

    RESOURCE is one of ``materials``, ``cores``, ``wires``.

    Default output is JSON on stdout (machine-friendly). Pass
    ``--csv FILE`` to write a spreadsheet-friendly CSV instead.
    """
    ensure_user_data()
    rows = _RESOURCES[resource]()

    parsed_filters = _parse_filters(filters)
    filtered = list(_apply_filters(rows, parsed_filters))
    if limit is not None and limit >= 0:
        filtered = filtered[:limit]

    payload = [_row_to_dict(r) for r in filtered]

    if csv_path is not None:
        _write_csv(csv_path, payload)
        click.echo(
            f"Wrote {len(payload)} rows → {csv_path}",
            err=True,
        )
    else:
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")

    return ExitCode.OK


def _parse_filters(filters: tuple[str, ...]) -> list[tuple[str, str]]:
    """Parse ``key=value`` strings into ``(key, value)`` tuples.

    Malformed entries (no ``=`` or empty key) are silently
    dropped — the user gets zero matches instead of a hard error
    so the filter syntax stays forgiving in shell scripts.
    """
    out: list[tuple[str, str]] = []
    for raw in filters:
        if "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        out.append((key, value.lower()))
    return out


def _apply_filters(
    rows: Iterable[Any], filters: list[tuple[str, str]],
) -> Iterable[Any]:
    """Yield rows where every filter's substring is contained in
    the row's attribute (case-insensitive)."""
    if not filters:
        yield from rows
        return
    for row in rows:
        if all(_match(row, k, v) for k, v in filters):
            yield row


def _match(row: Any, key: str, needle: str) -> bool:
    raw = getattr(row, key, None)
    if raw is None:
        # Pydantic model_dump fallback so callers can filter on
        # nested keys via the dump'd shape.
        if hasattr(row, "model_dump"):
            raw = row.model_dump().get(key)
    if raw is None:
        return False
    return needle in str(raw).lower()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Coerce a Pydantic / dataclass row into a plain dict for
    JSON / CSV emission."""
    if hasattr(row, "model_dump"):
        return row.model_dump()
    if hasattr(row, "_asdict"):
        return row._asdict()
    return dict(row.__dict__) if hasattr(row, "__dict__") else {"value": row}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write the rows to CSV. Column order follows the keys of
    the first row; subsequent rows pick up extra keys at the end
    so heterogeneous catalogues stay loss-less.

    Empty input writes a header-less zero-byte file — the user
    sees `0 rows` echoed to stderr and the CI script can branch
    on file size.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return

    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # Stringify nested objects so the CSV stays a
            # spreadsheet-friendly flat shape; the JSON output
            # path keeps the nested structure for tools that need
            # it.
            flat = {
                k: _flatten(v) for k, v in row.items()
            }
            writer.writerow(flat)


def _flatten(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return value
