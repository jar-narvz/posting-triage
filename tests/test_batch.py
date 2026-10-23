"""The batch runner, against a fake Batches API: rounds, resuming, retries, and saved results."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import Message

from posting_triage.batch import Pending, Replay, advance, load_saved, token_totals
from posting_triage.direct import direct_verdict
from posting_triage.extract import pipeline_verdict
from posting_triage.profile import load_profile
from posting_triage.synthetic import generate
from test_extract import perfect

PROFILE = load_profile(Path(__file__).parent.parent / "profile.example.yaml")
POSTINGS = generate(n=6, seed=11)
TEXTS = {p["id"]: p["text"] for p in POSTINGS}
BY_ID = {p["id"]: p for p in POSTINGS}


def message(payload, stop_reason="end_turn", tokens=(100, 20)):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return Message.model_validate({
        "id": "msg_x", "type": "message", "role": "assistant", "model": "m",
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
    })


class FakeBatches:
    """Answers each request with respond(custom_id, round); batches end when `ready` is set."""

    def __init__(self, respond):
        self.respond, self.ready, self.created = respond, False, []

    def create(self, requests):
        self.created.append(list(requests))
        return SimpleNamespace(id=f"batch_{len(self.created)}")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended" if self.ready else "in_progress")

    def results(self, batch_id):
        k = int(batch_id.split("_")[1])
        for request in self.created[k - 1]:
            answer = self.respond(request["custom_id"], k)
            result = (SimpleNamespace(type="succeeded", message=answer) if isinstance(answer, Message)
                      else SimpleNamespace(type=answer, message=None))
            yield SimpleNamespace(custom_id=request["custom_id"], result=result)


def client_for(respond):
    batches = FakeBatches(respond)
    return SimpleNamespace(messages=SimpleNamespace(batches=batches)), batches


def pipeline(text, call):
    return pipeline_verdict(text, PROFILE, call, "m")


def good(pid):
    return message(perfect(BY_ID[pid]).model_dump())


def bad_quote(pid):
    data = perfect(BY_ID[pid]).model_dump()
    data["degree"] = {"value": "bachelors", "strength": "required", "quotes": ["not in the posting"]}
    return message(data)


def run_to_end(client, batches, run_dir, solve):
    for _ in range(10):
        batches.ready = False
        assert advance(client, run_dir, TEXTS, solve, log=lambda s: None) is None  # submits a round, or finds it unfinished
        assert advance(client, run_dir, TEXTS, solve, log=lambda s: None) is None  # still running
        batches.ready = True
        out = advance(client, run_dir, TEXTS, solve, log=lambda s: None)
        if out is not None:
            return out
    raise AssertionError("never finished")


def test_replay_returns_saved_responses_then_asks_for_the_next_request():
    call = Replay(["first"])
    assert call(model="m") == "first"
    with pytest.raises(Pending) as p:
        call(model="m", messages=[])
    assert p.value.params == {"model": "m", "messages": []}


def test_pipeline_retries_only_failed_postings_in_a_second_round(tmp_path):
    first = sorted(TEXTS)[0]
    client, batches = client_for(lambda pid, k: bad_quote(pid) if (pid, k) == (first, 1) else good(pid))
    out = run_to_end(client, batches, tmp_path, pipeline)
    assert [len(b) for b in batches.created] == [6, 1]
    assert batches.created[1][0]["custom_id"] == first
    assert "quote not found" in batches.created[1][0]["params"]["messages"][0]["content"]
    for pid, v in out.items():
        assert (v.verdict, v.field) == (BY_ID[pid]["gold_verdict"], BY_ID[pid]["deciding_field"])


def test_finished_run_is_read_from_disk_without_new_batches(tmp_path):
    client, batches = client_for(lambda pid, k: good(pid))
    first = run_to_end(client, batches, tmp_path, pipeline)
    again = advance(client, tmp_path, TEXTS, pipeline, log=lambda s: None)
    assert again == first and len(batches.created) == 1


def test_errored_request_is_retried_by_the_pipeline(tmp_path):
    victim = sorted(TEXTS)[2]
    client, batches = client_for(lambda pid, k: "errored" if (pid, k) == (victim, 1) else good(pid))
    out = run_to_end(client, batches, tmp_path, pipeline)
    assert [len(b) for b in batches.created] == [6, 1]
    assert out[victim].verdict == BY_ID[victim]["gold_verdict"]


def test_errored_request_is_flag_for_the_direct_prompt(tmp_path):
    def direct(text, call):
        return direct_verdict(text, PROFILE, call, "m")

    answer = message({"verdict": "apply", "deciding_field": "none", "quotes": []})
    client, batches = client_for(lambda pid, k: "expired" if pid == sorted(TEXTS)[0] else answer)
    out = run_to_end(client, batches, tmp_path, direct)
    assert len(batches.created) == 1  # no retry round
    assert out[sorted(TEXTS)[0]].verdict == "flag"
    assert {v.verdict for pid, v in out.items() if pid != sorted(TEXTS)[0]} == {"apply"}


def test_a_run_directory_belongs_to_one_set_of_postings(tmp_path):
    client, batches = client_for(lambda pid, k: good(pid))
    advance(client, tmp_path, TEXTS, pipeline, log=lambda s: None)
    fewer = dict(list(TEXTS.items())[:3])
    with pytest.raises(RuntimeError, match="new run name"):
        advance(client, tmp_path, fewer, pipeline, log=lambda s: None)


def test_saved_responses_and_token_totals(tmp_path):
    client, batches = client_for(lambda pid, k: good(pid))
    run_to_end(client, batches, tmp_path, pipeline)
    saved, rounds = load_saved(tmp_path)
    assert rounds == 1 and set(saved) == set(TEXTS)
    assert token_totals(tmp_path)["input_tokens"] == 600
    assert token_totals(tmp_path)["output_tokens"] == 120
