"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys

from .bootstrap import build_services


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="missive", description="A calm, private mail client.")
    parser.add_argument("--demo", action="store_true", help="try it on made-up mail (no server, nothing saved)")
    args, qt_args = parser.parse_known_args(argv[1:])
    services = build_services(demo=args.demo)
    from .presentation.qt_app import run  # imported late so --help needs no display

    return run(services, [argv[0], *qt_args])
