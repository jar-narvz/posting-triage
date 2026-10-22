"""Interactive labeling session behind `triage label`.

Answers are single keypresses where possible. Lowercase keys pick an answer;
uppercase keys are controls, so they never collide with an answer:
    O  open the posting in your browser      B  back to the previous question
    T  show the cached posting text again    S  skip this posting
    Q  quit (nothing saved for this posting)
"""

import csv
import datetime
import pydoc
import re
import sys
import webbrowser
from collections import Counter
from pathlib import Path

from posting_triage.cache import CACHE_DIR, load
from posting_triage.candidates import is_hard
from posting_triage.excerpt import excerpt, highlight


class Back(Exception):
    """Go back one question."""


class SkipPosting(Exception):
    """Record this posting as skipped and move on."""


class Quit(Exception):
    """Stop the session without saving the posting in progress."""


CONTROLS = {"B": Back, "S": SkipPosting, "Q": Quit}
ENTER = "\n"
CONTROL_HELP = "O open · T text · B back · S skip · Q quit"


class Terminal:
    """Real keyboard and screen. Tests use a scripted stand-in with the same methods."""

    def __init__(self):
        self.color = sys.stdout.isatty()  # highlight key terms only on a real terminal

    def key(self):
        if not sys.stdin.isatty():
            line = sys.stdin.readline()
            if not line:
                raise Quit  # end of piped input
            return line[:1] if line.strip() else "\n"
        return read_key()

    def line(self, prompt):
        try:
            return input(prompt)
        except EOFError:
            raise Quit from None

    def show(self, text=""):
        print(text, flush=True)

    def open(self, url):
        webbrowser.open(url)

    def page(self, text):
        pydoc.pager(text)  # `less` on macOS/Linux; press q to come back


def read_key():
    """One keypress, without waiting for Enter (macOS/Linux)."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        key = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if key == "\x03":  # Ctrl-C arrives as a character in raw mode
        raise KeyboardInterrupt
    return "\n" if key == "\r" else key


class Prompter:
    """Asks one question at a time for one posting."""

    def __init__(self, io, url, text=""):
        self.io = io
        self.url = url
        self.text_body = text

    def choose(self, question, options, default=None):
        """options: list of (key, value, label). Returns the chosen value.
        With a default, Enter accepts it."""
        values = {key: value for key, value, _ in options}
        labels = {key: label for key, _, label in options}
        menu = "  ".join(f"[{key}] {label}" for key, _, label in options)
        hint = ""
        if default is not None:
            default_label = next(label for _, value, label in options if value == default)
            hint = f"  (Enter = {default_label})"
            values[ENTER], labels[ENTER] = default, default_label
        while True:
            self.io.show(f"{question}  {menu}{hint}")
            key = self.io.key()
            if self._control(key):
                continue
            if key in values:
                self.io.show(f"  → {labels[key]}")
                return values[key]
            keys = " ".join(k for k, _, _ in options)
            self.io.show(f"  press one of: {keys}  ({CONTROL_HELP})")

    def text(self, question, parse=str.strip, default=None):
        """A typed answer. `parse` may raise ValueError to ask again.
        With a default, an empty answer accepts it."""
        prompt = f"{question} [{default}]: " if default is not None else f"{question}: "
        while True:
            answer = self.io.line(prompt)
            if self._control(answer.strip()):
                continue
            if default is not None and not answer.strip():
                answer = default
            try:
                return parse(answer)
            except ValueError as e:
                self.io.show(f"  {e}")

    def _control(self, key):
        """Handle a control key. Returns True if the question should be asked again."""
        if key == "O":
            self.io.open(self.url)
            return True
        if key == "T":
            self.io.page(self.text_body or "(no cached text — press O to open the posting)")
            return True
        if key in CONTROLS:
            raise CONTROLS[key]
        return False


LABEL_COLUMNS = (
    "id", "url", "company", "title", "track", "gold_verdict", "deciding_field", "notes",
    "role_level", "degree", "degree_strength", "experience_years", "experience_strength",
    "grad_start", "grad_end", "locations", "remote", "role_type", "labeled_at",
)
SKIP_COLUMNS = ("id", "url", "reason")
# Cache statuses skipped without asking (labeling guide, rule 1): there's no text to label from.
AUTO_SKIP = {"not_found": "dead", "unreadable": "unreadable"}

STRENGTH = [("r", "required", "required"), ("p", "preferred", "preferred")]
DECIDING_FIELDS = [
    ("v", "liveness", "couldn't verify"),
    ("t", "role_type", "role type"),
    ("k", "track", "track"),
    ("d", "degree", "degree"),
    ("l", "role_level", "level"),
    ("e", "experience", "experience"),
    ("g", "graduation", "graduation"),
    ("c", "location", "location"),
]


def parse_years(answer):
    answer = answer.strip()
    if answer == "-":
        return ""
    try:
        years = float(answer)
    except ValueError:
        raise ValueError("type a number of years (e.g. 2 or 0.5), or - if the posting doesn't say") from None
    if years < 0:
        raise ValueError("years can't be negative")
    return f"{years:g}"


MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_window(answer):
    """'-' (silent), or 'START END' as YYYY-MM, with '?' for an open end."""
    parts = answer.split()
    if parts == ["-"]:
        return ("", "")
    if len(parts) != 2 or not all(p == "?" or MONTH.match(p) for p in parts) or parts == ["?", "?"]:
        raise ValueError("type START END as YYYY-MM (e.g. 2026-12 2027-08), ? for an open end, or -")
    start, end = ("" if p == "?" else p for p in parts)
    if start and end and start > end:
        raise ValueError("start is after end")
    return (start, end)


def parse_locations(answer):
    answer = answer.strip()
    if answer == "-":
        return ""
    places = [p.strip() for p in answer.split(";") if p.strip()]
    if not places:
        raise ValueError("type locations separated by ; or - if none are listed")
    return "; ".join(places)


ABBREVIATIONS = {"SF": "San Francisco, CA", "NYC": "New York, NY", "LA": "Los Angeles, CA"}


def guess_track(candidate):
    """Prefill for the track question, from the title's term, else the source list.
    None when the title doesn't settle it (e.g. a co-op with no term)."""
    title = candidate["title"].lower()
    if re.search(r"\bspring\b", title):
        return "spring_coop"
    if re.search(r"\b(fall|autumn|winter)\b|part[- ]time", title):
        return "other"
    if "summer" in title:
        return "summer_2027"
    if re.search(r"co-?op", title):
        return None
    if candidate.get("source", "").endswith("intern"):
        return "summer_2027"
    if candidate.get("source", "").endswith("newgrad"):
        return "new_grad"
    return None


