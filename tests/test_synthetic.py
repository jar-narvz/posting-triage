"""Checks on the phrase library. The effect checks restate the labeling guide's
policy for profile.example.yaml field by field, so a typo in a hand-written
effect (say, a "preferred" phrase marked SKIP) fails here."""

import pytest

from posting_triage.label import LABEL_COLUMNS
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

PROFILE_TRACKS = {"new_grad", "summer_2027", "spring_coop"}
TARGET_ROLES = {"swe", "ml_ai", "data_engineer", "frontend_fullstack"}
MATCHING_PLACES = {"San Francisco, CA", "San Jose, CA", "Los Angeles, CA", "Remote (US)"}
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


def policy_effect(slot, v):
    """The guide's rule for one field, written independently of the library."""
    if slot == "role_type":
        return FLAG if v["role_type"] == "ambiguous" else PASS if v["role_type"] in TARGET_ROLES else SKIP
    if slot == "track":
        return PASS if v["track"] in PROFILE_TRACKS else SKIP
    if slot == "degree":
        above = v["degree"] in ("masters", "phd")
        return (SKIP if v["degree_strength"] == "required" else FLAG) if above else PASS
    if slot == "role_level":
        return {"mid": SKIP, "senior": SKIP, "unclear": FLAG}.get(v["role_level"], PASS)
    if slot == "experience":
        if v["experience_years"] == "":
            return PASS
        if v["experience_strength"] == "preferred":
            return FLAG
        return SKIP if float(v["experience_years"]) > 1 else PASS
    if slot == "graduation":
        start, end = v["grad_start"] or "0000-00", v["grad_end"] or "9999-99"
        return PASS if start <= "2027-05" <= end else FLAG
    if slot == "location":
        if v["locations"] == "":
            return FLAG
        places = {p.strip() for p in v["locations"].split(";")}
        return PASS if places & MATCHING_PLACES or v["remote"] == "true" else SKIP
    raise AssertionError(slot)


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
