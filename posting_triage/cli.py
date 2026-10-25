"""Command-line entry point: `triage init | label | cache | run`."""

import argparse
import contextlib
import csv
import os
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

from posting_triage.cache import CACHE_DIR, cache_all
from posting_triage.label import Terminal, run_session
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
from posting_triage.run_eval import EFFORT, MODELS, load_env
from posting_triage.triage import DEAD, TriageResponse, triage

EXAMPLE_PROFILE = Path(__file__).parent.parent / "profile.example.yaml"
# The eval's pick (Oct 24 full run): the cheapest model within 5 points of the best apply precision.
DEFAULT_MODEL = "claude-haiku-5-5"


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
    label = sub.add_parser("label", help="hand-label candidates into data/labels.csv")
    label.add_argument("--candidates", default="data/candidates.csv")
    label.add_argument("--labels", default="data/labels.csv")
    label.add_argument("--skips", default="data/label_skips.csv")
    label.add_argument("--cache-dir", default=str(CACHE_DIR))
    run = sub.add_parser("run", help="triage posting URLs: APPLY, FLAG, SKIP, or DEAD, with the reason")
    run.add_argument("urls", nargs="+", metavar="URL")
    run.add_argument("--profile", default="profile.yaml")
    run.add_argument("--model", default=DEFAULT_MODEL, choices=MODELS)
    run.add_argument("--json", action="store_true", help="one JSON object per URL, the API's response schema")
    args = parser.parse_args(argv)

    if args.command == "init":
        return init_profile(Path(args.path))
    if args.command == "cache":
        return run_cache(args)
    if args.command == "label":
        with open(args.candidates, newline="") as f:
            candidates = list(csv.DictReader(f))
        return run_session(candidates, Terminal(), args.labels, args.skips, args.cache_dir)
    if args.command == "run":
        return run_triage(args)
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


@contextlib.contextmanager
def browser_when_needed(no_browser=False):
    """Yields browser_for(url): None for board-API links, else one Chromium, started only
    when the first such link needs it and shared by every later one."""
    with contextlib.ExitStack() as stack:
        browser = None

        def browser_for(url):
            nonlocal browser
            if no_browser or board_job(url) is not None:
                return None
            if browser is None:
                browser = stack.enter_context(Browser())
            return browser

        yield browser_for


def run_triage(args):
    try:
        profile = load_profile(args.profile)
    except ProfileError as e:
        print(e)
        return 1
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set: put it in .env (see .env.example)")
        return 1
    import anthropic  # imported here so the other commands don't need it

    client = anthropic.Anthropic()
    failed = False
    with browser_when_needed() as browser_for:
        for url in args.urls:
            start = time.perf_counter()
            try:
                result = triage(url, profile, client.messages.create, args.model, browser_for(url), effort=EFFORT)
            except anthropic.APIError as e:  # one bad call shouldn't lose the other postings
                # With --json, errors go to stderr so stdout stays one valid JSON object per line.
                print(f"ERROR  {url}\n       {type(e).__name__}: {e}", file=sys.stderr if args.json else sys.stdout)
                failed = True
                continue
            if args.json:
                latency_ms = round((time.perf_counter() - start) * 1000)
                print(TriageResponse.from_triage(result, args.model, latency_ms).model_dump_json())
            else:
                print(format_triage(result))
    return 1 if failed else 0


def format_triage(result):
    """The verdict and URL, then the reason on an indented line (none for APPLY)."""
    if result.verdict == DEAD:
        reason = f"careers page: {result.careers_page}" if result.careers_page else result.detail
    elif result.field == "liveness":
        reason = f"couldn't verify ({result.detail})"
    elif result.field == "quote":
        reason = f'quote not in the posting: "{result.quote}"' if result.quote else "no usable reading of the posting"
    elif result.field:
        reason = f'{result.field}: "{result.quote}"' if result.quote else result.field
    else:
        reason = ""
    return f"{result.verdict.upper():5}  {result.url}" + (f"\n       {reason}" if reason else "")


def run_cache(args):
    with open(args.candidates, newline="") as f:
        rows = list(csv.DictReader(f))

    with browser_when_needed(args.no_browser) as browser_for:
        counts = cache_all(
            rows,
            lambda url: fetch_posting(url, browser_for(url)),
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
