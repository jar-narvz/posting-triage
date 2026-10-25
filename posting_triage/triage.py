"""One posting URL in, one answer out: liveness, then extraction, then the rules.

This is the function the CLI and the API both call. It only wires the stages together;
every decision lives in liveness.py (is it live?) and rules.py (APPLY / FLAG / SKIP).
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from posting_triage.extract import pipeline_verdict
from posting_triage.liveness import fetch_posting, get_json, live_careers_page
from posting_triage.rules import FLAG

DEAD = "dead"
# The eval's pick (Oct 24 full run): the cheapest model within 5 points of the best apply precision.
DEFAULT_MODEL = "claude-haiku-5-5"


@dataclass(frozen=True)
class Triage:
    url: str
    verdict: str  # apply | flag | skip | dead
    field: str  # the deciding field; "liveness" for dead and couldn't-verify, "" for APPLY
    quote: str | None  # the posting's words behind it, when there are any
    careers_page: str | None = None  # only for DEAD: where to look for other roles; None if that's gone too
    detail: str = ""  # why liveness failed, e.g. "HTTP 403"


class TriageResponse(BaseModel):
    """The one answer schema `triage run --json` and the API both return (decision 7).
    `Triage` stays the internal result; this adds what a caller needs to know about the run."""

    url: str
    verdict: Literal["apply", "flag", "skip", "dead"]
    deciding_field: str  # "" for APPLY
    quote: str | None
    careers_page: str | None
    detail: str
    model: str
    latency_ms: int

    @classmethod
    def from_triage(cls, result, model, latency_ms):
        return cls(
            url=result.url,
            verdict=result.verdict,
            deciding_field=result.field,
            quote=result.quote,
            careers_page=result.careers_page,
            detail=result.detail,
            model=model,
            latency_ms=latency_ms,
        )


def triage(url, profile, call, model, browser=None, get=get_json, effort="medium"):
    """The tool's answer for one posting URL. `call`, `browser`, and `get` are passed in
    (client.messages.create, a started Browser, liveness.get_json) so tests can swap fakes."""
    posting = fetch_posting(url, browser, get)
    if posting.status == "not_found":
        page = live_careers_page(url, posting, get)
        detail = posting.detail if page else f"{posting.detail}; company board gone too"
        return Triage(url, DEAD, "liveness", None, page, detail)
    if posting.status != "ok" or not posting.text.strip():
        # Decision 5: a page we couldn't read is "couldn't verify", never DEAD.
        return Triage(url, FLAG, "liveness", None, detail=posting.detail or "no posting text")
    v = pipeline_verdict(posting.text, profile, call, model, effort)
    return Triage(url, v.verdict, v.field, v.quote)
