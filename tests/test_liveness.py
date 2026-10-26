import pytest

from posting_triage.liveness import (
    CHROMIUM_ARGS,
    BoardJob,
    Browser,
    PostingText,
    board_job,
    careers_page,
    fetch_from_board,
    fetch_posting,
    html_to_text,
    live_careers_page,
    tidy_text,
)
from posting_triage.urlguard import BlockedURL

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


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://job-boards.greenhouse.io/doordashusa/jobs/8263774", "https://job-boards.greenhouse.io/doordashusa"),
        ("https://boards.greenhouse.io/embed/job_app?for=acme&token=456", "https://boards.greenhouse.io/acme"),
        ("https://job-boards.eu.greenhouse.io/acme/jobs/123", "https://job-boards.eu.greenhouse.io/acme"),
        (f"https://jobs.lever.co/kobie/{UUID}/apply", "https://jobs.lever.co/kobie"),
        (f"https://jobs.eu.lever.co/acme/{UUID}", "https://jobs.eu.lever.co/acme"),
        (f"https://jobs.ashbyhq.com/crusoe/{UUID}/application?embed=true", "https://jobs.ashbyhq.com/crusoe"),
        ("https://netflix.wd108.myworkdayjobs.com/en-US/netflix/job/Los-Gatos/SWE-Intern_JR42989",
         "https://netflix.wd108.myworkdayjobs.com/"),
        ("https://careers.withwaymo.com/jobs?gh_jid=8202025", "https://careers.withwaymo.com/"),
        ("https://Lifeattiktok.com/search/7512345", "https://lifeattiktok.com/"),
    ],
)
def test_careers_page_is_the_board_or_the_front_page(url, expected):
    assert careers_page(url) == expected


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
WORKDAY_URL = "https://acme.wd1.myworkdayjobs.com/en-US/ext/job/SWE_JR1"


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


def test_tidy_text_matches_html_to_text_shape():
    assert tidy_text("  Title \n\n\n   Body   text\n-\n- item ") == "Title\nBody text\n- item"



GONE = PostingText("not_found", "greenhouse", detail="HTTP 404")


@pytest.mark.parametrize("status, expected", [
    (200, "https://job-boards.greenhouse.io/acme"),
    (404, None),
    (0, "https://job-boards.greenhouse.io/acme"),  # no answer is not proof the board is gone
])
def test_dead_greenhouse_posting_links_its_board_only_if_the_board_is_there(status, expected):
    get = fake_get({"https://boards-api.greenhouse.io/v1/boards/acme": (status, None)})
    assert live_careers_page("https://job-boards.greenhouse.io/acme/jobs/123", GONE, get) == expected
    assert get.calls == ["https://boards-api.greenhouse.io/v1/boards/acme"]


def test_dead_lever_posting_checks_the_board_on_its_own_instance():
    get = fake_get({})
    assert live_careers_page(f"https://jobs.eu.lever.co/acme/{UUID}", GONE, get) is None
    assert get.calls == ["https://api.eu.lever.co/v0/postings/acme?limit=1"]


@pytest.mark.parametrize("detail, expected", [
    ("not on board", "https://jobs.ashbyhq.com/acme"),
    ("board HTTP 404", None),
])
def test_dead_ashby_posting_needs_no_second_request(detail, expected):
    get = fake_get({})
    posting = PostingText("not_found", "ashby", detail=detail)
    assert live_careers_page(f"https://jobs.ashbyhq.com/acme/{UUID}", posting, get) == expected
    assert get.calls == []


def test_dead_non_board_posting_gets_the_front_page_unchecked():
    get = fake_get({})
    posting = PostingText("not_found", "browser", detail="HTTP 404")
    assert live_careers_page(WORKDAY_URL, posting, get) == "https://acme.wd1.myworkdayjobs.com/"
    assert get.calls == []


class FakeBrowser:
    def __init__(self):
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return PostingText("ok", "browser", "rendered")


def test_fetch_posting_routes_board_urls_to_the_api():
    browser = FakeBrowser()
    get = fake_get({GH_URL: (200, {"title": "SWE", "content": ""})})
    result = fetch_posting("https://boards.greenhouse.io/acme/jobs/123", browser, get)
    assert result.source == "greenhouse"
    assert browser.urls == []


def test_fetch_posting_sends_other_urls_to_the_browser():
    browser = FakeBrowser()
    url = "https://acme.wd1.myworkdayjobs.com/en-US/ext/job/SWE_JR1"
    assert fetch_posting(url, browser, fake_get({})) == PostingText("ok", "browser", "rendered")
    assert browser.urls == [url]


def test_fetch_posting_without_a_browser_is_unreadable():
    result = fetch_posting("https://acme.example/jobs/1", None, fake_get({}))
    assert result.status == "unreadable"


