"""Shared helpers used by every CLI subcommand.

Centralised so each subcommand stays a 30-line click definition
plus a short call into the engine.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import click

from pfc_inductor.data_loader import (
    ensure_user_data,
    load_cores,
    load_materials,
    load_wires,
)
from pfc_inductor.errors import DesignError
from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.project import ProjectFile, load_project


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LoadedProject:
    """Result of resolving a ``.pfc`` file into a runnable design.

    Carries the project file metadata + the *resolved* objects from
    the catalogue, so subcommands don't have to re-do the lookup.
    Lookup failures fall back to engine-friendly defaults instead
    of crashing — the engine reports "no material selected" much
    more meaningfully than a KeyError ever could.
    """

    project: ProjectFile
    spec: Spec
    materials: list[Material]
    cores: list[Core]
    wires: list[Wire]
    selected_material: Optional[Material]
    selected_core: Optional[Core]
    selected_wire: Optional[Wire]


def load_session(path: Path) -> LoadedProject:
    """Load a `.pfc` and resolve its selection IDs against the catalogue.

    Raises :class:`click.UsageError` when the file is missing or the
    JSON is malformed — those are user errors, surfaced cleanly.
    """
    if not path.is_file():
        raise click.UsageError(f"Project file not found: {path}")
    try:
        project = load_project(path)
    except (OSError, ValueError) as exc:
        raise click.UsageError(
            f"Could not read {path}: {exc}",
        ) from exc

    ensure_user_data()
    materials = load_materials()
    cores = load_cores()
    wires = load_wires()

    sel = project.selection
    return LoadedProject(
        project=project,
        spec=project.spec,
        materials=materials,
        cores=cores,
        wires=wires,
        selected_material=_find_by_id(materials, sel.material_id),
        selected_core=_find_by_id(cores, sel.core_id),
        selected_wire=_find_by_id(wires, sel.wire_id),
    )


def _find_by_id(items: Iterable[Any], target_id: str) -> Optional[Any]:
    if not target_id:
        return None
    for item in items:
        if getattr(item, "id", None) == target_id:
            return item
    return None


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------
def emit(payload: Any, *, pretty: bool, fp: Any = None) -> None:
    """Write ``payload`` to ``fp`` (default stdout) as JSON or
    pretty-printed text depending on the user's flag.

    JSON is the default because the CLI's primary audience is CI
    pipelines. ``--pretty`` exists for humans running interactive
    spot-checks; it uses Click's terminal-colour helpers when
    available.
    """
    out = fp if fp is not None else sys.stdout
    if pretty:
        _emit_pretty(payload, out)
    else:
        json.dump(_to_jsonable(payload), out, default=_to_jsonable, indent=2)
        out.write("\n")


def _to_jsonable(value: Any) -> Any:
    """Coerce engine objects to JSON-friendly primitives.

    Pydantic models get ``.model_dump()``; dataclasses get a dict;
    floats stay floats; numpy / pandas types are normalised.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "_asdict"):
        return value._asdict()
    if hasattr(value, "tolist"):  # numpy arrays
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    return value


def _emit_pretty(payload: Any, out: Any) -> None:
    """Render a small dict / mapping as ``key: value`` lines.

    Subcommands needing rich tables can build them with their own
    helpers; this is the lowest-common-denominator pretty-printer
    used by ``design`` and similar key-value summaries.
    """
    if isinstance(payload, dict):
        width = max((len(str(k)) for k in payload.keys()), default=0)
        for k, v in payload.items():
            click.echo(f"{str(k).ljust(width)}  {_format_value(v)}", file=out)
        return
    click.echo(str(payload), file=out)


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        # Engineering precision — 4 sig-fig is plenty for stdout
        # spot-checks; full precision is in JSON mode.
        return f"{value:.4g}"
    if isinstance(value, list):
        return f"[{len(value)} items]"
    return str(value)


# ---------------------------------------------------------------------------
# Error wrapping
# ---------------------------------------------------------------------------
def wrap_design_error(func):
    """Decorator: convert :class:`DesignError` into a Click usage error.

    DesignError is the engine's "your inputs are bad" exception; the
    user benefit of catching it here is that the CLI reports the
    engine's hint message verbatim instead of dumping a traceback.
    """

    def _wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DesignError as exc:
            raise click.UsageError(exc.user_message()) from exc

    _wrapped.__name__ = func.__name__
    _wrapped.__doc__ = func.__doc__
    return _wrapped
