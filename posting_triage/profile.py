"""Load and validate profile.yaml."""

import datetime
from dataclasses import dataclass
from pathlib import Path

import yaml

DEGREES = ("none", "bachelors", "masters", "phd")
TRACKS = ("new_grad", "summer_2027", "spring_coop")
ROLE_TYPES = ("swe", "ml_ai", "data_engineer", "data_scientist", "frontend_fullstack", "other")
FIELDS = (
    "degree",
    "graduation_date",
    "locations",
    "tracks",
    "target_role_types",
    "excluded_role_types",
)


class ProfileError(ValueError):
    """profile.yaml is missing, malformed, or has a bad value."""


@dataclass(frozen=True)
class Profile:
    degree: str
    graduation_date: datetime.date  # always the 1st of the month
    locations: tuple[str, ...]
    tracks: tuple[str, ...]
    target_role_types: tuple[str, ...]
    excluded_role_types: tuple[str, ...]


def load_profile(path="profile.yaml"):
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ProfileError(f"{path} not found; run `triage init` to create it") from None
    except yaml.YAMLError as e:
        raise ProfileError(f"{path} is not valid YAML: {e}") from None
    return parse_profile(data)


def parse_profile(data):
    if not isinstance(data, dict):
        raise ProfileError("profile must be a mapping of field: value")
    missing = [f for f in FIELDS if f not in data]
    if missing:
        raise ProfileError(f"missing field(s): {', '.join(missing)}")
    unknown = sorted(set(data) - set(FIELDS))
    if unknown:
        # Catches typos like `location:` that would otherwise be silently ignored.
        raise ProfileError(f"unknown field(s): {', '.join(unknown)}")

    target = parse_choices("target_role_types", data["target_role_types"], ROLE_TYPES)
    excluded = parse_choices(
        "excluded_role_types", data["excluded_role_types"], ROLE_TYPES, allow_empty=True
    )
    both = sorted(set(target) & set(excluded))
    if both:
        raise ProfileError(f"role type(s) both targeted and excluded: {', '.join(both)}")

    return Profile(
        degree=parse_degree(data["degree"]),
        graduation_date=parse_month(data["graduation_date"]),
        locations=parse_strings("locations", data["locations"]),
        tracks=parse_choices("tracks", data["tracks"], TRACKS),
        target_role_types=target,
        excluded_role_types=excluded,
    )


def parse_degree(value):
    if value not in DEGREES:
        raise ProfileError(f"degree must be one of {', '.join(DEGREES)} (got {value!r})")
    return value


def parse_month(value):
    """Accept "YYYY-MM" (or a full date YAML already parsed) and return the 1st of that month."""
    if isinstance(value, datetime.date):
        return value.replace(day=1)
    try:
        return datetime.datetime.strptime(str(value), "%Y-%m").date()
    except ValueError:
        raise ProfileError(f"graduation_date must be YYYY-MM, e.g. 2027-05 (got {value!r})") from None


def parse_strings(name, value, allow_empty=False):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ProfileError(f"{name} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise ProfileError(f"{name} must list at least one entry")
    return tuple(v.strip() for v in value)


def parse_choices(name, value, allowed, allow_empty=False):
    items = parse_strings(name, value, allow_empty)
    bad = [v for v in items if v not in allowed]
    if bad:
        raise ProfileError(
            f"{name}: unknown value(s) {', '.join(bad)}; choose from {', '.join(allowed)}"
        )
    return items