def guess_locations(candidate):
    """Prefill for locations: the candidate list's location, with shorthand spelled out.
    Lists often truncate ("+2"), so check the posting before accepting."""
    places = []
    for place in candidate.get("location", "").split(";"):
        place = re.sub(r"\s*\+\d+$", "", place).strip()
        if place:
            places.append(ABBREVIATIONS.get(place, place))
    return "; ".join(places) or None


def guess_remote(candidate):
    return "true" if "remote" in candidate.get("location", "").lower() else "false"


def steps(candidate):
    """The questions for one posting, in order. Each step: (name, ask, applies).
    Track, locations, and remote are prefilled (Enter accepts); judgment fields never are."""
    always = lambda a: True  # noqa: E731
    return [
        ("track", lambda p, a: p.choose("Track", [
            ("n", "new_grad", "new grad"), ("s", "summer_2027", "summer 2027"),
            ("c", "spring_coop", "spring co-op"), ("o", "other", "other term")],
            default=guess_track(candidate)), always),
        ("role_level", lambda p, a: p.choose("Role level", [
            ("i", "intern", "intern"), ("g", "new_grad", "new grad"), ("e", "entry", "entry"),
            ("m", "mid", "mid"), ("s", "senior", "senior"), ("u", "unclear", "unclear")]), always),
        ("degree", lambda p, a: p.choose("Degree", [
            ("-", "", "not stated"), ("n", "none", "none needed"), ("b", "bachelors", "bachelors"),
            ("m", "masters", "masters"), ("p", "phd", "phd")]), always),
        ("degree_strength", lambda p, a: p.choose("  Degree is", STRENGTH),
         lambda a: a["degree"] not in ("", "none")),
        ("experience_years", lambda p, a: p.text("Years of experience (number, or -)", parse_years), always),
        ("experience_strength", lambda p, a: p.choose("  Experience is", STRENGTH),
         lambda a: a["experience_years"] != ""),
        ("grad_window", lambda p, a: p.text("Graduation window (START END as YYYY-MM, ? open, or -)", parse_window),
         always),
        ("locations", lambda p, a: p.text("Locations (separate with ;  or - if none)", parse_locations,
                                           default=guess_locations(candidate)), always),
        ("remote", lambda p, a: p.choose("Remote allowed", [("y", "true", "yes"), ("n", "false", "no")],
                                         default=guess_remote(candidate)), always),
        ("role_type", lambda p, a: p.choose("Role type", [
            ("s", "swe", "swe"), ("m", "ml_ai", "ml/ai"), ("d", "data_engineer", "data eng"),
            ("x", "data_scientist", "data scientist"), ("f", "frontend_fullstack", "frontend/fullstack"),
            ("o", "other", "other"), ("a", "ambiguous", "ambiguous")]), always),
        ("gold_verdict", lambda p, a: p.choose("VERDICT", [
            ("a", "apply", "APPLY"), ("f", "flag", "FLAG"), ("s", "skip", "SKIP")]), always),
        ("deciding_field", lambda p, a: p.choose("  Deciding field", DECIDING_FIELDS),
         lambda a: a["gold_verdict"] != "apply"),
        ("notes", lambda p, a: p.text("Notes (optional)"), always),
    ]


