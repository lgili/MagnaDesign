"""Domain exception hierarchy.

The UI catches :class:`DesignError` (and subclasses) to show a user-facing
message dialog. Anything that escapes this hierarchy is a real bug —
let it propagate so the developer sees the traceback rather than a
generic "Error" QMessageBox.

Layering rule
-------------

- ``models/`` and ``physics/`` modules: raise ``ValueError`` /
  ``KeyError`` / Pydantic ``ValidationError`` as today. The boundary
  layers translate those into ``DesignError`` subclasses so the UI
  doesn't have to know about Pydantic.
- ``design/`` and ``optimize/``: raise specific :class:`DesignError`
  subclasses where the cause is well-understood (e.g.
  :class:`InfeasibleDesignError`). For unexpected internals, let the
  exception propagate.
- ``ui/``: ``except DesignError as e: QMessageBox.warning(self, ..., str(e))``.
  Never use bare ``except Exception`` for user-facing messaging.

Pattern at the boundary
-----------------------

    from pydantic import ValidationError
    from pfc_inductor.errors import SpecValidationError

    try:
        spec = Spec(**user_inputs)
    except ValidationError as exc:
        raise SpecValidationError(
            "Invalid spec. Check the highlighted fields."
        ) from exc
"""

from __future__ import annotations


class DesignError(Exception):
    """Base for every domain error the UI is allowed to show as a
    friendly message. Carries an optional ``hint`` with a remediation
    string the dialog can append below the main message.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint

    def user_message(self) -> str:
        """Format ``message + hint`` for ``QMessageBox.setText``."""
        if self.hint:
            return f"{self.args[0]}\n\n{self.hint}"
        return str(self.args[0])


class SpecValidationError(DesignError):
    """The spec failed validation (Pydantic, range checks, topology
    cross-field constraints)."""


class CatalogError(DesignError):
    """A material/core/wire id is missing or the JSON catalog is
    malformed."""


class InfeasibleDesignError(DesignError):
    """The selected (spec, core, wire, material) tuple has no feasible
    solution under the engine's constraints — typically saturation,
    window overflow, or thermal runaway."""


class FEABackendError(DesignError):
    """FEA backend (FEMMT/FEMM) is unavailable, misconfigured, or the
    solver returned an error. Distinguished from generic solver bugs:
    these are user-actionable (install ONELAB, switch backend, etc.)."""


class ReportGenerationError(DesignError):
    """HTML/CSV report generation failed at I/O or rendering layer."""


__all__ = [
    "CatalogError",
    "DesignError",
    "FEABackendError",
    "InfeasibleDesignError",
    "ReportGenerationError",
    "SpecValidationError",
]