def serve(pages):
    """A tiny local web server on 127.0.0.1: path -> (status, headers, body).
    Returns (base URL, list of paths it was asked for, server)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    asked = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            status, headers, body = pages.get(self.path, (500, {}, "error"))
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", asked, server


def allow_only(*bases):
    """A proxy check that allows only these local servers, the way the real one allows only
    public addresses. Anything else, other local ports included, is blocked."""
    ports = {int(base.rsplit(":", 1)[1]) for base in bases}

    def check(host, port):
        if host != "127.0.0.1" or port not in ports:
            raise BlockedURL("not allowed in this test")
        return ["127.0.0.1"]
    return check


@pytest.fixture
def local_site():
    """/job renders its text with JavaScript, /gone is a 404."""
    base, _, server = serve({
        "/job": (200, {}, "<body><div id=app></div><script>"
                          "document.getElementById('app').innerHTML = '<h1>SWE I</h1><p>BS   required</p>';"
                          "</script></body>"),
        "/gone": (404, {}, "<body>Not found</body>"),
        # iCIMS-style: the posting lives inside an iframe.
        "/framed": (200, {}, "<body><nav>Careers</nav><iframe src='/inner'></iframe></body>"),
        "/inner": (200, {}, "<body><p>Junior Engineer</p><p>2+ years required</p></body>"),
    })
    yield base
    server.shutdown()


@pytest.fixture
def internal_and_hostile():
    """`internal` stands in for 169.254.170.2; `hostile` is a public page that tries to reach
    it by a redirect, an iframe, an image, and a script's fetch()."""
    internal, internal_asked, internal_server = serve({"/": (200, {}, "<body>SECRET CREDENTIALS</body>")})
    hostile, _, hostile_server = serve({
        "/redirect": (302, {"Location": f"{internal}/"}, ""),
        "/embed": (200, {}, f"<body><p>Posting</p><iframe src='{internal}/'></iframe>"
                            f"<img src='{internal}/'><script>fetch('{internal}/').catch(() => {{}})</script></body>"),
    })
    yield hostile, internal, internal_asked
    hostile_server.shutdown()
    internal_server.shutdown()


@pytest.mark.browser
def test_browser_reads_javascript_rendered_text(local_site):
    with Browser(settle_ms=2_000, check=allow_only(local_site)) as browser:
        assert browser.fetch(f"{local_site}/job") == PostingText("ok", "browser", "SWE I\nBS required")
        assert browser.fetch(f"{local_site}/gone").status == "not_found"
        assert browser.fetch(f"{local_site}/broken").status == "unreadable"


@pytest.mark.browser
def test_browser_reads_text_inside_iframes(local_site):
    with Browser(settle_ms=2_000, check=allow_only(local_site)) as browser:
        result = browser.fetch(f"{local_site}/framed")
    assert result == PostingText("ok", "browser", "Careers\nJunior Engineer\n2+ years required")


@pytest.mark.browser
def test_a_redirect_to_a_blocked_address_is_never_followed(internal_and_hostile):
    hostile, internal, internal_asked = internal_and_hostile
    with Browser(settle_ms=1_000, check=allow_only(hostile)) as browser:
        result = browser.fetch(f"{hostile}/redirect")
    assert result.status == "unreadable" and "SECRET" not in result.text
    assert internal_asked == []
    assert [port for _, port, _ in browser.proxy.blocked] == [int(internal.rsplit(":", 1)[1])]


@pytest.mark.browser
def test_iframes_images_and_scripts_cannot_reach_a_blocked_address(internal_and_hostile):
    hostile, _, internal_asked = internal_and_hostile
    with Browser(settle_ms=1_000, check=allow_only(hostile)) as browser:
        result = browser.fetch(f"{hostile}/embed")
    assert result.status == "ok" and "Posting" in result.text and "SECRET" not in result.text
    assert internal_asked == []


@pytest.mark.browser
def test_the_redirect_is_followed_when_its_target_is_allowed(internal_and_hostile):
    # The control: without it, the blocking test could pass because redirects never ran at all.
    hostile, internal, _ = internal_and_hostile
    with Browser(settle_ms=1_000, check=allow_only(hostile, internal)) as browser:
        assert "SECRET" in browser.fetch(f"{hostile}/redirect").text


def test_chromium_runs_without_a_jit_and_without_udp():
    # The sandbox can't run in the container, so the JIT (a common exploit target) is off;
    # QUIC and WebRTC UDP would bypass the filtering proxy.
    assert "--js-flags=--jitless" in CHROMIUM_ARGS
    assert "--disable-quic" in CHROMIUM_ARGS
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in CHROMIUM_ARGS


@pytest.mark.browser
def test_the_launched_browser_has_no_jit():
    # V8 reports its flags to the page: with --jitless, WebAssembly (which needs the JIT) is gone.
    with Browser() as browser:
        browser._start()
        page = browser._browser.new_page()
        assert page.evaluate("typeof WebAssembly") == "undefined"
        page.close()


def test_browser_starts_chromium_only_when_a_page_is_fetched(monkeypatch):
    started = []
    monkeypatch.setattr(Browser, "_start", lambda self: started.append(self))
    with Browser():
        pass
    assert started == []  # entered and left without a fetch: nothing launched, nothing to close
