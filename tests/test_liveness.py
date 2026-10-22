import pytest

from posting_triage.liveness import BoardJob, PostingText, board_job, fetch_from_board, html_to_text

UUID = "3d182b7f-482e-45b2-8668-f04f0b5fda8e"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://boards.greenhouse.io/figma/jobs/6219995004?gh_jid=6219995004",
         BoardJob("greenhouse", "figma", "6219995004")),
        ("https://job-boards.greenhouse.io/doordashusa/jobs/8263774",
         BoardJob("greenhouse", "doordashusa", "8263774")),
        ("https://job-boards.eu.greenhouse.io/acme/jobs/123",
         BoardJob("greenhouse", "acme", "123")),
        ("https://boards.greenhouse.io/embed/job_app?for=acme&token=456",
         BoardJob("greenhouse", "acme", "456")),
        (f"https://jobs.lever.co/kobie/{UUID}", BoardJob("lever", "kobie", UUID)),
        (f"https://jobs.lever.co/kobie/{UUID}/apply", BoardJob("lever", "kobie", UUID)),
        (f"https://jobs.eu.lever.co/acme/{UUID}", BoardJob("lever", "acme", UUID, eu=True)),
        (f"https://jobs.ashbyhq.com/spruceid/{UUID}", BoardJob("ashby", "spruceid", UUID)),
        (f"https://jobs.ashbyhq.com/crusoe/{UUID}/application?embed=true",
         BoardJob("ashby", "crusoe", UUID)),
    ],
)
def test_board_urls_are_recognized(url, expected):
    assert board_job(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://careers.withwaymo.com/jobs?gh_jid=8202025",  # board token not in URL
        "https://boards.greenhouse.io/figma",  # board page, not a job
        "https://jobs.lever.co/kobie",
        "https://jobs.ashbyhq.com/spruceid",
        "https://jobs.ashbyhq.com/spruceid/not-a-uuid",
        "https://netflix.wd108.myworkdayjobs.com/en-US/netflix/job/Los-Gatos/SWE-Intern_JR42989",
        "https://lifeattiktok.com/search/7512345",
    ],
)
def test_other_urls_go_to_the_browser(url):
    assert board_job(url) is None


def test_every_board_url_in_candidates_parses():
    """Guard against URL shapes the real lists use that the parser misses."""
    import csv
    from pathlib import Path

    path = Path(__file__).parent.parent / "data" / "candidates.csv"
    with path.open() as f:
        urls = [row["url"] for row in csv.DictReader(f)]
    board_hosted = [
        u for u in urls
        if any(h in u for h in ("://boards.greenhouse.io/", "://job-boards.", "://jobs.lever.co/", "://jobs.ashbyhq.com/"))
    ]
    assert board_hosted, "expected some board-hosted URLs in the sample"
    assert [u for u in board_hosted if board_job(u) is None] == []


def test_html_to_text_keeps_structure():
    markup = (
        "<h2>About the role</h2><p>Build things&nbsp;at   scale.</p>"
        "<ul><li>BS in CS</li><li>2+ years <strong>preferred</strong></li></ul>"
        "<p>Pay &amp; benefits</p>"
    )
    assert html_to_text(markup) == (
        "About the role\nBuild things at scale.\n- BS in CS\n- 2+ years preferred\nPay & benefits"
    )


def test_html_to_text_drops_scripts_and_styles():
    markup = "<style>p{color:red}</style><p>Visible</p><script>var x = '<p>no</p>';</script>"
    assert html_to_text(markup) == "Visible"


def test_html_to_text_handles_br_and_plain_text():
    assert html_to_text("Line one<br>Line two<br/>Line three") == "Line one\nLine two\nLine three"
    assert html_to_text("no tags at all") == "no tags at all"
    assert html_to_text("") == ""


def fake_get(responses):
    """Stand-in for get_json: maps URL -> (status, body) and records calls."""
    calls = []

    def get(url):
        calls.append(url)
        return responses.get(url, (404, None))

    get.calls = calls
    return get


GH_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123"


def test_greenhouse_unescapes_content():
    get = fake_get({GH_URL: (200, {
        "title": "Software Engineer, New Grad",
        "location": {"name": "San Francisco, CA"},
        "content": "&lt;p&gt;Build &amp;amp; ship.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;BS in CS&lt;/li&gt;&lt;/ul&gt;",
    })})
    result = fetch_from_board(BoardJob("greenhouse", "acme", "123"), get)
    assert result == PostingText(
        "ok", "greenhouse", "Software Engineer, New Grad\nSan Francisco, CA\nBuild & ship.\n- BS in CS"
    )
    assert get.calls == [GH_URL]


def test_lever_includes_lists_and_eu_host():
    url = f"https://api.eu.lever.co/v0/postings/acme/{UUID}"
    get = fake_get({url: (200, {
        "text": "Backend Engineer I",
        "categories": {"location": "Remote", "allLocations": ["Remote", "Austin, TX"]},
        "description": "<div>We build tools.</div>",
        "lists": [{"text": "Requirements", "content": "<li>2+ years preferred</li>"}],
        "additional": "<p>Equal opportunity.</p>",
    })})
    result = fetch_from_board(BoardJob("lever", "acme", UUID, eu=True), get)
    assert result.status == "ok"
    assert result.text == (
        "Backend Engineer I\nRemote; Austin, TX\nWe build tools.\n"
        "Requirements\n- 2+ years preferred\nEqual opportunity."
    )


def test_ashby_finds_the_job_on_the_board():
    url = "https://api.ashbyhq.com/posting-api/job-board/zeta"
    get = fake_get({url: (200, {"jobs": [
        {"title": "Other job", "jobUrl": "https://jobs.ashbyhq.com/zeta/aaaa"},
        {
            "title": "ML Engineer",
            "location": "New York, NY",
            "secondaryLocations": [{"location": "Remote"}],
            "descriptionHtml": "<p>PhD preferred.</p>",
            "jobUrl": f"https://jobs.ashbyhq.com/zeta/{UUID}",
        },
    ]})})
    result = fetch_from_board(BoardJob("ashby", "zeta", UUID), get)
    assert result == PostingText("ok", "ashby", "ML Engineer\nNew York, NY; Remote\nPhD preferred.")


def test_ashby_job_missing_from_board_is_not_found():
    url = "https://api.ashbyhq.com/posting-api/job-board/zeta"
    get = fake_get({url: (200, {"jobs": [{"title": "Other", "jobUrl": "https://jobs.ashbyhq.com/zeta/aaaa"}]})})
    assert fetch_from_board(BoardJob("ashby", "zeta", UUID), get) == PostingText(
        "not_found", "ashby", detail="not on board"
    )


@pytest.mark.parametrize(
    "job",
    [BoardJob("greenhouse", "acme", "123"), BoardJob("lever", "acme", UUID), BoardJob("ashby", "acme", UUID)],
)
def test_404_is_not_found(job):
    assert fetch_from_board(job, fake_get({})).status == "not_found"


@pytest.mark.parametrize("status", [0, 500, 429])
def test_other_failures_are_unreadable_not_dead(status):
    # A server error or no network says nothing about whether the posting is live.
    get = lambda url: (status, None)  # noqa: E731
    result = fetch_from_board(BoardJob("greenhouse", "acme", "123"), get)
    assert result == PostingText("unreadable", "greenhouse", detail=f"HTTP {status}")


@pytest.mark.network
def test_real_greenhouse_404():
    result = fetch_from_board(BoardJob("greenhouse", "not-a-real-board-xyz", "1"))
    assert result.status == "not_found"
