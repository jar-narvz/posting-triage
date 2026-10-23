"""The eval report: wiring, saved runs, and formatting, on small made-up inputs. Runs are
filled through batch.immediate with a fake client, so nothing touches the network."""

import datetime
import json
import os
from types import SimpleNamespace

import pytest

from posting_triage import run_eval
from posting_triage.batch import immediate
from posting_triage.evaluate import score
from posting_triage.profile import Profile
from posting_triage.run_eval import (
    collect, cost, format_confusion, load_env, real_postings, report, run_llm, texts,
)
from posting_triage.synthetic import generate
from test_batch import good, message

PROFILE = Profile(
    degree="bachelors",
    graduation_date=datetime.date(2027, 5, 1),
    locations=("Bay Area", "Los Angeles", "Remote"),
    tracks=("new_grad", "summer_2027", "spring_coop"),
    target_role_types=("swe", "ml_ai", "data_engineer", "frontend_fullstack"),
    excluded_role_types=("data_scientist",),
)
CANDIDATES = [
    {"id": "a1", "title": "Software Engineer, New Grad", "location": "San Jose, CA"},
    {"id": "b2", "title": "Senior Software Engineer", "location": "SF"},
    {"id": "c3", "title": "Unlabeled Engineer", "location": "SF"},
]
BLANK = {c: "" for c in run_eval.GOLD_COLUMNS}
LABELS = [
    BLANK | {"id": "a1", "gold_verdict": "apply", "deciding_field": "", "locations": "gold value, not shown"},
    BLANK | {"id": "b2", "gold_verdict": "skip", "deciding_field": "role_level"},
    BLANK | {"id": "zz", "gold_verdict": "skip", "deciding_field": "track"},  # not in candidates: dropped
]
MODEL = "claude-haiku-5-5"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "cache"
    d.mkdir()
    (d / "a1.json").write_text(json.dumps({"status": "ok", "text": "cached posting a1"}))
    (d / "b2.json").write_text(json.dumps({"status": "not_found", "text": ""}))
    monkeypatch.setattr(run_eval.cache, "CACHE_DIR", d)
    return d


def test_real_postings_use_the_listing_cached_text_and_gold(cache_dir):
    real = real_postings(LABELS, CANDIDATES, cache_dir)
    assert [(p["id"], p["location"], p["text"]) for p in real] == [
        ("a1", "San Jose, CA", "cached posting a1"),
        ("b2", "SF", ""),  # not cached as ok: no text for the LLM approaches
    ]
    assert real[0]["gold"]["locations"] == "gold value, not shown"
    assert texts(real) == {"a1": "cached posting a1"}


