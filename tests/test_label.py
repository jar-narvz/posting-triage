import csv
import datetime

import pytest

from posting_triage.cache import save
from posting_triage.label import (
    Back,
    Prompter,
    Quit,
    SkipPosting,
    parse_locations,
    parse_window,
    parse_years,
    run_session,
)
from posting_triage.liveness import PostingText


class ScriptedIO:
    """Stand-in for Terminal: plays back keys and typed lines, records output."""

    def __init__(self, *inputs):
        self.inputs = list(inputs)
        self.output = []
        self.opened = []
        self.paged = []

    def key(self):
        return self.inputs.pop(0)

    def line(self, prompt):
        self.output.append(prompt)
        return self.inputs.pop(0)

    def show(self, text=""):
        self.output.append(text)

    def open(self, url):
        self.opened.append(url)

    def page(self, text):
        self.paged.append(text)


LEVELS = [("i", "intern", "intern"), ("g", "new_grad", "new grad"), ("u", "unclear", "unclear")]


def test_choose_returns_the_value_for_a_key():
    io = ScriptedIO("g")
    assert Prompter(io, "https://x").choose("Role level", LEVELS) == "new_grad"
    assert "[i] intern  [g] new grad  [u] unclear" in io.output[0]


def test_choose_reasks_on_an_unknown_key():
    io = ScriptedIO("z", "i")
    assert Prompter(io, "https://x").choose("Role level", LEVELS) == "intern"
    assert any("press one of: i g u" in line for line in io.output)


def test_open_shows_the_posting_and_asks_again():
    io = ScriptedIO("O", "u")
    assert Prompter(io, "https://x/job").choose("Role level", LEVELS) == "unclear"
    assert io.opened == ["https://x/job"]


@pytest.mark.parametrize("key, control", [("B", Back), ("S", SkipPosting), ("Q", Quit)])
def test_control_keys_raise(key, control):
    with pytest.raises(control):
        Prompter(ScriptedIO(key), "https://x").choose("Role level", LEVELS)


def test_text_parses_and_reasks_on_error():
    def years(answer):
        if not answer.strip().isdigit():
            raise ValueError("type a whole number")
        return int(answer)

    io = ScriptedIO("two", "2")
    assert Prompter(io, "https://x").text("Years", years) == 2
    assert "  type a whole number" in io.output


def test_text_accepts_control_keys_too():
    with pytest.raises(Back):
        Prompter(ScriptedIO("B"), "https://x").text("Years")
    io = ScriptedIO("O", "Seattle, WA")
    assert Prompter(io, "https://x").text("Locations") == "Seattle, WA"
    assert io.opened == ["https://x"]


@pytest.mark.parametrize("answer, value", [("2", "2"), ("0.5", "0.5"), (" - ", "")])
def test_parse_years(answer, value):
    assert parse_years(answer) == value


@pytest.mark.parametrize("answer", ["two", "-1"])
def test_parse_years_rejects(answer):
    with pytest.raises(ValueError):
        parse_years(answer)


@pytest.mark.parametrize(
    "answer, window",
    [("-", ("", "")), ("2026-12 2027-08", ("2026-12", "2027-08")), ("? 2027-08", ("", "2027-08"))],
)
def test_parse_window(answer, window):
    assert parse_window(answer) == window


@pytest.mark.parametrize("answer", ["2027-08", "Dec 2026 Aug 2027", "2027-08 2026-12", "? ?", "2027-13 2028-01"])
def test_parse_window_rejects(answer):
    with pytest.raises(ValueError):
        parse_window(answer)


def test_parse_locations():
    assert parse_locations("San Jose, CA ; Remote (US)") == "San Jose, CA; Remote (US)"
    assert parse_locations("-") == ""
    with pytest.raises(ValueError):
        parse_locations(" ; ")


CANDIDATES = [
    {"id": f"c{i}", "url": f"https://x.example/{i}", "company": f"Co{i}", "title": title,
     "location": "SF", "tags": ""}
    for i, title in enumerate(["SWE New Grad", "Backend Engineer I", "ML Engineer Graduate - PhD"])
]
NOW = datetime.datetime(2026, 10, 22, 12, 0, tzinfo=datetime.timezone.utc)

# Keys for one APPLY posting: track, level, degree, strength, years, window,
# locations, remote, role type, verdict, notes. (No deciding field for APPLY.)
APPLY_KEYS = ["n", "g", "b", "r", "-", "-", "San Francisco, CA", "n", "s", "a", ""]
# FLAG on preferred experience: experience years + strength, then the deciding field.
FLAG_KEYS = ["n", "e", "-", "2", "p", "-", "Remote", "y", "s", "f", "e", "2+ yrs preferred"]


