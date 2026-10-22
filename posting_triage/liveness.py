"""Stage 1: is the posting live? Greenhouse, Lever, and Ashby go through their public
job-board APIs; anything else opens in headless Chromium (Playwright).

API docs (checked Oct 2026):
  Greenhouse  https://developers.greenhouse.io/job-board.html
  Lever       https://github.com/lever/postings-api
  Ashby       https://developers.ashbyhq.com/docs/public-job-posting-api
"""

import re
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
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line not in ("", "-"))
