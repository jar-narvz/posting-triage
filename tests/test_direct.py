"""The direct-verdict comparison prompt. A fake `call` stands in for the API."""

import dataclasses
from pathlib import Path

import pytest

from posting_triage.direct import DirectAnswer, direct_verdict, parse, request_params, system
from posting_triage.extract import FIELD_GUIDE
from posting_triage.profile import load_profile
from posting_triage.rules import RULE_ORDER, Verdict
from test_extract_requests import FakeClient, reply

PROFILE = load_profile(Path(__file__).parent.parent / "profile.example.yaml")


def answer(verdict, field, quotes=()):
    return reply({"verdict": verdict, "deciding_field": field, "quotes": list(quotes)})


def test_prompt_has_the_profile_the_rules_and_the_shared_field_guide():
    prompt = system(PROFILE)
    for text in ("degree: bachelors, graduating 2027-05", "locations: Bay Area, Los Angeles, Remote",
                 "excluded role types: data_scientist", "More than 1 year required is skip", FIELD_GUIDE):
        assert text in prompt


def test_prompt_follows_the_profile():
    seattle = dataclasses.replace(PROFILE, locations=("Seattle, WA",), excluded_role_types=())
    prompt = system(seattle)
    assert "locations: Seattle, WA" in prompt and "excluded role types: none" in prompt


def test_rules_are_listed_in_the_rules_module_order():
    prompt = system(PROFILE)
    positions = [prompt.index(f"{i}. {field}:") for i, field in enumerate(RULE_ORDER, 1)]
    assert positions == sorted(positions)


def test_deciding_fields_are_the_rule_fields_plus_none():
    allowed = DirectAnswer.model_json_schema()["properties"]["deciding_field"]["enum"]
    assert set(allowed) == set(RULE_ORDER) | {"none"}


def test_request_uses_structured_output_and_the_posting():
    params = request_params("posting text", PROFILE, "claude-sonnet-5-5")
    assert params["model"] == "claude-sonnet-5-5"
    assert params["output_config"]["effort"] == "medium"
    assert params["output_config"]["format"]["schema"] == DirectAnswer.model_json_schema()
    assert params["messages"] == [{"role": "user", "content": "<posting>\nposting text\n</posting>"}]


@pytest.mark.parametrize(
    "response, expected",
    [
        (answer("skip", "degree", ["PhD required"]), Verdict("skip", "degree", "PhD required")),
        (answer("flag", "location", ["Seattle", "Remote"]), Verdict("flag", "location", "Seattle; Remote")),
        (answer("apply", "none"), Verdict("apply", "", None)),
        (answer("apply", "degree", ["ignored"]), Verdict("apply", "", None)),  # apply has no deciding field
        (answer("skip", "none"), Verdict("skip", "", None)),  # kept as given: counts against deciding-field accuracy
    ],
)
def test_parse(response, expected):
    assert parse(response) == expected


@pytest.mark.parametrize(
    "response",
    [reply("not json"), reply({"verdict": "skip"}), reply({}, "refusal"), reply({}, "max_tokens")],
    ids=["not json", "missing fields", "refusal", "cut off"],
)
def test_no_usable_answer_is_flag(response):
    assert direct_verdict("text", PROFILE, FakeClient(response), "m") == Verdict("flag", "quote", None)


def test_one_request_no_retry():
    call = FakeClient(answer("skip", "location", ["Seattle, WA"]))
    assert direct_verdict("text", PROFILE, call, "m").verdict == "skip"
    assert len(call.requests) == 1
