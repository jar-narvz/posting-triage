"""Checks on the phrase library. The effect check compares each hand-written effect
with the guide's policy (tests/guide_policy.py), so a typo such as a "preferred"
phrase marked SKIP fails here."""

import pytest

from posting_triage.label import LABEL_COLUMNS
from guide_policy import policy_effect
from posting_triage.synthetic import (
    FLAG,
    FULLTIME,
    INTERN,
    PASS,
    SKIP,
    SLOTS,
    TRACK,
    effect,
)

EXPECTED_EFFECTS = {  # which outcomes each rule can produce
    "role_type": {PASS, FLAG, SKIP},
    "track": {PASS, SKIP},
    "degree": {PASS, FLAG, SKIP},
    "role_level": {PASS, FLAG, SKIP},
    "experience": {PASS, FLAG, SKIP},
    "graduation": {PASS, FLAG},  # a graduation mismatch never skips
    "location": {PASS, FLAG, SKIP},
}
ALL_PHRASES = [(slot, p) for slot, phrases in SLOTS for p in phrases]


@pytest.mark.parametrize("slot, phrases", SLOTS)
def test_each_slot_has_the_outcomes_its_rule_allows(slot, phrases):
    assert {p.effect for p in phrases} == EXPECTED_EFFECTS[slot]


@pytest.mark.parametrize("slot, phrases", SLOTS)
@pytest.mark.parametrize("kind", [INTERN, FULLTIME])
def test_every_slot_can_pass_for_every_kind(slot, phrases, kind):
    assert any(p.effect == PASS and kind in p.kinds for p in phrases)


@pytest.mark.parametrize("slot, phrase", ALL_PHRASES, ids=lambda x: getattr(x, "text", x) or "(silent)")
def test_values_are_label_columns(slot, phrase):
    assert set(phrase.values) <= set(LABEL_COLUMNS)


@pytest.mark.parametrize("slot, phrase", ALL_PHRASES, ids=lambda x: getattr(x, "text", x) or "(silent)")
def test_hand_written_effect_matches_the_guide(slot, phrase):
    assert phrase.effect == policy_effect(slot, phrase.values)


def test_spring_coop_accepts_any_us_location():
    location = dict(SLOTS)["location"]
    boston = next(p for p in location if p.text == "Boston, MA")
    toronto = next(p for p in location if p.text == "Toronto, ON, Canada")
    spring = {"track": next(p for p in TRACK if p.values["track"] == "spring_coop")}
    summer = {"track": next(p for p in TRACK if p.values["track"] == "summer_2027")}
    assert effect("location", boston, spring) == PASS
    assert effect("location", boston, summer) == SKIP
    assert effect("location", toronto, spring) == SKIP


def test_title_patterns_have_a_role_slot():
    level = dict(SLOTS)["role_level"]
    assert all("{role}" in p.text for p in level)


def test_there_are_hard_cases_in_every_rule_that_has_them():
    tagged = {slot for slot, p in ALL_PHRASES if p.hard}
    assert {"role_type", "track", "degree", "role_level", "experience", "graduation", "location"} <= tagged
