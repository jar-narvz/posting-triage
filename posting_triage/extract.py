"""Stage 2: the LLM fills the eligibility-field schema, each value with its quote.
Quotes are checked against the posting text; a missing quote gets one retry.

This module holds the schema the LLM must fill, the conversion of its answer into
the labels.csv format the rules read, and the quote check (decision 2).
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

Strength = Literal["required", "preferred"] | None


class Part(BaseModel):
    # Structured outputs need every property listed and nothing extra allowed.
    model_config = ConfigDict(extra="forbid")


class RoleType(Part):
    value: Literal["swe", "ml_ai", "data_engineer", "data_scientist", "frontend_fullstack", "other", "ambiguous"]
    quote: str | None


class Track(Part):
    value: Literal["new_grad", "summer_2027", "spring_coop", "other"] | None
    quote: str | None


class RoleLevel(Part):
    value: Literal["intern", "new_grad", "entry", "mid", "senior", "unclear"]
    quote: str | None


class Degree(Part):
    value: Literal["none", "bachelors", "masters", "phd"] | None
    strength: Strength
    quote: str | None


class Experience(Part):
    years: float | None
    strength: Strength
    quote: str | None


class Graduation(Part):
    start: str | None  # YYYY-MM
    end: str | None
    quote: str | None


class Location(Part):
    places: list[str]
    remote: bool
    quote: str | None


class Extraction(Part):
    """One entry per verdict rule, named as in rules.RULE_ORDER."""
    role_type: RoleType
    track: Track
    degree: Degree
    role_level: RoleLevel
    experience: Experience
    graduation: Graduation
    location: Location


def json_schema():
    """The schema for output_config.format."""
    return Extraction.model_json_schema()


def to_fields(e):
    """The labels.csv form of an extraction: strings, "" for silent, as rules.decide reads them."""
    has_degree = e.degree.value not in (None, "none")
    return {
        "role_type": e.role_type.value,
        "track": e.track.value or "",
        "degree": e.degree.value or "",
        "degree_strength": (e.degree.strength or "required") if has_degree else "",
        "role_level": e.role_level.value,
        "experience_years": "" if e.experience.years is None else f"{e.experience.years:g}",
        "experience_strength": "" if e.experience.years is None else e.experience.strength or "required",
        "grad_start": e.graduation.start or "",
        "grad_end": e.graduation.end or "",
        "locations": "; ".join(p.strip() for p in e.location.places if p.strip()),
        "remote": "true" if e.location.remote else "false",
    }


def to_quotes(e):
    return {name: getattr(e, name).quote for name in Extraction.model_fields}


# ---------------------------------------------------------------------------
# Quote check (decision 2)

QUOTE_MARKS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def normalize(text):
    """Collapse whitespace and treat curly and straight quotes alike; nothing looser."""
    return " ".join(text.translate(QUOTE_MARKS).split())


def problems(e, text):
    """Field name -> what's wrong with it. Empty means every value traces to the posting.
    These fields get one retry; any still listed after it make the verdict FLAG."""
    haystack = normalize(text)
    found = {}
    fields = to_fields(e)
    stated = {
        "role_type": True,
        "track": bool(fields["track"]),
        "degree": bool(fields["degree"]),
        "role_level": True,
        "experience": bool(fields["experience_years"]),
        "graduation": bool(fields["grad_start"] or fields["grad_end"]),
        "location": bool(fields["locations"]) or e.location.remote,
    }
    for name, quote in to_quotes(e).items():
        quote = normalize(quote or "")  # "" is in every text, so a blank quote counts as none
        if quote and quote not in haystack:
            found[name] = f"quote not found in the posting: {quote!r}"
        elif not quote and stated[name]:
            found[name] = "has a value but no quote"
    for month in (e.graduation.start, e.graduation.end):
        if month is not None and not MONTH.fullmatch(month):
            found["graduation"] = f"month must be YYYY-MM, got {month!r}"
    return found
