"""Stage 1: is the posting live? Greenhouse, Lever, and Ashby go through their public
job-board APIs; anything else opens in headless Chromium (Playwright).

API docs (checked Oct 2026):
  Greenhouse  https://developers.greenhouse.io/job-board.html
  Lever       https://github.com/lever/postings-api
  Ashby       https://developers.ashbyhq.com/docs/public-job-posting-api
"""

import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class BoardJob:
    """A posting that one of the board APIs can look up."""

    board: str  # greenhouse | lever | ashby
    token: str  # the company's board name in that system
    job_id: str
    eu: bool = False  # Lever runs a separate EU instance


def board_job(url):
    """Return the BoardJob for a Greenhouse, Lever, or Ashby posting URL, else None.

    Company-hosted pages that only carry ?gh_jid= are not matched: the board token
    isn't in the URL, so those go to the browser instead.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    path = [p for p in parts.path.split("/") if p]

    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"):
        # /{board}/jobs/{id}
        if len(path) >= 3 and path[1] == "jobs" and path[2].isdigit():
            return BoardJob("greenhouse", path[0], path[2])
        # /embed/job_app?for={board}&token={id}
        query = parse_qs(parts.query)
        if path[:2] == ["embed", "job_app"] and "for" in query and "token" in query:
            return BoardJob("greenhouse", query["for"][0], query["token"][0])

    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        # /{site}/{posting-id}[/apply]
        if len(path) >= 2 and is_uuid(path[1]):
            return BoardJob("lever", path[0], path[1], eu=host == "jobs.eu.lever.co")

    if host == "jobs.ashbyhq.com":
        # /{board}/{job-id}[/application]
        if len(path) >= 2 and is_uuid(path[1]):
            return BoardJob("ashby", path[0], path[1])

    return None


def careers_page(url):
    """Where to send someone when a posting is DEAD: the company's job board for Greenhouse,
    Lever, and Ashby links, else the site's front page. The posting's own host is kept, so
    EU boards and older Greenhouse hosts stay on the instance the company uses."""
    parts = urlsplit(url)
    job = board_job(url)
    path = f"/{job.token}" if job else "/"
    return f"{parts.scheme}://{parts.netloc.lower()}{path}"


UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def is_uuid(text):
    return bool(UUID.match(text))


BLOCK_TAGS = {
    "p", "div", "br", "ul", "ol", "li", "tr", "table", "section", "article",
    "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
}
SKIP_TAGS = {"script", "style", "noscript"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)  # &amp; -> &, &nbsp; -> \xa0
        self.parts = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skipping += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skipping = max(0, self.skipping - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_to_text(markup):
    """Plain text from posting HTML: one line per block, bullets kept as "- ",
    runs of spaces collapsed, no blank lines."""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return tidy_text("".join(parser.parts))


def tidy_text(text):
    """Collapse spaces within each line and drop empty lines and empty bullets.
    Shared by the API and browser paths so every cached posting has the same shape."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line not in ("", "-"))


@dataclass(frozen=True)
class PostingText:
    """What one fetch found. Deciding DEAD vs FLAG from this is Phase 4's job."""

    status: str  # ok | not_found | unreadable
    source: str  # greenhouse | lever | ashby | browser
    text: str = ""
    detail: str = ""  # e.g. "HTTP 404", "not on board"


BOARD_GONE = "board HTTP 404"


