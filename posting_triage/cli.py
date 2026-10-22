"""Command-line entry point: `triage init | label | cache | run`."""

import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(prog="triage")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="triage postings (not implemented yet)")
    args = parser.parse_args(argv)

    if args.command == "run":
        print("triage run: not implemented yet")
        return 0
    return 1
