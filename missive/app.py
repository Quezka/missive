"""Command-line entry point."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .bootstrap import build_services


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="missive", description="A calm, private mail client.")
    parser.add_argument("--demo", action="store_true", help="try it on made-up mail (no server, nothing saved)")
    parser.add_argument("--debug", action="store_true", help="print how long the mail server takes (also MISSIVE_DEBUG=1)")
    args, qt_args = parser.parse_known_args(argv[1:])
    if args.debug or os.environ.get("MISSIVE_DEBUG"):
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="%(asctime)s %(name)s: %(message)s")
        logging.getLogger("PIL").setLevel(logging.WARNING)
    services = build_services(demo=args.demo)
    from .presentation.qt_app import run  # imported late so --help needs no display

    return run(services, [argv[0], *qt_args])
