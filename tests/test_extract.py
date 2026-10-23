"""The extraction schema, its conversion to the labels.csv format, and the quote check.
No API calls: extractions are built by hand or from the synthetic answer key."""

import pytest

from posting_triage.extract import Extraction, json_schema, normalize, problems, to_fields, to_quotes
from posting_triage.rules import RULE_ORDER
from posting_triage.synthetic import generate


def listed(quote):
    return [quote] if quote else []


def perfect(posting):
    """The extraction a flawless reader would return for a synthetic posting."""
    g, q = posting["gold"], posting["quotes"]
    return Extraction.model_validate({
        "role_type": {"value": g["role_type"], "quotes": listed(q["role_type"])},
        # A full-time title with no term is new grad by the guide; the title is the evidence.
        "track": {"value": g["track"], "quotes": listed(q["track"] or q["role_level"])},
        "degree": {"value": g["degree"] or None, "strength": g["degree_strength"] or None, "quotes": listed(q["degree"])},
        "role_level": {"value": g["role_level"], "quotes": listed(q["role_level"])},
        "experience": {"years": float(g["experience_years"]) if g["experience_years"] else None,
                       "strength": g["experience_strength"] or None, "quotes": listed(q["experience"])},
        "graduation": {"start": g["grad_start"] or None, "end": g["grad_end"] or None, "quotes": listed(q["graduation"])},
        "location": {"places": [p.strip() for p in g["locations"].split(";") if p.strip()],
                     "remote": g["remote"] == "true", "quotes": listed(q["location"])},
    })


@pytest.mark.parametrize("posting", generate(), ids=lambda p: p["id"])
def test_a_perfect_extraction_converts_to_gold_and_passes_the_quote_check(posting):
    e = perfect(posting)
    assert to_fields(e) == posting["gold"]
    assert problems(e, posting["text"]) == {}


def sample():
    return perfect(generate(n=1, seed=1)[0])


def text():
    return generate(n=1, seed=1)[0]["text"]


def test_entries_match_the_rule_order():
    assert list(Extraction.model_fields) == RULE_ORDER
    assert list(to_quotes(sample())) == RULE_ORDER


def test_schema_suits_structured_outputs():
    """Every object lists all its properties as required and allows nothing extra."""
    schema = json_schema()
    objects = [schema, *schema["$defs"].values()]
    for obj in objects:
        assert obj["additionalProperties"] is False, obj.get("title")
        assert set(obj["required"]) == set(obj["properties"]), obj.get("title")


def test_invented_quote_is_caught():
    data = sample().model_dump()
    data["degree"] = {"value": "bachelors", "strength": "required", "quotes": ["Bachelor's degree required"]}
    assert "degree" in problems(Extraction.model_validate(data), text())


def test_value_without_quote_is_caught_but_silence_is_not():
    data = sample().model_dump()
    data["experience"] = {"years": 3, "strength": "required", "quotes": []}
    assert problems(Extraction.model_validate(data), text()) == {"experience": "has a value but no quote"}
    data["experience"] = {"years": None, "strength": None, "quotes": []}
    assert "experience" not in problems(Extraction.model_validate(data), text())


def test_blank_quote_counts_as_missing():
    data = sample().model_dump()
    data["role_type"]["quotes"] = ["   "]
    assert problems(Extraction.model_validate(data), text()) == {"role_type": "has a value but no quote"}


def test_bad_month_format_is_a_problem():
    data = sample().model_dump()
    data["graduation"] = {"start": "Dec 2026", "end": None, "quotes": []}
    assert "graduation" in problems(Extraction.model_validate(data), text())


def test_quote_match_ignores_whitespace_and_curly_quotes_only():
    posting = "Requirements\n- Bachelor’s degree in\n   Computer Science"
    data = sample().model_dump()
    data["degree"] = {"value": "bachelors", "strength": "required", "quotes": ["Bachelor's degree in Computer Science"]}
    e = Extraction.model_validate(data)
    assert "degree" not in problems(e, posting)
    data["degree"]["quotes"] = ["bachelor's degree in computer science"]  # case still matters
    assert "degree" in problems(Extraction.model_validate(data), posting)


def test_normalize():
    assert normalize("  a\n\tb  “c” ‘d’ ") == "a b \"c\" 'd'"


@pytest.mark.parametrize("years, expected", [(0.0, "0"), (1.0, "1"), (0.5, "0.5"), (None, "")])
def test_years_are_written_like_labels(years, expected):
    data = sample().model_dump()
    data["experience"] = {"years": years, "strength": "required" if years is not None else None, "quotes": ["x"]}
    assert to_fields(Extraction.model_validate(data))["experience_years"] == expected


def test_strength_defaults_to_required_and_is_blank_without_a_value():
    data = sample().model_dump()
    data["degree"] = {"value": "masters", "strength": None, "quotes": ["x"]}
    data["experience"] = {"years": None, "strength": "preferred", "quotes": []}
    fields = to_fields(Extraction.model_validate(data))
    assert (fields["degree_strength"], fields["experience_strength"]) == ("required", "")
    data["degree"] = {"value": "none", "strength": "required", "quotes": ["x"]}
    assert to_fields(Extraction.model_validate(data))["degree_strength"] == ""


def test_quotes_from_separate_places_each_pass():
    posting = "Location: San Francisco, CA\nAbout us\nWe also hire in Los Angeles, CA."
    data = sample().model_dump()
    data["location"] = {"places": ["San Francisco, CA", "Los Angeles, CA"], "remote": False,
                        "quotes": ["San Francisco, CA", "We also hire in Los Angeles, CA."]}
    e = Extraction.model_validate(data)
    assert "location" not in problems(e, posting)
    assert to_quotes(e)["location"] == "San Francisco, CA; We also hire in Los Angeles, CA."


def test_one_bad_quote_among_good_ones_is_named():
    posting = "Location: San Francisco, CA"
    data = sample().model_dump()
    data["location"] = {"places": ["San Francisco, CA", "Austin, TX"], "remote": False,
                        "quotes": ["San Francisco, CA", "Austin, TX"]}
    assert problems(Extraction.model_validate(data), posting)["location"] == "quote not found in the posting: 'Austin, TX'"


def test_silent_field_has_no_reason_quote():
    data = sample().model_dump()
    data["experience"] = {"years": None, "strength": None, "quotes": []}
    assert to_quotes(Extraction.model_validate(data))["experience"] is None
