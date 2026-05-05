"""Parse the key=value results file written by the FEMM Lua script."""
from __future__ import annotations
from pathlib import Path
from typing import Optional


_REQUIRED_KEYS = ("L_H", "flux_linkage_Wb", "I_test_A", "B_pk_T")


class ResultsParseError(RuntimeError):
    pass


def parse_results_file(path: Path) -> dict[str, float | int | str]:
    """Parse a key=value text file (one entry per line) into a dict.

    Numeric strings are converted to int or float when possible; everything
    else is kept as a string.
    """
    if not Path(path).exists():
        raise ResultsParseError(f"Results file not found: {path}")
    out: dict[str, float | int | str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        out[key] = _coerce(value)
    missing = [k for k in _REQUIRED_KEYS if k not in out]
    if missing:
        raise ResultsParseError(f"Missing keys in results file: {missing}")
    return out


def _coerce(s: str):
    try:
        i = int(s)
        if str(i) == s:
            return i
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s
