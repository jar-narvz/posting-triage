"""The extraction request, response parsing, the one retry, and the pipeline verdict.
A fake `call` stands in for client.messages.create, so nothing touches the network."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from posting_triage.extract import (
    SYSTEM, ExtractionError, extract, json_schema, parse, pipeline_verdict, request_params,
)
from posting_triage.profile import load_profile
from posting_triage.synthetic import generate
from test_extract import perfect

PROFILE = load_profile(Path(__file__).parent.parent / "profile.example.yaml")
POSTING = generate(n=1, seed=1)[0]


def reply(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="thinking", thinking=""),
                                                            SimpleNamespace(type="text", text=text)])


class FakeClient:
    """Returns the given responses in order and records every request."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, **params):
        self.requests.append(params)
        return self.responses.pop(0)


def good():
    return perfect(POSTING).model_dump()


def with_bad_quote():
    data = good()
    data["degree"] = {"value": "bachelors", "strength": "required", "quotes": ["Bachelor's degree required, invented"]}
    return data


def test_request_carries_schema_effort_and_cached_instructions():
    params = request_params("posting text", "claude-haiku-5-5")
    assert params["model"] == "claude-haiku-5-5"
    assert params["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": json_schema()}}
    assert params["system"] == [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    assert params["messages"] == [{"role": "user", "content": "<posting>\nposting text\n</posting>"}]
    assert "temperature" not in params  # removed from the API


def test_instructions_never_mention_the_profile():
    # "target" too: the reader can't know which role types the profile targets.
    for word in ("profile", "target", "Bay Area", "2027-05", "May 2027"):
        assert word not in SYSTEM


def test_parse_reads_the_text_block_after_thinking():
    assert parse(reply(good())) == perfect(POSTING)


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_parse_rejects_cut_off_or_refused_output(stop_reason):
    with pytest.raises(ExtractionError, match=stop_reason):
        parse(reply(good(), stop_reason))


def test_clean_first_answer_needs_no_retry():
    call = FakeClient(reply(good()))
    e, found = extract(POSTING["text"], call, "m")
    assert (e, found, len(call.requests)) == (perfect(POSTING), {}, 1)


def test_bad_quote_gets_one_retry_that_names_the_problem():
    call = FakeClient(reply(with_bad_quote()), reply(good()))
    e, found = extract(POSTING["text"], call, "m")
    assert found == {} and len(call.requests) == 2
    note = call.requests[1]["messages"][0]["content"]
    assert "degree: quote not found" in note and "invented" in note


def test_still_bad_after_the_retry_is_reported_not_retried_again():
    call = FakeClient(reply(with_bad_quote()), reply(with_bad_quote()))
    e, found = extract(POSTING["text"], call, "m")
    assert list(found) == ["degree"] and len(call.requests) == 2


def test_unreadable_response_is_retried_too():
    call = FakeClient(reply("not json"), reply(good()))
    assert extract(POSTING["text"], call, "m") == (perfect(POSTING), {})


def test_pipeline_verdict_matches_gold_for_a_perfect_reader():
    for posting in generate(n=40, seed=3):
        v = pipeline_verdict(posting["text"], PROFILE, FakeClient(reply(perfect(posting).model_dump())), "m")
        assert (v.verdict, v.field) == (posting["gold_verdict"], posting["deciding_field"]), posting["id"]


def test_pipeline_flags_on_a_quote_that_never_checks_out():
    call = FakeClient(reply(with_bad_quote()), reply(with_bad_quote()))
    v = pipeline_verdict(POSTING["text"], PROFILE, call, "m")
    assert (v.verdict, v.field, v.quote) == ("flag", "quote", "Bachelor's degree required, invented")


def test_pipeline_flags_when_no_form_comes_back():
    call = FakeClient(reply(good(), "refusal"), reply(good(), "refusal"))
    v = pipeline_verdict(POSTING["text"], PROFILE, call, "m")
    assert (v.verdict, v.field) == ("flag", "quote")
