import datetime
import re
from pathlib import Path

import pytest

from posting_triage.profile import Profile, ProfileError, load_profile, parse_profile

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
