"""Standardised exit codes for the headless CLI.

CI pipelines need to distinguish between "the design is bad" and
"the tool blew up", so we adopt a Unix-conventional bucketing:

- ``0  OK``               — happy path, results were produced.
- ``1  GENERIC_ERROR``    — anything we didn't classify (bug, IO).
- ``2  COMPLIANCE_FAIL``  — the design ran but failed a regulatory
                            check (e.g. IEC 61000-3-2 limit
                            exceeded). Surfaced by ``compliance``
                            and ``report`` subcommands once the
                            ``add-compliance-report-pdf`` change
                            lands.
- ``3  WORST_CASE_FAIL``  — the design ran but at least one
                            production-tolerance corner violates
                            spec. Surfaced by ``worst-case`` once
                            ``add-worst-case-tolerance-doe`` lands.
- ``4  USAGE_ERROR``      — bad invocation (missing argument,
                            malformed file). Click already uses 2
                            for usage by default, but we shift
                            ours up so 2/3 stay reserved for the
                            engineering-result classes above.

Why not Click's defaults? Because a CI script that wraps the CLI
needs ``$? == 2`` to mean "compliance failure on a real design",
not "you forgot --top". The shift is small but matters when the
script branches on exit code to decide whether to escalate.
"""
from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    GENERIC_ERROR = 1
    COMPLIANCE_FAIL = 2
    WORST_CASE_FAIL = 3
    USAGE_ERROR = 4


# Human-readable map for ``--help`` and error messages.
EXIT_CODES: dict[ExitCode, str] = {
    ExitCode.OK:               "Successful execution",
    ExitCode.GENERIC_ERROR:    "Generic error (bug, I/O failure)",
    ExitCode.COMPLIANCE_FAIL:  "Design fails a regulatory check",
    ExitCode.WORST_CASE_FAIL:  "Design fails at least one tolerance corner",
    ExitCode.USAGE_ERROR:      "Bad invocation (missing argument, "
                               "malformed file)",
}
