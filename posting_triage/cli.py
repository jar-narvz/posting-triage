"""Command-line entry point: `triage init | label | cache | run`."""

import argparse
import contextlib
import csv
import time
from collections import Counter
from pathlib import Path

import yaml

from posting_triage.cache import CACHE_DIR, cache_all
from posting_triage.liveness import Browser, board_job, fetch_posting
from posting_triage.profile import (
    DEGREES,
    ROLE_TYPES,
    TRACKS,
    ProfileError,
    load_profile,
    parse_choices,
    parse_degree,
    parse_month,
    parse_profile,
    parse_strings,
)

EXAMPLE_PROFILE = Path(__file__).parent.parent / "profile.example.yaml"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="triage")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="answer a few questions and write profile.yaml")
    init.add_argument("--path", default="profile.yaml", help="where to write the profile")
    cache = sub.add_parser("cache", help="fetch and save posting text for every candidate")
    cache.add_argument("--candidates", default="data/candidates.csv")
    cache.add_argument("--cache-dir", default=str(CACHE_DIR))
    cache.add_argument("--refresh", action="store_true", help="refetch everything, not just new and unreadable")
    cache.add_argument("--no-browser", action="store_true", help="board APIs only; skip other links")
    cache.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    sub.add_parser("run", help="triage postings (not implemented yet)")
    args = parser.parse_args(argv)

    if args.command == "init":
        return init_profile(Path(args.path))
    if args.command == "cache":
        return run_cache(args)
    if args.command == "run":
        print("triage run: not implemented yet")
        return 0
    return 1


def init_profile(path, ask=input):
    """Ask the profile questions and write `path`. Never overwrites without a yes."""
    if path.exists():
        answer = ask(f"{path} already exists. Overwrite it? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print(f"Left {path} unchanged.")
            return 1

    defaults = load_profile(EXAMPLE_PROFILE)
    data = {
        "degree": ask_until_valid(
            ask, f"Highest degree you'll have ({', '.join(DEGREES)})", defaults.degree, parse_degree
        ),
        "graduation_date": ask_until_valid(
            ask,
            "Graduation month (YYYY-MM)",
            defaults.graduation_date.strftime("%Y-%m"),
            lambda s: parse_month(s).strftime("%Y-%m"),
        ),
        "locations": ask_until_valid(
            ask,
            "Locations you'll work in, comma-separated",
            ", ".join(defaults.locations),
            lambda s: list(parse_strings("locations", split_list(s))),
        ),
        "tracks": ask_until_valid(
            ask,
            f"Tracks, comma-separated ({', '.join(TRACKS)})",
            ", ".join(defaults.tracks),
            lambda s: list(parse_choices("tracks", split_list(s), TRACKS)),
        ),
        "target_role_types": ask_until_valid(
            ask,
            f"Role types you want, comma-separated ({', '.join(ROLE_TYPES)})",
            ", ".join(defaults.target_role_types),
            lambda s: list(parse_choices("target_role_types", split_list(s), ROLE_TYPES)),
        ),
    }
    data["excluded_role_types"] = ask_until_valid(
        ask,
        "Role types to skip, comma-separated, or - for none",
        ", ".join(defaults.excluded_role_types),
        lambda s: excluded_types(s, data["target_role_types"]),
    )

    parse_profile(data)  # same checks `triage run` will apply when it loads the file
    path.write_text(format_profile(data))
    print(f"Wrote {path}.")
    return 0


def ask_until_valid(ask, question, default, parse):
    """Re-ask until `parse` accepts the answer. An empty answer takes the default."""
    while True:
        answer = ask(f"{question} [{default}]: ").strip() or default
        try:
            return parse(answer)
        except ProfileError as e:
            print(f"  {e}")


def split_list(answer):
    return [part.strip() for part in answer.split(",") if part.strip()]


def excluded_types(answer, targets):
    if answer == "-":
        return []
    excluded = list(parse_choices("excluded_role_types", split_list(answer), ROLE_TYPES))
    both = sorted(set(excluded) & set(targets))
    if both:
        raise ProfileError(f"already listed as role types you want: {', '.join(both)}")
    return excluded


def format_profile(data):
    """Same style as profile.example.yaml: one field per line, lists inline.
    yaml.safe_dump quotes any location that would otherwise break the YAML (e.g. "Remote: US")."""
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=1000)


def run_cache(args):
    with open(args.candidates, newline="") as f:
        rows = list(csv.DictReader(f))

    with contextlib.ExitStack() as stack:
        browser = None

        def fetch(url):
            nonlocal browser
            # Start Chromium only when the first non-API link actually needs it.
            if browser is None and not args.no_browser and board_job(url) is None:
                browser = stack.enter_context(Browser())
            return fetch_posting(url, browser)

        counts = cache_all(
            rows,
            fetch,
            cache_dir=args.cache_dir,
            refresh=args.refresh,
            sleep=(lambda: time.sleep(args.delay)) if args.delay > 0 else None,
        )

    print(format_cache_summary(counts, len(rows)))
    return 0


def format_cache_summary(counts, total):
    by_status = Counter()
    for (status, _), n in counts.items():
        by_status[status] += n
    lines = [f"{total} candidates: " + " · ".join(
        f"{by_status[s]} {s}" for s in ("ok", "not_found", "unreadable") if by_status[s]
    )]
    for (status, source), n in sorted(counts.items()):
        lines.append(f"  {status:10} {source:10} {n}")
    return "\n".join(lines)
