"""triage(url): liveness outcomes and the hand-off to the pipeline.
Fake `get`, browser, and `call` stand in for the board APIs, Chromium, and Claude."""

from pathlib import Path

from posting_triage.liveness import PostingText
from posting_triage.profile import load_profile
from posting_triage.synthetic import generate
from posting_triage.triage import DEAD, Triage, triage
from test_extract import perfect
from test_extract_requests import FakeClient, reply
from test_liveness import fake_get

PROFILE = load_profile(Path(__file__).parent.parent / "profile.example.yaml")
GH_POSTING = "https://job-boards.greenhouse.io/acme/jobs/123"
GH_API = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123"
GH_BOARD = "https://boards-api.greenhouse.io/v1/boards/acme"
WORKDAY = "https://acme.wd1.myworkdayjobs.com/en-US/ext/job/SWE_JR1"


class FakeBrowser:
    def __init__(self, result):
        self.result, self.urls = result, []

    def fetch(self, url):
        self.urls.append(url)
        return self.result


def never_called(**params):
    raise AssertionError("the LLM should not be called")


def test_dead_posting_returns_the_careers_page_without_calling_the_llm():
    get = fake_get({GH_BOARD: (200, {"name": "Acme"})})
    result = triage(GH_POSTING, PROFILE, never_called, "m", get=get)
    assert result == Triage(GH_POSTING, DEAD, "liveness", None,
                            "https://job-boards.greenhouse.io/acme", "HTTP 404")


def test_dead_posting_whose_board_is_gone_gets_no_careers_page():
    result = triage(GH_POSTING, PROFILE, never_called, "m", get=fake_get({}))
    assert result == Triage(GH_POSTING, DEAD, "liveness", None, None,
                            "HTTP 404; company board gone too")


def test_unreadable_page_is_flagged_never_dead():
    browser = FakeBrowser(PostingText("unreadable", "browser", detail="HTTP 403"))
    result = triage(WORKDAY, PROFILE, never_called, "m", browser=browser)
    assert (result.verdict, result.field, result.careers_page, result.detail) == ("flag", "liveness", None, "HTTP 403")


def test_no_browser_for_a_non_board_link_is_flagged():
    result = triage(WORKDAY, PROFILE, never_called, "m", get=fake_get({}))
    assert (result.verdict, result.field) == ("flag", "liveness")


def test_a_live_page_with_no_text_is_flagged_not_sent_to_the_llm():
    browser = FakeBrowser(PostingText("ok", "browser", "  \n "))
    result = triage(WORKDAY, PROFILE, never_called, "m", browser=browser)
    assert (result.verdict, result.field, result.detail) == ("flag", "liveness", "no posting text")


def test_live_posting_gets_the_pipeline_verdict():
    for posting in generate(n=20, seed=5):
        browser = FakeBrowser(PostingText("ok", "browser", posting["text"]))
        call = FakeClient(reply(perfect(posting).model_dump()))
        result = triage(WORKDAY, PROFILE, call, "m", browser=browser)
        assert (result.verdict, result.field) == (posting["gold_verdict"], posting["deciding_field"]), posting["id"]
        assert result.careers_page is None
        assert call.requests[0]["model"] == "m"


def test_board_text_is_what_the_llm_reads():
    posting = generate(n=1, seed=1)[0]
    get = fake_get({GH_API: (200, {"title": "", "content": posting["text"]})})
    call = FakeClient(reply(perfect(posting).model_dump()))
    browser = FakeBrowser(PostingText("ok", "browser", "should not be used"))
    triage(GH_POSTING, PROFILE, call, "m", browser=browser, get=get)
    assert browser.urls == []
    assert posting["text"].splitlines()[0] in call.requests[0]["messages"][0]["content"]
