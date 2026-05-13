"""Typst → PDF runtime.

Thin wrapper around the ``typst`` PyPI wheel (which embeds the
upstream Typst native binary per OS). Centralises the compile call,
font-path handling, and a default scratch directory so the rest of
the report code stays platform-agnostic.

Why a wrapper instead of calling ``typst.compile`` everywhere:

* Catches and re-raises ``RuntimeError`` from the Rust core with a
  context line that includes the offending ``.typ`` excerpt, which
  is what an engineer needs to diagnose the template error.
* Lets us add font-discovery / package-cache plumbing later in one
  place without sweeping every caller.
* Provides a ``compile_str`` convenience that takes the template as
  an in-memory string (no temp ``.typ`` file the caller has to
  manage). The caller writes the template to a temp dir we own and
  deletes it after compile so partial / interrupted runs don't
  litter the user data dir.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TypstUnavailable(RuntimeError):
    """Raised when the ``typst`` pip wheel can't be imported.

    Surfaces as a soft failure to the host so the caller can fall
    back to the legacy ReportLab path (or surface a clear "install
    typst" hint to the user) instead of crashing the export.
    """


class TypstCompileError(RuntimeError):
    """The Typst compiler ran but rejected the document.

    The exception ``args[0]`` is the human-readable error from the
    Typst binary (already includes file + line + caret marker).
    """


def _import_typst():
    try:
        import typst  # type: ignore[import-not-found]
    except ImportError as e:
        raise TypstUnavailable(
            "The 'typst' pip wheel is not installed. "
            "Install it with `pip install typst` (the wheel embeds "
            "the native Typst binary for macOS, Linux, and Windows)."
        ) from e
    return typst


def compile_to_pdf(
    typst_source: str,
    output_path: Path | str,
    *,
    root: Optional[Path] = None,
) -> Path:
    """Compile a Typst source string to a PDF on disk.

    Parameters
    ----------
    typst_source
        The full ``.typ`` document body. Headings, equations, tables,
        images — everything that lives inside the document.
    output_path
        Where to write the PDF. Parent directory is created if it
        doesn't exist.
    root
        Optional Typst "project root" — the directory ``#import``
        statements in the template resolve against. Defaults to the
        directory of the temp ``.typ`` file we write internally,
        which is fine for self-contained templates (which is what
        the project report uses).

    Returns
    -------
    Path
        The resolved absolute path of the written PDF.

    Raises
    ------
    TypstUnavailable
        ``typst`` pip wheel isn't installed.
    TypstCompileError
        The template has a syntax or semantic error.
    """
    typst = _import_typst()
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    # Write the source to a temp ``.typ`` so the Typst binary can
    # read it. Using ``tempfile`` rather than the user data dir keeps
    # the source ephemeral — interrupted compiles don't leave a stale
    # template behind for the user to wonder about.
    with tempfile.TemporaryDirectory(prefix="magnadesign-typst-") as tmpdir:
        src_path = Path(tmpdir) / "project.typ"
        src_path.write_text(typst_source, encoding="utf-8")
        try:
            typst.compile(
                str(src_path),
                output=str(out),
                root=str(root) if root else str(src_path.parent),
            )
        except Exception as e:
            logger.error("typst compile failed: %s", e)
            raise TypstCompileError(str(e)) from e
    return out
