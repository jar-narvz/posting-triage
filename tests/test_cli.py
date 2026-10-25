import json
from pathlib import Path

import anthropic
import pytest

from posting_triage.cli import DEFAULT_MODEL, format_triage, main
from posting_triage.triage import Triage, TriageResponse

EXAMPLE_PROFILE = str(Path(__file__).parent.parent / "profile.example.yaml")
BOARD_URL = "https://job-boards.greenhouse.io/acme/jobs/1"
WORKDAY_URL = "https://acme.wd1.myworkdayjobs.com/job/2"


@pytest.mark.parametrize("result, expected", [
    (Triage("u", "apply", "", None), "APPLY  u"),
    (Triage("u", "skip", "role_level", "Senior Software Engineer"),
     'SKIP   u\n       role_level: "Senior Software Engineer"'),
    (Triage("u", "flag", "liveness", None, detail="HTTP 403"), "FLAG   u\n       couldn't verify (HTTP 403)"),
    (Triage("u", "flag", "quote", "BS required"), 'FLAG   u\n       quote not in the posting: "BS required"'),
    (Triage("u", "flag", "quote", None), "FLAG   u\n       no usable reading of the posting"),
    (Triage("u", "dead", "liveness", None, "https://acme.example/", "HTTP 404"),
     "DEAD   u\n       careers page: https://acme.example/"),
    (Triage("u", "dead", "liveness", None, None, "HTTP 404; company board gone too"),
     "DEAD   u\n       HTTP 404; company board gone too"),
])
def test_format_triage(result, expected):
    assert format_triage(result) == expected


