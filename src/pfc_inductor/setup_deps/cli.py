"""``pfc-inductor-setup`` console script entrypoint.

Runs the cross-platform installer with sensible defaults. Suitable for
CI, headless boxes and users who prefer the terminal.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import Optional

from pfc_inductor.setup_deps import (
    check_fea_setup, setup_fea, SetupReport, SetupStep,
)


_RESET = "\033[0m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"


def _supports_color(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def _print_step(s: SetupStep, *, color: bool) -> None:
    if s.ok:
        marker = f"{_GREEN}✓{_RESET}" if color else "ok"
    else:
        marker = f"{_RED}✗{_RESET}" if color else "FAIL"
    detail = f" {_DIM}({s.detail}){_RESET}" if (color and s.detail) else (
        f" ({s.detail})" if s.detail else ""
    )
    print(f"  [{marker}] {s.name}{detail}")


def _print_report(report: SetupReport, *, color: bool) -> None:
    if report.platform:
        print(
            f"Plataforma: {report.platform.os}-{report.platform.arch} "
            f"({report.platform.onelab_tag})"
        )
    if report.onelab_dir:
        print(f"ONELAB:     {report.onelab_dir}")
    print()
    for step in report.steps:
        _print_step(step, color=color)
    print()
    if report.ok:
        msg = "Setup concluído com sucesso."
        print(f"{_GREEN}{msg}{_RESET}" if color else msg)
    else:
        msg = "Setup terminou com falhas — veja acima."
        print(f"{_YELLOW}{msg}{_RESET}" if color else msg)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="pfc-inductor-setup",
        description=(
            "Instala e configura o backend FEA (ONELAB + FEMMT) "
            "automaticamente em macOS, Linux e Windows."
        ),
    )
    p.add_argument(
        "--onelab-dir", type=Path, default=None,
        help="Diretório destino do ONELAB (padrão: ~/onelab).",
    )
    p.add_argument(
        "--skip-codesign", action="store_true",
        help="Pula codesign do macOS (use se já tiver feito manualmente).",
    )
    p.add_argument(
        "--check", action="store_true",
        help="Apenas verifica o estado atual; não instala nada.",
    )
    p.add_argument(
        "--no-color", action="store_true",
        help="Desabilita cores ANSI.",
    )
    args = p.parse_args(argv)
    color = not args.no_color and _supports_color(sys.stdout)

    if args.check:
        v = check_fea_setup()
        print("Estado do backend FEA:")
        print(f"  FEMMT importável  : {'sim' if v.femmt_importable else 'não'}"
              + (f"  (v{v.femmt_version})" if v.femmt_version else ""))
        print(f"  ONELAB configurado: {v.onelab_dir or '(não definido)'}")
        print(f"  Pronto para usar  : "
              + ("sim" if v.fea_ready else "NÃO"))
        for note in v.notes:
            print(f"  - {note}")
        return 0 if v.fea_ready else 1

    def on_progress(msg: str, frac: float) -> None:
        # Throttled, single-line progress for the CLI.
        bar = int(20 * max(0.0, min(1.0, frac)))
        line = f"  [{('#' * bar).ljust(20)}] {msg}"
        sys.stdout.write("\r\x1b[K" + line if color else "\r" + line)
        sys.stdout.flush()
        if frac >= 0.99:
            sys.stdout.write("\n")
            sys.stdout.flush()

    report = setup_fea(
        onelab_dir=args.onelab_dir,
        skip_codesign=args.skip_codesign,
        on_progress=on_progress,
    )
    print()
    _print_report(report, color=color)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
