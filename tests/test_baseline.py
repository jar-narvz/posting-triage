"""The keyword baseline, including the mistakes it's supposed to make. If a change
"fixes" one of the expected-mistake tests, the baseline got stronger than decision 6."""

import pytest

from posting_triage.baseline import TITLE_KEYWORDS, baseline_verdict

PLACES = ("Bay Area", "Los Angeles", "Remote")
SF = "San Francisco, CA"


@pytest.mark.parametrize("keyword", TITLE_KEYWORDS)
def test_each_title_keyword_skips(keyword):
    assert baseline_verdict(f"{keyword} Software Engineer", SF, PLACES) == ("skip", f'title: "{keyword}"')


@pytest.mark.parametrize("title", ["SENIOR Engineer", "Software Engineer, PhD", "ML Engineer (Masters)"])
def test_keywords_match_any_case(title):
    assert baseline_verdict(title, SF, PLACES)[0] == "skip"


@pytest.mark.parametrize("title", ["Undergraduate Researcher", "Staffing Tools Engineer"])
def test_keywords_match_whole_words_only(title):
    assert baseline_verdict(title, SF, PLACES)[0] == "apply"


@pytest.mark.parametrize("title, word", [("Software Engineer I/II", "II"), ("Software Engineer III", "III")])
def test_roman_numeral_levels_are_reported_as_written(title, word):
    assert baseline_verdict(title, SF, PLACES) == ("skip", f'title: "{word}"')


def test_location_outside_the_profile_skips():
    assert baseline_verdict("Software Engineer, New Grad", "Seattle, WA", PLACES) == ("skip", 'location: "Seattle, WA"')


def test_no_location_skips():
    assert baseline_verdict("Software Engineer, New Grad", "", PLACES) == ("skip", "location: none listed")


def test_title_is_checked_before_location():
    assert baseline_verdict("Senior Engineer", "Seattle, WA", PLACES) == ("skip", 'title: "Senior"')


def test_clean_title_in_a_profile_region_applies():
    assert baseline_verdict("Software Engineer Intern - Summer 2027", "San Jose, CA", PLACES)[0] == "apply"


# Expected mistakes. Gold verdicts here are from the labeling guide for profile.example.yaml.
@pytest.mark.parametrize(
    "title, location, gold",
    [
        ("Software Engineer Graduate", SF, "apply"),  # bachelor's-level "Graduate" title
        ("Software Engineer, New Grad (Senior Living Platform)", SF, "apply"),  # Senior is a team name
        ("Software Engineer I/II", SF, "apply"),  # mixed levels; label the lowest
        ("Data & ML Engineer, New Grad", SF, "flag"),  # ambiguous role type; baseline never flags
        ("Software Engineer, New Grad", "", "flag"),  # no location is FLAG, not SKIP
        ("Software Engineer Intern - Spring 2027 Co-op", "Boston, MA", "apply"),  # co-ops accept any US place
        ("Hardware Engineer, New Grad", SF, "skip"),  # off-target role with no keyword
    ],
)
def test_expected_mistakes(title, location, gold):
    assert baseline_verdict(title, location, PLACES)[0] != gold
