"""The API with FastAPI's TestClient. A fake `run` stands in for the pipeline and a fake
URL check for DNS, so nothing here calls Claude, opens a browser, or uses the network."""

import threading
from pathlib import Path

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from posting_triage.api import MAX_CONCURRENT, Settings, create_app, settings_from_env
from posting_triage.profile import ProfileError
from posting_triage.run_eval import MODELS
from posting_triage.triage import DEFAULT_MODEL, Triage, TriageResponse
from posting_triage.urlguard import BlockedURL, public_url

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = "https://job-boards.greenhouse.io/acme/jobs/1"
EXAMPLE_PROFILE = str(Path(__file__).parent.parent / "profile.example.yaml")


def accept(url):
    return url


@pytest.fixture
def client_for():
    """client_for(...) -> (TestClient, calls). Each client is entered, so one event loop
    serves every request, as under uvicorn. Without that, TestClient starts a loop per
    request and closing it waits for the worker thread, which hides the timeout behavior."""
    clients = []

    def make(run=None, check_url=accept, **settings):
        calls = []

        def default_run(url, model):
            calls.append((url, model))
            return Triage(url, "skip", "degree", "PhD required")

        client = TestClient(create_app(Settings(token=TOKEN, **settings), run or default_run, check_url))
        clients.append(client.__enter__())
        return client, calls

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def test_health_needs_no_token(client_for):
    client, _ = client_for()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok" and response.json()["version"]


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_are_served_unless_turned_off(client_for, path):
    on, _ = client_for()
    off, _ = client_for(docs=False)
    assert on.get(path).status_code == 200
    assert off.get(path).status_code == 404
    assert off.get("/health").status_code == 200  # still up for warm-ups


@pytest.mark.parametrize("value, expected", [(None, True), ("on", True), ("off", False), (" OFF ", False)])
def test_triage_docs_setting(value, expected):
    env = {"TRIAGE_API_TOKEN": "t", "ANTHROPIC_API_KEY": "k"}
    if value is not None:
        env["TRIAGE_DOCS"] = value
    assert settings_from_env(env).docs is expected


def test_an_unclear_docs_setting_stops_startup():
    # A typo shouldn't quietly leave the docs public on AWS.
    with pytest.raises(RuntimeError, match="TRIAGE_DOCS"):
        settings_from_env({"TRIAGE_API_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "TRIAGE_DOCS": "no"})


def test_a_triage_returns_the_shared_schema_with_the_default_model(client_for):
    client, calls = client_for()
    response = client.post("/triage", json={"url": URL}, headers=AUTH)
    assert response.status_code == 200
    body = TriageResponse.model_validate(response.json())
    assert (body.url, body.verdict, body.deciding_field, body.quote) == (URL, "skip", "degree", "PhD required")
    assert body.model == DEFAULT_MODEL and body.latency_ms >= 0
    assert calls == [(URL, DEFAULT_MODEL)]


def test_another_model_can_be_asked_for(client_for):
    client, calls = client_for()
    client.post("/triage", json={"url": URL, "model": MODELS[2]}, headers=AUTH)
    assert calls == [(URL, MODELS[2])]


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong-token"},
    {"Authorization": f"Basic {TOKEN}"},
    {"Authorization": "Bearer "},
    {"Authorization": TOKEN},
])
def test_a_missing_or_wrong_token_is_401_and_nothing_runs(client_for, headers):
    client, calls = client_for()
    response = client.post("/triage", json={"url": URL}, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "detail" in response.json()
    assert calls == []


def test_the_rate_limit_is_429_with_retry_after(client_for):
    client, calls = client_for(rate_limit=2)
    statuses = [client.post("/triage", json={"url": URL}, headers=AUTH).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    response = client.post("/triage", json={"url": URL}, headers=AUTH)
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert len(calls) == 2


def test_wrong_tokens_do_not_use_up_the_rate_limit(client_for):
    client, _ = client_for(rate_limit=1)
    for _ in range(5):
        client.post("/triage", json={"url": URL}, headers={"Authorization": "Bearer guess"})
    assert client.post("/triage", json={"url": URL}, headers=AUTH).status_code == 200


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost/", "ftp://example.com/x",
                                 "https://example.com:8080/", "not a url"])
def test_blocked_urls_are_400_with_the_reason(client_for, url):
    client, calls = client_for(check_url=public_url)  # the real check; these never need DNS
    response = client.post("/triage", json={"url": url}, headers=AUTH)
    assert response.status_code == 400
    assert response.json()["detail"]
    assert calls == []


def test_the_url_check_runs_on_the_submitted_url(client_for):
    seen = []

    def check(url):
        seen.append(url)
        raise BlockedURL("resolves to a non-public address (169.254.169.254)")

    client, _ = client_for(check_url=check)
    response = client.post("/triage", json={"url": URL}, headers=AUTH)
    assert (response.status_code, seen) == (400, [URL])
    assert "169.254.169.254" in response.json()["detail"]


def test_an_unknown_model_is_400(client_for):
    client, calls = client_for()
    response = client.post("/triage", json={"url": URL, "model": "gpt-9"}, headers=AUTH)
    assert response.status_code == 400 and calls == []


def test_a_slow_triage_is_504(client_for):
    release = threading.Event()
    client, _ = client_for(run=lambda url, model: release.wait(5), timeout_s=0.2)
    try:
        assert client.post("/triage", json={"url": URL}, headers=AUTH).status_code == 504
    finally:
        release.set()


