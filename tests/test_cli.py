import json
from pathlib import Path

import anthropic
import pytest

from posting_triage.cli import DEFAULT_MODEL, format_triage, main
from posting_triage.triage import Triage, TriageResponse

EXAMPLE_PROFILE = str(Path(__file__).parent.parent / "profile.example.yaml")
BOARD_URL = "https://job-boards.greenhouse.io/acme/jobs/1"
BROWSER_URL = "https://lifeattiktok.com/search/2"  # no board API: needs the browser


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
    assert main(["run", BOARD_URL, BROWSER_URL, "--profile", EXAMPLE_PROFILE]) == 0
    assert [(url, model, effort) for url, model, _, effort in run_env] == [
        (BOARD_URL, DEFAULT_MODEL, "medium"), (BROWSER_URL, DEFAULT_MODEL, "medium")]
    assert run_env[0][2] is None  # no browser for a board-API link
    assert isinstance(run_env[1][2], FakeBrowser)
    assert FakeBrowser.closed
    assert capsys.readouterr().out == f"APPLY  {BOARD_URL}\nAPPLY  {BROWSER_URL}\n"


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
    assert main(["run", BOARD_URL, BROWSER_URL, "--profile", EXAMPLE_PROFILE]) == 1
    out = capsys.readouterr().out
    assert f"ERROR  {BOARD_URL}\n       FakeAPIError: connection reset" in out
    assert f'SKIP   {BROWSER_URL}\n       degree: "PhD required"' in out


def test_run_json_prints_one_response_per_url(run_env, capsys):
    assert main(["run", BOARD_URL, BROWSER_URL, "--profile", EXAMPLE_PROFILE, "--json"]) == 0
    lines = capsys.readouterr().out.splitlines()
    responses = [TriageResponse.model_validate(json.loads(line)) for line in lines]
    assert [(r.url, r.verdict, r.model) for r in responses] == [
        (BOARD_URL, "apply", DEFAULT_MODEL), (BROWSER_URL, "apply", DEFAULT_MODEL)]
    assert all(r.latency_ms >= 0 for r in responses)


def test_run_json_sends_errors_to_stderr(run_env, monkeypatch, capsys):
    def flaky(url, profile, call, model, browser, effort):
        if url == BOARD_URL:
            raise FakeAPIError("connection reset")
        return Triage(url, "skip", "degree", "PhD required")

    monkeypatch.setattr("posting_triage.cli.triage", flaky)
    assert main(["run", BOARD_URL, BROWSER_URL, "--profile", EXAMPLE_PROFILE, "--json"]) == 1
    captured = capsys.readouterr()
    assert f"ERROR  {BOARD_URL}" in captured.err
    assert [json.loads(line)["url"] for line in captured.out.splitlines()] == [BROWSER_URL]


@pytest.fixture
def serve_env(monkeypatch):
    """API settings in the environment, no .env read, and uvicorn.run recorded instead of run."""
    import uvicorn

    monkeypatch.setattr("posting_triage.cli.load_env", lambda: None)
    for name, value in {"TRIAGE_API_TOKEN": "t", "ANTHROPIC_API_KEY": "test-key",
                        "TRIAGE_PROFILE": EXAMPLE_PROFILE}.items():
        monkeypatch.setenv(name, value)
    started = []
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: started.append((app, host, port)))
    return started


def test_serve_starts_the_api_on_localhost_by_default(serve_env):
    from fastapi import FastAPI

    assert main(["serve"]) == 0
    [(app, host, port)] = serve_env
    assert isinstance(app, FastAPI) and (host, port) == ("127.0.0.1", 8000)


def test_serve_takes_a_host_and_port(serve_env):
    assert main(["serve", "--host", "0.0.0.0", "--port", "8080"]) == 0
    assert serve_env[0][1:] == ("0.0.0.0", 8080)


@pytest.mark.parametrize("unset, set_to, reason", [
    ("TRIAGE_API_TOKEN", None, "TRIAGE_API_TOKEN"),
    ("TRIAGE_PROFILE", "/nowhere/profile.yaml", "not found"),
])
def test_serve_refuses_to_start_and_says_why(serve_env, monkeypatch, capsys, unset, set_to, reason):
    if set_to:
        monkeypatch.setenv(unset, set_to)
    else:
        monkeypatch.delenv(unset)
    assert main(["serve"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("Not starting the API:") and reason in out
    assert serve_env == []


def test_env_example_holds_working_api_defaults(monkeypatch):
    from posting_triage.api import Settings, settings_from_env
    from posting_triage.run_eval import load_env

    for name in ("ANTHROPIC_API_KEY", "TRIAGE_API_TOKEN", "TRIAGE_RATE_LIMIT", "TRIAGE_TIMEOUT_S", "TRIAGE_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    load_env(Path(__file__).parent.parent / ".env.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    with pytest.raises(RuntimeError, match="TRIAGE_API_TOKEN"):  # shipped empty, so it fails closed
        settings_from_env()
    monkeypatch.setenv("TRIAGE_API_TOKEN", "t")
    assert settings_from_env() == Settings("t", 10, 90.0, "profile.yaml")


def test_cache_command_fetches_every_candidate(tmp_path, monkeypatch, capsys):
    from posting_triage.liveness import PostingText

    candidates = tmp_path / "candidates.csv"
    candidates.write_text(
        "id,url,company,title,location,source,section,tags\n"
        "aaa,https://boards.greenhouse.io/acme/jobs/1,Acme,SWE,SF,s,x,\n"
        "bbb,https://lifeattiktok.com/search/2,Acme,MLE,SF,s,x,\n"
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
        "https://lifeattiktok.com/search/2",
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