def get_json(url, timeout=20):
    """GET a JSON API. Returns (HTTP status, parsed body or None); status 0 = no response."""
    request = urllib.request.Request(url, headers={"User-Agent": "posting-triage"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return 0, None


def fetch_from_board(job, get=get_json):
    """Fetch one posting's text from its board API. `get` is swappable for tests."""
    fetchers = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}
    return fetchers[job.board](job, get)


def _greenhouse(job, get):
    status, data = get(f"https://boards-api.greenhouse.io/v1/boards/{job.token}/jobs/{job.job_id}")
    if status == 404:
        return PostingText("not_found", "greenhouse", detail="HTTP 404")
    if status != 200 or not data:
        return PostingText("unreadable", "greenhouse", detail=f"HTTP {status}")
    # `content` is HTML with its tags entity-escaped (&lt;p&gt;), so unescape once first.
    body = html_to_text(html.unescape(data.get("content") or ""))
    location = (data.get("location") or {}).get("name", "")
    return PostingText("ok", "greenhouse", join_lines(data.get("title"), location, body))


def _lever(job, get):
    status, data = get(f"https://{lever_host(job)}/v0/postings/{job.token}/{job.job_id}")
    if status == 404:
        return PostingText("not_found", "lever", detail="HTTP 404")
    if status != 200 or not data:
        return PostingText("unreadable", "lever", detail=f"HTTP {status}")
    categories = data.get("categories") or {}
    locations = categories.get("allLocations") or [categories.get("location", "")]
    lists = [
        join_lines(item.get("text"), html_to_text(item.get("content") or ""))
        for item in data.get("lists") or []
    ]
    return PostingText(
        "ok",
        "lever",
        join_lines(
            data.get("text"),
            "; ".join(loc for loc in locations if loc),
            html_to_text(data.get("description") or ""),
            *lists,
            html_to_text(data.get("additional") or ""),
        ),
    )


def _ashby(job, get):
    # Ashby has no single-job endpoint: fetch the whole board and find the job in it.
    status, data = get(f"https://api.ashbyhq.com/posting-api/job-board/{job.token}")
    if status == 404:
        return PostingText("not_found", "ashby", detail=BOARD_GONE)
    if status != 200 or not data:
        return PostingText("unreadable", "ashby", detail=f"HTTP {status}")
    match = next(
        (j for j in data.get("jobs") or [] if job.job_id in (j.get("jobUrl") or "")),
        None,
    )
    if match is None:
        return PostingText("not_found", "ashby", detail="not on board")
    secondary = [s.get("location", "") for s in match.get("secondaryLocations") or []]
    return PostingText(
        "ok",
        "ashby",
        join_lines(
            match.get("title"),
            "; ".join(loc for loc in [match.get("location", ""), *secondary] if loc),
            html_to_text(match.get("descriptionHtml") or "") or match.get("descriptionPlain", ""),
        ),
    )


def join_lines(*parts):
    return "\n".join(p.strip() for p in parts if p and p.strip())


class Browser:
    """Headless Chromium for pages the board APIs can't reach (Workday, company sites, ...).

    It only loads pages and reads their text: it never clicks, signs in, or submits anything.
    Use as a context manager so one browser serves many postings:

        with Browser() as browser:
            result = browser.fetch(url)
    """

    def __init__(self, timeout_ms=30_000, settle_ms=10_000):
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms

    def __enter__(self):
        from playwright.sync_api import sync_playwright  # imported here so API-only runs don't need it

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._playwright.stop()

    def fetch(self, url):
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        page = self._browser.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            status = response.status if response else 0
            if status in (404, 410):
                return PostingText("not_found", "browser", detail=f"HTTP {status}")
            try:
                # JS-rendered boards (Workday) fill the page after load; give them time to settle.
                page.wait_for_load_state("networkidle", timeout=self.settle_ms)
            except PlaywrightTimeout:
                pass  # some pages never go idle; read whatever has rendered
            text = tidy_text("\n".join(frame_texts(page, PlaywrightError)))
            if status >= 400:
                return PostingText("unreadable", "browser", text, detail=f"HTTP {status}")
            return PostingText("ok", "browser", text)
        except PlaywrightError as e:
            return PostingText("unreadable", "browser", detail=str(e).splitlines()[0][:200])
        finally:
            page.close()


def frame_texts(page, error_type, frame_timeout_ms=5_000):
    """Text of the page and of every iframe in it. Some boards (iCIMS) put the
    whole job description inside an iframe, which the page's own text leaves out."""
    texts = [page.inner_text("body")]
    for frame in page.frames:
        if frame is page.main_frame:
            continue
        try:
            texts.append(frame.inner_text("body", timeout=frame_timeout_ms))
        except error_type:
            pass  # frame without a body, or gone before we read it
    return texts


def fetch_posting(url, browser=None, get=get_json):
    """Board API if the URL has one; otherwise the browser; otherwise unreadable."""
    job = board_job(url)
    if job:
        return fetch_from_board(job, get)
    if browser is None:
        return PostingText("unreadable", "browser", detail="no board API; browser not started")
    return browser.fetch(url)


def live_careers_page(url, posting, get=get_json):
    """careers_page(url) for a DEAD posting, or None when the company's whole board is gone
    too (it moved to another system, say), so we never link a dead board. Only board links
    are checked; others get the front page unchecked. Only a 404 counts as gone: a board
    that won't answer keeps its link."""
    job = board_job(url)
    if job is None:
        return careers_page(url)
    if job.board == "ashby":
        gone = posting.detail == BOARD_GONE  # the Ashby fetch already downloaded the board
    else:
        status, _ = get(board_api(job))
        gone = status == 404
    return None if gone else careers_page(url)


def board_api(job):
    """The API URL for a company's whole board (Greenhouse, Lever)."""
    if job.board == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{job.token}"
    return f"https://{lever_host(job)}/v0/postings/{job.token}?limit=1"


def lever_host(job):
    return "api.eu.lever.co" if job.eu else "api.lever.co"