def test_an_abandoned_triage_keeps_its_slot_until_it_really_finishes(client_for):
    # After timeouts, the stuck threads still run; a new request must wait, not start a third.
    release, started = threading.Event(), []

    def run(url, model):
        started.append(url)
        if len(started) <= MAX_CONCURRENT:
            release.wait(5)
        return Triage(url, "apply", "", None)

    client, _ = client_for(run=run, timeout_s=0.2)
    try:
        for _ in range(MAX_CONCURRENT):
            assert client.post("/triage", json={"url": URL}, headers=AUTH).status_code == 504
        assert client.post("/triage", json={"url": URL}, headers=AUTH).status_code == 504
        assert len(started) == MAX_CONCURRENT  # the third never started
    finally:
        release.set()
    for _ in range(50):  # the stuck threads finish and hand their slots back
        response = client.post("/triage", json={"url": URL}, headers=AUTH)
        if response.status_code == 200:
            break
    assert response.status_code == 200


def fail_with(error):
    def run(url, model):
        raise error
    return run


def test_an_anthropic_timeout_is_504(client_for):
    error = anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com"))
    client, _ = client_for(run=fail_with(error))
    assert client.post("/triage", json={"url": URL}, headers=AUTH).status_code == 504


def test_an_anthropic_error_is_502(client_for):
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    client, _ = client_for(run=fail_with(error))
    response = client.post("/triage", json={"url": URL}, headers=AUTH)
    assert response.status_code == 502
    assert "APIConnectionError" in response.json()["detail"]


@pytest.mark.parametrize("env, message", [
    ({"ANTHROPIC_API_KEY": "k"}, "TRIAGE_API_TOKEN"),
    ({"ANTHROPIC_API_KEY": "k", "TRIAGE_API_TOKEN": "  "}, "TRIAGE_API_TOKEN"),
    ({"TRIAGE_API_TOKEN": "t"}, "ANTHROPIC_API_KEY"),
    ({"TRIAGE_API_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "TRIAGE_RATE_LIMIT": "ten"}, "must be numbers"),
])
def test_the_app_refuses_to_start_without_its_settings(env, message):
    with pytest.raises(RuntimeError, match=message):
        settings_from_env(env)


def test_settings_from_env_reads_every_setting():
    env = {"TRIAGE_API_TOKEN": "t", "ANTHROPIC_API_KEY": "k", "TRIAGE_RATE_LIMIT": "5",
           "TRIAGE_TIMEOUT_S": "45", "TRIAGE_PROFILE": "/run/profile.yaml"}
    assert settings_from_env(env) == Settings("t", 5, 45.0, "/run/profile.yaml")


def stored(**values):
    """A read_parameters stand-in that returns these values for any prefix."""
    base = {"api-token": "t", "anthropic-api-key": "k", "profile": "degree: bachelors\n"}
    return lambda prefix: {**base, **values}


def test_with_a_parameter_store_prefix_the_secrets_and_profile_come_from_there():
    env = {"TRIAGE_SSM_PREFIX": "/posting-triage", "TRIAGE_TIMEOUT_S": "45",
           "TRIAGE_API_TOKEN": "ignored", "ANTHROPIC_API_KEY": "ignored"}
    assert settings_from_env(env, stored()) == Settings(
        "t", 10, 45.0, "profile.yaml", api_key="k", profile_yaml="degree: bachelors\n"
    )


def test_without_a_prefix_parameter_store_is_never_read():
    def never(prefix):
        raise AssertionError("Parameter Store should not be read")

    env = {"TRIAGE_API_TOKEN": "t", "ANTHROPIC_API_KEY": "k"}
    assert settings_from_env(env, never).api_key is None  # the SDK reads the env itself


@pytest.mark.parametrize("values, message", [
    ({"api-token": "  "}, "TRIAGE_API_TOKEN"),
    ({"anthropic-api-key": " "}, "anthropic-api-key"),
])
def test_blank_stored_secrets_stop_startup(values, message):
    with pytest.raises(RuntimeError, match=message):
        settings_from_env({"TRIAGE_SSM_PREFIX": "/posting-triage"}, stored(**values))


def test_the_stored_profile_and_key_reach_the_runner(monkeypatch):
    seen = {}
    monkeypatch.setattr("posting_triage.api.anthropic.Anthropic", lambda **kw: seen.update(kw))
    profile_yaml = open(EXAMPLE_PROFILE).read()
    create_app(Settings(token=TOKEN, profile="/no/such/file.yaml", api_key="sk-stored", profile_yaml=profile_yaml))
    assert seen["api_key"] == "sk-stored"  # and the missing file wasn't read: the stored profile was used


def test_a_bad_stored_profile_stops_startup():
    with pytest.raises(ProfileError, match="the stored profile"):
        create_app(Settings(token=TOKEN, profile_yaml="degree: [unclosed"))


def test_the_app_refuses_to_start_without_a_profile(tmp_path):
    with pytest.raises(ProfileError):
        create_app(Settings(token=TOKEN, profile=str(tmp_path / "missing.yaml")))


def test_the_real_runner_builds_from_the_profile(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = TestClient(create_app(Settings(token=TOKEN, profile=EXAMPLE_PROFILE)))
    assert client.get("/health").status_code == 200