@pytest.fixture
def run_env(monkeypatch):
    """A key in the environment, no .env read, and a fake triage() that records its calls."""
    monkeypatch.setattr("posting_triage.cli.load_env", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("posting_triage.cli.Browser", FakeBrowser)
    calls = []

    def fake_triage(url, profile, call, model, browser, effort):
        calls.append((url, model, browser, effort))
        return Triage(url, "apply", "", None)

    monkeypatch.setattr("posting_triage.cli.triage", fake_triage)
    return calls


def test_run_triages_each_url_with_the_default_model(run_env, capsys):
    assert main(["run", BOARD_URL, WORKDAY_URL, "--profile", EXAMPLE_PROFILE]) == 0
    assert [(url, model, effort) for url, model, _, effort in run_env] == [
        (BOARD_URL, DEFAULT_MODEL, "medium"), (WORKDAY_URL, DEFAULT_MODEL, "medium")]
    assert run_env[0][2] is None  # no browser for a board-API link
    assert isinstance(run_env[1][2], FakeBrowser)
    assert FakeBrowser.closed
    assert capsys.readouterr().out == f"APPLY  {BOARD_URL}\nAPPLY  {WORKDAY_URL}\n"


def test_run_takes_another_model(run_env):
    assert main(["run", BOARD_URL, "--profile", EXAMPLE_PROFILE, "--model", "claude-opus-5-5"]) == 0
    assert run_env[0][1] == "claude-opus-5-5"


def test_run_without_a_profile_says_to_run_init(run_env, tmp_path, capsys):
    assert main(["run", BOARD_URL, "--profile", str(tmp_path / "profile.yaml")]) == 1
    assert "triage init" in capsys.readouterr().out
    assert run_env == []


def test_run_without_a_key_stops_before_fetching(run_env, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert main(["run", BOARD_URL, "--profile", EXAMPLE_PROFILE]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out
    assert run_env == []


class FakeAPIError(anthropic.APIError):
    def __init__(self, message):  # skip the SDK's request/body arguments
        Exception.__init__(self, message)


def test_an_api_error_on_one_posting_still_triages_the_rest(run_env, monkeypatch, capsys):
    def flaky(url, profile, call, model, browser, effort):
        if url == BOARD_URL:
            raise FakeAPIError("connection reset")
        return Triage(url, "skip", "degree", "PhD required")

    monkeypatch.setattr("posting_triage.cli.triage", flaky)
    assert main(["run", BOARD_URL, WORKDAY_URL, "--profile", EXAMPLE_PROFILE]) == 1
    out = capsys.readouterr().out
    assert f"ERROR  {BOARD_URL}\n       FakeAPIError: connection reset" in out
    assert f'SKIP   {WORKDAY_URL}\n       degree: "PhD required"' in out


def test_run_json_prints_one_response_per_url(run_env, capsys):
    assert main(["run", BOARD_URL, WORKDAY_URL, "--profile", EXAMPLE_PROFILE, "--json"]) == 0
    lines = capsys.readouterr().out.splitlines()
    responses = [TriageResponse.model_validate(json.loads(line)) for line in lines]
    assert [(r.url, r.verdict, r.model) for r in responses] == [
        (BOARD_URL, "apply", DEFAULT_MODEL), (WORKDAY_URL, "apply", DEFAULT_MODEL)]
    assert all(r.latency_ms >= 0 for r in responses)


def test_run_json_sends_errors_to_stderr(run_env, monkeypatch, capsys):
    def flaky(url, profile, call, model, browser, effort):
        if url == BOARD_URL:
            raise FakeAPIError("connection reset")
        return Triage(url, "skip", "degree", "PhD required")

    monkeypatch.setattr("posting_triage.cli.triage", flaky)
    assert main(["run", BOARD_URL, WORKDAY_URL, "--profile", EXAMPLE_PROFILE, "--json"]) == 1
    captured = capsys.readouterr()
    assert f"ERROR  {BOARD_URL}" in captured.err
    assert [json.loads(line)["url"] for line in captured.out.splitlines()] == [WORKDAY_URL]


def test_cache_command_fetches_every_candidate(tmp_path, monkeypatch, capsys):
    from posting_triage.liveness import PostingText

    candidates = tmp_path / "candidates.csv"
    candidates.write_text(
        "id,url,company,title,location,source,section,tags\n"
        "aaa,https://boards.greenhouse.io/acme/jobs/1,Acme,SWE,SF,s,x,\n"
        "bbb,https://acme.wd1.myworkdayjobs.com/job/2,Acme,MLE,SF,s,x,\n"
    )
    fetched = []

    def fake_fetch_posting(url, browser):
        fetched.append((url, browser))
        return PostingText("ok", "browser" if browser else "greenhouse", "text")

    monkeypatch.setattr("posting_triage.cli.fetch_posting", fake_fetch_posting)
    monkeypatch.setattr("posting_triage.cli.Browser", FakeBrowser)
    cache_dir = tmp_path / "cache"
    args = ["cache", "--candidates", str(candidates), "--cache-dir", str(cache_dir), "--delay", "0"]

    assert main(args) == 0
    assert [url for url, _ in fetched] == [
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://acme.wd1.myworkdayjobs.com/job/2",
    ]
    assert fetched[0][1] is None  # browser not started for the API link
    assert isinstance(fetched[1][1], FakeBrowser)
    assert FakeBrowser.closed
    assert sorted(p.name for p in cache_dir.iterdir()) == ["aaa.json", "bbb.json"]
    assert "2 candidates: 2 ok" in capsys.readouterr().out


def test_cache_command_no_browser_never_starts_one(tmp_path, monkeypatch):
    from posting_triage.liveness import PostingText

    candidates = tmp_path / "candidates.csv"
    candidates.write_text("id,url,company,title\nbbb,https://acme.example/job/2,Acme,MLE\n")
    monkeypatch.setattr("posting_triage.cli.Browser", lambda: pytest.fail("browser started"))
    monkeypatch.setattr(
        "posting_triage.cli.fetch_posting",
        lambda url, browser: PostingText("unreadable", "browser", detail="browser not started"),
    )
    args = ["cache", "--candidates", str(candidates), "--cache-dir", str(tmp_path / "c"),
            "--delay", "0", "--no-browser"]
    assert main(args) == 0


class FakeBrowser:
    closed = False

    def __enter__(self):
        FakeBrowser.closed = False
        return self

    def __exit__(self, *exc):
        FakeBrowser.closed = True


def test_label_command_passes_paths_through(tmp_path, monkeypatch):
    candidates = tmp_path / "candidates.csv"
    candidates.write_text("id,url,company,title\naaa,https://x/1,Acme,SWE\n")
    seen = {}

    def fake_session(rows, io, labels, skips, cache_dir):
        seen.update(rows=rows, labels=labels, skips=skips, cache_dir=cache_dir)
        return 0

    monkeypatch.setattr("posting_triage.cli.run_session", fake_session)
    args = ["label", "--candidates", str(candidates), "--labels", "L.csv", "--skips", "S.csv", "--cache-dir", "C"]
    assert main(args) == 0
    assert [r["id"] for r in seen["rows"]] == ["aaa"]
    assert (seen["labels"], seen["skips"], seen["cache_dir"]) == ("L.csv", "S.csv", "C")
