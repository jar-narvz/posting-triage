"""The verdict rules. The synthetic test is the strong one: gold answers were built from
scenarios, not from this module, so matching all of them is an independent check."""

import dataclasses
from pathlib import Path

import pytest

from posting_triage.label import read_rows
from posting_triage.profile import load_profile
from posting_triage.rules import RULE_ORDER, RULES, Verdict, decide
from posting_triage.synthetic import generate

ROOT = Path(__file__).parent.parent
PROFILE = load_profile(ROOT / "profile.example.yaml")

# Passes every rule; each test changes one thing.
OK = {
    "role_type": "swe", "track": "new_grad", "degree": "bachelors", "degree_strength": "required",
    "role_level": "new_grad", "experience_years": "", "experience_strength": "",
    "grad_start": "", "grad_end": "", "locations": "San Francisco, CA", "remote": "false",
}


def outcome(**change):
    v = decide(OK | change, PROFILE)
    return v.verdict, v.field


@pytest.mark.parametrize("posting", generate(), ids=lambda p: p["id"])
def test_reproduces_every_synthetic_answer(posting):
    v = decide(posting["gold"], PROFILE)
    assert (v.verdict, v.field) == (posting["gold_verdict"], posting["deciding_field"])


LABELED = [r for r in read_rows(ROOT / "data/labels.csv") if r["deciding_field"] not in ("liveness", "quote")]


@pytest.mark.parametrize("row", LABELED, ids=lambda r: r["id"])
def test_reproduces_every_hand_label(row):
    """Also a check on the labels: a failure here is as likely a mislabel as a rules bug."""
    v = decide(row, PROFILE)
    assert (v.verdict, v.field) == (row["gold_verdict"], row["deciding_field"]), row["notes"]


def test_clean_posting_applies():
    assert decide(OK, PROFILE) == Verdict("apply", "", None)


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"role_type": "ambiguous"}, ("flag", "role_type")),
        ({"role_type": "data_scientist"}, ("skip", "role_type")),  # excluded
        ({"role_type": "other"}, ("skip", "role_type")),  # not a target
        ({"track": "other"}, ("skip", "track")),
        ({"track": ""}, ("apply", "")),  # absent is not uncertain
        ({"degree": "masters", "degree_strength": "required"}, ("skip", "degree")),
        ({"degree": "phd", "degree_strength": "preferred"}, ("flag", "degree")),
        ({"degree": "none"}, ("apply", "")),
        ({"degree": ""}, ("apply", "")),
        ({"role_level": "mid"}, ("skip", "role_level")),
        ({"role_level": "senior"}, ("skip", "role_level")),
        ({"role_level": "unclear"}, ("flag", "role_level")),
        ({"role_level": "entry"}, ("apply", "")),
        ({"experience_years": "2", "experience_strength": "required"}, ("skip", "experience")),
        ({"experience_years": "1", "experience_strength": "required"}, ("apply", "")),
        ({"experience_years": "0.5", "experience_strength": "required"}, ("apply", "")),
        ({"experience_years": "2", "experience_strength": "preferred"}, ("flag", "experience")),
        ({"grad_start": "2026-12", "grad_end": "2027-08"}, ("apply", "")),
        ({"grad_start": "", "grad_end": "2027-05"}, ("apply", "")),  # the boundary month counts
        ({"grad_start": "2027-12", "grad_end": "2028-06"}, ("flag", "graduation")),
        ({"grad_start": "2027-09", "grad_end": ""}, ("flag", "graduation")),  # must return to school
        ({"locations": ""}, ("flag", "location")),
        ({"locations": "Seattle, WA"}, ("skip", "location")),
        ({"locations": "Seattle, WA; Santa Clara, CA"}, ("apply", "")),
        ({"locations": "Austin, TX", "remote": "true"}, ("apply", "")),
        ({"locations": "Boston, MA", "track": "spring_coop"}, ("apply", "")),
        ({"locations": "Toronto, ON, Canada", "track": "spring_coop"}, ("skip", "location")),
    ],
)
def test_each_rule(change, expected):
    assert outcome(**change) == expected


def test_first_rule_to_fire_decides():
    # Senior and PhD-required: degree (rule 4) comes before level (rule 5).
    assert outcome(role_level="senior", degree="phd", degree_strength="required") == ("skip", "degree")
    # Ambiguous role and an out-of-profile track: role type comes first.
    assert outcome(role_type="ambiguous", track="other") == ("flag", "role_type")


def test_reason_quotes_the_deciding_field():
    quotes = {"experience": "3+ years of professional experience required", "location": "Seattle, WA"}
    v = decide(OK | {"experience_years": "3", "experience_strength": "required", "locations": "Seattle, WA"},
               PROFILE, quotes)
    assert v == Verdict("skip", "experience", "3+ years of professional experience required")


def test_unverified_quote_flags_before_any_rule():
    quotes = {"degree": "MS required", "location": "Seattle"}
    v = decide(OK | {"role_type": "other"}, PROFILE, quotes, unverified={"location", "degree"})
    assert v == Verdict("flag", "quote", "MS required")  # degree comes before location


def test_rules_read_the_profile_not_constants():
    phd_holder = dataclasses.replace(PROFILE, degree="phd")
    assert decide(OK | {"degree": "phd", "degree_strength": "required"}, phd_holder).verdict == "apply"
    wants_ds = dataclasses.replace(PROFILE, target_role_types=("data_scientist",), excluded_role_types=())
    assert decide(OK | {"role_type": "data_scientist"}, wants_ds).verdict == "apply"
    seattle = dataclasses.replace(PROFILE, locations=("Seattle, WA",))
    assert decide(OK | {"locations": "Seattle, WA"}, seattle).verdict == "apply"
    december = dataclasses.replace(PROFILE, graduation_date=PROFILE.graduation_date.replace(year=2027, month=12))
    assert decide(OK | {"grad_start": "2027-12", "grad_end": "2028-06"}, december).verdict == "apply"


def test_remote_counts_only_if_the_profile_wants_it():
    on_site = dataclasses.replace(PROFILE, locations=("Bay Area",))
    assert decide(OK | {"locations": "Austin, TX", "remote": "true"}, on_site).field == "location"


def test_rule_table_covers_the_order():
    assert list(RULES) == RULE_ORDER