def perfect_client(postings):
    """A fake API that answers every extraction perfectly and every direct prompt with apply."""
    by_text = {p["text"]: p for p in postings}

    def create(**params):
        text = params["messages"][0]["content"].split("<posting>\n", 1)[1].split("\n</posting>", 1)[0]
        if "deciding_field" in params["output_config"]["format"]["schema"]["properties"]:
            return message({"verdict": "apply", "deciding_field": "none", "quotes": []})
        return good(by_text[text]["id"])

    return immediate(SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_only_baseline_until_runs_exist(tmp_path):
    synthetic = generate(n=10, seed=7)
    results, fields, incomplete = collect(tmp_path, PROFILE, synthetic, [MODEL])
    assert list(results) == ["baseline"] and fields == {}
    assert incomplete == {"direct · haiku-5-5": (0, 10), "pipeline · haiku-5-5": (0, 10)}


def test_saved_runs_are_scored(tmp_path, monkeypatch):
    synthetic = generate(n=10, seed=7)
    monkeypatch.setattr("test_batch.BY_ID", {p["id"]: p for p in synthetic})
    assert run_llm(perfect_client(synthetic), tmp_path, PROFILE, synthetic, [MODEL], log=lambda s: None)
    results, fields, incomplete = collect(tmp_path, PROFILE, synthetic, [MODEL])
    assert incomplete == {}
    pipeline = results["pipeline · haiku-5-5"]
    assert all(pipeline[p["id"]] == (p["gold_verdict"], p["deciding_field"]) for p in synthetic)
    assert all(fields["pipeline · haiku-5-5"][p["id"]] == p["gold"] for p in synthetic)
    assert set(results["direct · haiku-5-5"].values()) == {("apply", "")}


def test_report_has_tables_and_is_repeatable(tmp_path, cache_dir, monkeypatch):
    synthetic = generate(n=10, seed=7)
    monkeypatch.setattr("test_batch.BY_ID", {p["id"]: p for p in synthetic})
    run_llm(perfect_client(synthetic), tmp_path, PROFILE, synthetic, [MODEL], log=lambda s: None)
    text = report(10, 7, PROFILE, [], CANDIDATES, tmp_path, [MODEL])
    assert "Synthetic benchmark: 10 postings, seed 7" in text
    assert "Real spot check" not in text  # no labels passed, so no empty tables
    assert "pipeline extraction accuracy by field" in text
    assert "accuracy on postings with each hard case" in text
    pipeline_row = next(line for line in text.splitlines() if line.strip().startswith("pipeline · haiku"))
    assert pipeline_row.count("100%") == 4  # precision, recall, accuracy, right reason
    assert text == report(10, 7, PROFILE, [], CANDIDATES, tmp_path, [MODEL])


def test_report_refuses_runs_saved_for_other_posting_text(tmp_path, cache_dir, monkeypatch):
    synthetic = generate(n=10, seed=7)
    monkeypatch.setattr("test_batch.BY_ID", {p["id"]: p for p in synthetic})
    run_llm(perfect_client(synthetic), tmp_path, PROFILE, synthetic, [MODEL], log=lambda s: None)
    with pytest.raises(RuntimeError, match="changed since these responses were saved"):
        report(10, 8, PROFILE, [], CANDIDATES, tmp_path, [MODEL])  # same ids, another seed's postings


def test_unfinished_runs_are_named(tmp_path, cache_dir):
    text = report(5, 7, PROFILE, LABELS, CANDIDATES, tmp_path, [MODEL])
    assert "not finished: pipeline · haiku-5-5 (0/6 postings answered)" in text  # 5 synthetic + a1


def test_undefined_rates_print_as_n_a(tmp_path, cache_dir):
    text = report(5, 7, PROFILE, [LABELS[1]], CANDIDATES, tmp_path, [MODEL])
    assert "0/0 = n/a" in text.split("Real spot check")[1]  # recall with no gold applies


def test_confusion_rows_are_gold_and_columns_predicted():
    lines = format_confusion("x", score(["apply", "skip"], ["skip", "skip"]))
    assert lines[1].split() == ["apply", "flag", "skip"]
    assert lines[2].split() == ["apply", "0", "0", "1"]
    assert lines[4].split() == ["skip", "0", "0", "1"]


def test_cost_counts_cache_and_halves_for_batches():
    totals = {"input_tokens": 1_000_000, "output_tokens": 100_000,
              "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0}
    assert cost("claude-opus-5-5", totals, batch=False) == pytest.approx(4.00 + 2.00 + 0.40)
    assert cost("claude-opus-5-5", totals, batch=True) == pytest.approx(3.20)


def test_load_env_sets_missing_keys_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nPT_TEST_A="from file"\nPT_TEST_B=from file\n\n')
    monkeypatch.setenv("PT_TEST_B", "already set")
    monkeypatch.delenv("PT_TEST_A", raising=False)
    load_env(env)
    assert (os.environ["PT_TEST_A"], os.environ["PT_TEST_B"]) == ("from file", "already set")
    monkeypatch.delenv("PT_TEST_A")


def test_missing_env_file_is_fine(tmp_path):
    load_env(tmp_path / "nope")