def labels_in(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_session_saves_rows_with_every_field(tmp_path):
    labels, skips = tmp_path / "labels.csv", tmp_path / "skips.csv"
    io = ScriptedIO(*APPLY_KEYS, *FLAG_KEYS, "Q")
    run_session(CANDIDATES, io, labels, skips, tmp_path / "cache", now=NOW)
    rows = labels_in(labels)
    assert [r["id"] for r in rows] == ["c0", "c1"]
    assert rows[0] == {
        "id": "c0", "url": "https://x.example/0", "company": "Co0", "title": "SWE New Grad",
        "track": "new_grad", "gold_verdict": "apply", "deciding_field": "", "notes": "",
        "role_level": "new_grad", "degree": "bachelors", "degree_strength": "required",
        "experience_years": "", "experience_strength": "", "grad_start": "", "grad_end": "",
        "locations": "San Francisco, CA", "remote": "false", "role_type": "swe",
        "labeled_at": "2026-10-22T12:00:00+00:00",
    }
    assert rows[1]["gold_verdict"] == "flag"
    assert rows[1]["deciding_field"] == "experience"
    assert (rows[1]["experience_years"], rows[1]["experience_strength"]) == ("2", "preferred")
    assert rows[1]["degree_strength"] == ""  # not asked when the degree isn't stated
    assert any("Stopped. Nothing saved for this posting." in line for line in io.output)


def test_quit_mid_posting_saves_nothing_and_resume_starts_there(tmp_path):
    labels, skips = tmp_path / "labels.csv", tmp_path / "skips.csv"
    run_session(CANDIDATES, ScriptedIO(*APPLY_KEYS, "n", "g", "Q"), labels, skips, tmp_path, now=NOW)
    assert [r["id"] for r in labels_in(labels)] == ["c0"]

    io = ScriptedIO("Q")
    run_session(CANDIDATES, io, labels, skips, tmp_path, now=NOW)
    assert any("[2/3]  Co1 — Backend Engineer I" in line for line in io.output)


def test_skip_is_recorded_separately_and_not_asked_again(tmp_path):
    labels, skips = tmp_path / "labels.csv", tmp_path / "skips.csv"
    run_session(CANDIDATES, ScriptedIO("n", "S", "Q"), labels, skips, tmp_path, now=NOW)
    assert not labels.exists()
    assert labels_in(skips) == [{"id": "c0", "url": "https://x.example/0", "reason": "skipped"}]

    io = ScriptedIO("Q")
    run_session(CANDIDATES, io, labels, skips, tmp_path, now=NOW)
    assert any("[2/3]" in line for line in io.output)


def test_back_returns_to_the_previous_question(tmp_path):
    labels, skips = tmp_path / "labels.csv", tmp_path / "skips.csv"
    # Answer degree = masters, press B at "Degree is", change degree to "not stated".
    keys = ["n", "g", "m", "B", "-", "-", "-", "SF", "n", "s", "a", "", "Q"]
    run_session(CANDIDATES, ScriptedIO(*keys), labels, skips, tmp_path, now=NOW)
    row = labels_in(labels)[0]
    assert (row["degree"], row["degree_strength"]) == ("", "")


def test_cached_text_is_shown_and_dead_postings_are_auto_skipped(tmp_path):
    labels, skips = tmp_path / "labels.csv", tmp_path / "skips.csv"
    cache = tmp_path / "cache"
    save("c0", "https://x.example/0", PostingText("not_found", "greenhouse", detail="HTTP 404"), cache)
    save("c1", "https://x.example/1", PostingText("ok", "lever", "Backend Engineer I\n2+ years preferred"), cache)
    io = ScriptedIO("Q")
    run_session(CANDIDATES, io, labels, skips, cache, now=NOW)
    assert labels_in(skips) == [{"id": "c0", "url": "https://x.example/0", "reason": "dead (HTTP 404)"}]
    assert io.paged == ["Backend Engineer I\n2+ years preferred"]
    assert any("cached ok via lever, 37 chars" in line for line in io.output)


def test_off_season_posting_is_labeled_other_track_and_skipped_on_track(tmp_path):
    labels, skips = tmp_path / "labels.csv", tmp_path / "skips.csv"
    keys = ["o", "i", "-", "-", "-", "San Francisco, CA", "n", "s", "s", "k", "Fall 2026 only", "Q"]
    run_session(CANDIDATES, ScriptedIO(*keys), labels, skips, tmp_path, now=NOW)
    row = labels_in(labels)[0]
    assert (row["track"], row["gold_verdict"], row["deciding_field"]) == ("other", "skip", "track")
