"""Stage 1: is the posting live? Greenhouse, Lever, and Ashby go through their public
job-board APIs; anything else opens in headless Chromium (Playwright).

API docs (checked Oct 2026):
  Greenhouse  https://developers.greenhouse.io/job-board.html
  Lever       https://github.com/lever/postings-api
  Ashby       https://developers.ashbyhq.com/docs/public-job-posting-api
"""

import re
from dataclasses import dataclass
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
