import datetime
import re
from pathlib import Path

import pytest

from posting_triage.profile import (
    Profile,
    ProfileError,
    load_profile,
    location_matches,
    parse_profile,
    profile_from_yaml,
)

EXAMPLE = Path(__file__).parent.parent / "profile.example.yaml"


def valid():
    return {
        "degree": "bachelors",
        "graduation_date": "2027-05",
        "locations": ["Bay Area", "Remote"],
        "tracks": ["new_grad"],
        "target_role_types": ["swe"],
        "excluded_role_types": ["data_scientist"],
    }


def test_example_profile_loads():
    profile = load_profile(EXAMPLE)
    assert profile == Profile(
        degree="bachelors",
        graduation_date=datetime.date(2027, 5, 1),
        locations=("Bay Area", "Los Angeles", "Remote"),
        tracks=("new_grad", "summer_2027", "spring_coop"),
        target_role_types=("swe", "ml_ai", "data_engineer", "frontend_fullstack"),
        excluded_role_types=("data_scientist",),
    )


def test_full_date_is_truncated_to_month():
    data = valid() | {"graduation_date": datetime.date(2027, 5, 17)}
    assert parse_profile(data).graduation_date == datetime.date(2027, 5, 1)


def test_excluded_role_types_may_be_empty():
    assert parse_profile(valid() | {"excluded_role_types": []}).excluded_role_types == ()


@pytest.mark.parametrize(
    "change, message",
    [
        ({"degree": "bs"}, "degree must be one of"),
        ({"graduation_date": "May 2027"}, "YYYY-MM"),
        ({"graduation_date": "2027-13"}, "YYYY-MM"),
        ({"locations": []}, "at least one"),
        ({"locations": ["Bay Area", ""]}, "non-empty strings"),
        ({"tracks": ["fall_2027"]}, "unknown value(s) fall_2027"),
        ({"target_role_types": ["swe", "devops"]}, "unknown value(s) devops"),
        ({"excluded_role_types": ["swe"]}, "both targeted and excluded: swe"),
        ({"location": ["Remote"]}, "unknown field(s): location"),
    ],
)
def test_bad_values_are_rejected(change, message):
    with pytest.raises(ProfileError, match=re.escape(message)):
        parse_profile(valid() | change)


def test_missing_field_is_named():
    data = valid()
    del data["tracks"]
    with pytest.raises(ProfileError, match="missing field.*tracks"):
        parse_profile(data)


def test_missing_file_points_to_init(tmp_path):
    with pytest.raises(ProfileError, match="triage init"):
        load_profile(tmp_path / "profile.yaml")


def test_invalid_yaml_is_reported(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("degree: [unclosed\n")
    with pytest.raises(ProfileError, match="not valid YAML"):
        load_profile(path)


def test_profile_text_gets_the_same_checks_as_the_file():
    # The deployed API reads the profile's YAML from Parameter Store, not a file.
    assert profile_from_yaml(EXAMPLE.read_text()) == load_profile(EXAMPLE)
    with pytest.raises(ProfileError, match="the stored profile is not valid YAML"):
        profile_from_yaml("degree: [unclosed\n", source="the stored profile")


EXAMPLE_PLACES = ("Bay Area", "Los Angeles", "Remote")


@pytest.mark.parametrize(
    "location",
    [
        "Santa Clara, CA",
        "SF",
        "san jose, ca",
        "San Jose, CA +2",
        "US, CA, Santa Clara",  # Workday writes the country first
        "USA, CA, Los Angeles",
        "Seattle, WA; San Jose, CA",  # one match is enough
        "El Segundo, CA",
        "Remote in USA",
        "Remote (US)",
        "San Francisco Bay Area",
        "HQ (San Francisco, CA)",  # a real Ashby posting, Oct 29: a label with the place in parentheses
        "HQ: San Francisco, CA",
        "San Jose, CA (Hybrid)",
    ],
)
def test_places_in_a_profile_region_match(location):
    assert location_matches(location, EXAMPLE_PLACES)


@pytest.mark.parametrize(
    "location",
    [
        "Seattle, WA",
        "Irvine, CA",  # Orange County is not Los Angeles
        "San Diego, CA",
        "New York City, NY",
        "Bellevue, WA; Austin, TX",
        "USA, WA, Bellevue",
        "",
        "HQ (New York City, NY)",  # unwrapping a label doesn't make any place match
        "Office: Seattle, WA",
        "Austin, TX (Bay Area team)",  # a note isn't a place unless it is one exactly
    ],
)
def test_places_outside_every_region_do_not_match(location):
    assert not location_matches(location, EXAMPLE_PLACES)


def test_a_profile_location_that_is_not_a_region_is_taken_as_a_city():
    assert location_matches("Seattle, WA", ("Seattle, WA",))
    assert location_matches("Seattle", ("seattle",))
    assert not location_matches("Seattle, WA", ("Bay Area",))


def test_remote_needs_the_word_not_a_substring():
    assert not location_matches("Remotely Labs HQ, Boston, MA", ("Remote",))
