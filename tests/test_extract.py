"""The extraction schema, its conversion to the labels.csv format, and the quote check.
No API calls: extractions are built by hand or from the synthetic answer key."""

import pytest

from posting_triage.extract import Extraction, json_schema, normalize, problems, to_fields, to_quotes
from posting_triage.rules import RULE_ORDER
from posting_triage.synthetic import generate


def perfect(posting):
    """The extraction a flawless reader would return for a synthetic posting."""
    g, q = posting["gold"], posting["quotes"]
    return Extraction.model_validate({
        "role_type": {"value": g["role_type"], "quote": q["role_type"]},
        # A full-time title with no term is new grad by the guide; the title is the evidence.
        "track": {"value": g["track"], "quote": q["track"] or q["role_level"]},
        "degree": {"value": g["degree"] or None, "strength": g["degree_strength"] or None, "quote": q["degree"]},
        "role_level": {"value": g["role_level"], "quote": q["role_level"]},
        "experience": {"years": float(g["experience_years"]) if g["experience_years"] else None,
                       "strength": g["experience_strength"] or None, "quote": q["experience"]},
        "graduation": {"start": g["grad_start"] or None, "end": g["grad_end"] or None, "quote": q["graduation"]},
        "location": {"places": [p.strip() for p in g["locations"].split(";") if p.strip()],
                     "remote": g["remote"] == "true", "quote": q["location"]},
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
    data["degree"] = {"value": "bachelors", "strength": "required", "quote": "Bachelor's degree required"}
    assert "degree" in problems(Extraction.model_validate(data), text())


def test_value_without_quote_is_caught_but_silence_is_not():
    data = sample().model_dump()
    data["experience"] = {"years": 3, "strength": "required", "quote": None}
    assert problems(Extraction.model_validate(data), text()) == {"experience": "has a value but no quote"}
    data["experience"] = {"years": None, "strength": None, "quote": None}
    assert "experience" not in problems(Extraction.model_validate(data), text())


def test_blank_quote_counts_as_missing():
    data = sample().model_dump()
    data["role_type"]["quote"] = "   "
    assert problems(Extraction.model_validate(data), text()) == {"role_type": "has a value but no quote"}


def test_bad_month_format_is_a_problem():
    data = sample().model_dump()
    data["graduation"] = {"start": "Dec 2026", "end": None, "quote": None}
    assert "graduation" in problems(Extraction.model_validate(data), text())


def test_quote_match_ignores_whitespace_and_curly_quotes_only():
    posting = "Requirements\n- Bachelor’s degree in\n   Computer Science"
    data = sample().model_dump()
    data["degree"] = {"value": "bachelors", "strength": "required", "quote": "Bachelor's degree in Computer Science"}
    e = Extraction.model_validate(data)
    assert "degree" not in problems(e, posting)
    data["degree"]["quote"] = "bachelor's degree in computer science"  # case still matters
    assert "degree" in problems(Extraction.model_validate(data), posting)


def test_normalize():
    assert normalize("  a\n\tb  “c” ‘d’ ") == "a b \"c\" 'd'"


@pytest.mark.parametrize("years, expected", [(0.0, "0"), (1.0, "1"), (0.5, "0.5"), (None, "")])
def test_years_are_written_like_labels(years, expected):
    data = sample().model_dump()
    data["experience"] = {"years": years, "strength": "required" if years is not None else None, "quote": "x"}
    assert to_fields(Extraction.model_validate(data))["experience_years"] == expected


def test_strength_defaults_to_required_and_is_blank_without_a_value():
    data = sample().model_dump()
    data["degree"] = {"value": "masters", "strength": None, "quote": "x"}
    data["experience"] = {"years": None, "strength": "preferred", "quote": None}
    fields = to_fields(Extraction.model_validate(data))
    assert (fields["degree_strength"], fields["experience_strength"]) == ("required", "")
    data["degree"] = {"value": "none", "strength": "required", "quote": "x"}
    assert to_fields(Extraction.model_validate(data))["degree_strength"] == ""