def ask_fields(prompter, candidate):
    """Walk the steps; B goes back to the previous step that applied."""
    plan = steps(candidate)
    answers, history, i = {}, [], 0
    while i < len(plan):
        name, ask, applies = plan[i]
        if not applies(answers):
            answers[name] = ""
            i += 1
            continue
        try:
            answers[name] = ask(prompter, answers)
            history.append(i)
            i += 1
        except Back:
            if history:
                i = history.pop()
    return answers


def to_row(candidate, answers, now):
    start, end = answers["grad_window"]
    row = {
        "id": candidate["id"],
        "url": candidate["url"],
        "company": candidate["company"],
        "title": candidate["title"],
        **{k: answers[k] for k in (
            "track", "gold_verdict", "deciding_field", "notes", "role_level", "degree",
            "degree_strength", "experience_years", "experience_strength", "locations",
            "remote", "role_type")},
        "grad_start": start,
        "grad_end": end,
        "labeled_at": now.isoformat(timespec="seconds"),
    }
    return {k: row[k] for k in LABEL_COLUMNS}


def append_row(path, columns, row):
    path = Path(path)
    new = not path.exists() or path.stat().st_size == 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if new:
            writer.writeheader()
        writer.writerow(row)


def read_ids(path):
    path = Path(path)
    if not path.exists():
        return set()
    with path.open(newline="") as f:
        return {row["id"] for row in csv.DictReader(f)}


def read_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def progress(candidates, labels_path, skips_path):
    labels = read_rows(labels_path)
    skipped = len(read_ids(skips_path))
    by_id = {c["id"]: c for c in candidates}
    hard = sum(1 for r in labels if r["id"] in by_id and is_hard(by_id[r["id"]]))
    verdicts = Counter(r["gold_verdict"] for r in labels)
    remaining = len(candidates) - len(labels) - skipped
    return (
        f"{len(labels)} labeled ({verdicts['apply']} apply · {verdicts['flag']} flag · "
        f"{verdicts['skip']} skip) · {hard} likely hard · {skipped} skipped · {remaining} left"
    )


def header(candidate, entry, position, total):
    tags = f"  {candidate['tags']}" if candidate.get("tags") else ""
    if entry is None:
        cached = "no cached text (press O to open)"
    else:
        cached = f"cached {entry['status']} via {entry['source']}, {len(entry['text'])} chars"
    return "\n".join([
        "",
        "─" * 72,
        f"[{position}/{total}]  {candidate['company']} — {candidate['title']}{tags}",
        f"           {candidate['location']}",
        f"           {candidate['url']}",
        f"           {cached}",
    ])


def run_session(candidates, io, labels_path, skips_path, cache_dir=CACHE_DIR, now=None):
    """Label candidates in file order, skipping ones already labeled or skipped."""
    done = read_ids(labels_path) | read_ids(skips_path)
    todo = [c for c in candidates if c["id"] not in done]
    io.show(f"{len(done)} done, {len(todo)} to go. {progress(candidates, labels_path, skips_path)}")

    for n, candidate in enumerate(todo, 1):
        entry = load(candidate["id"], cache_dir)
        if entry and entry["status"] in AUTO_SKIP:
            reason = f"{AUTO_SKIP[entry['status']]} ({entry['detail'] or entry['status']})"
            append_row(skips_path, SKIP_COLUMNS, {"id": candidate["id"], "url": candidate["url"], "reason": reason})
            io.show(f"auto-skipped, {reason}: {candidate['company']} — {candidate['title']}")
            continue

        text = entry["text"] if entry else ""
        io.show(header(candidate, entry, len(done) + n, len(candidates)))
        if text:
            io.show(highlight(excerpt(text), color=getattr(io, "color", False)))
            io.show("           ↑ excerpt (T = full text)")
        io.show(f"           {CONTROL_HELP}")
        prompter = Prompter(io, candidate["url"], text)
        try:
            answers = ask_fields(prompter, candidate)
        except SkipPosting:
            append_row(skips_path, SKIP_COLUMNS, {"id": candidate["id"], "url": candidate["url"], "reason": "skipped"})
            io.show("  skipped")
            continue
        except (Quit, KeyboardInterrupt):
            io.show("\nStopped. Nothing saved for this posting.")
            break

        stamp = now or datetime.datetime.now(datetime.timezone.utc)
        append_row(labels_path, LABEL_COLUMNS, to_row(candidate, answers, stamp))
        io.show("  saved")
        labeled_now = len(read_ids(labels_path))
        if labeled_now % 10 == 0:
            io.show(progress(candidates, labels_path, skips_path))

    io.show(progress(candidates, labels_path, skips_path))
    return 0
