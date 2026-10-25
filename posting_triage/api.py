"""REST API: a thin layer over triage() (decision 7). It checks who's asking and what
they asked for (decisions 8 and 9), then calls the same function the CLI calls and
returns the same TriageResponse. No verdict logic lives here.

    GET  /health  -> {"status": "ok", "version": ...}             no auth
    POST /triage  {"url": ..., "model": optional}  -> TriageResponse
                  401 no or wrong token · 429 rate limited · 400 bad or non-public URL
                  504 timed out · 502 the Anthropic call failed

Settings come from the environment (see .env.example). The app refuses to start
without TRIAGE_API_TOKEN, ANTHROPIC_API_KEY, or a readable profile.
"""

import asyncio
import contextlib
import hmac
import importlib.metadata
import os
import time
from dataclasses import dataclass

import anthropic
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from posting_triage.liveness import Browser, board_job
from posting_triage.profile import load_profile
from posting_triage.ratelimit import RateLimiter
from posting_triage.run_eval import EFFORT, MODELS
from posting_triage.triage import DEFAULT_MODEL, TriageResponse, triage
from posting_triage.urlguard import BlockedURL, public_url

MAX_CONCURRENT = 2  # triages running at once, each possibly with its own Chromium
CLIENT_TIMEOUT_S = 30  # per Anthropic call
CLIENT_RETRIES = 1  # for transient API errors; the pipeline's own retry is for bad output


@dataclass(frozen=True)
class Settings:
    token: str
    rate_limit: int = 10  # requests per minute per token
    timeout_s: float = 90
    profile: str = "profile.yaml"


def settings_from_env(env=os.environ):
    """Settings, or RuntimeError naming what's missing: the app fails closed."""
    token = env.get("TRIAGE_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TRIAGE_API_TOKEN is not set: the API won't start without a token")
    if not env.get("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    try:
        return Settings(
            token=token,
            rate_limit=int(env.get("TRIAGE_RATE_LIMIT", "10")),
            timeout_s=float(env.get("TRIAGE_TIMEOUT_S", "90")),
            profile=env.get("TRIAGE_PROFILE", "profile.yaml"),
        )
    except ValueError as e:
        raise RuntimeError(f"TRIAGE_RATE_LIMIT and TRIAGE_TIMEOUT_S must be numbers: {e}") from None


def pipeline_runner(profile):
    """run(url, model) -> Triage, the real thing: Claude, plus a browser only for links
    no board API covers. Each call gets its own browser (sync Playwright can't be
    shared across threads)."""
    client = anthropic.Anthropic(timeout=CLIENT_TIMEOUT_S, max_retries=CLIENT_RETRIES)

    def run(url, model):
        with contextlib.ExitStack() as stack:
            browser = None if board_job(url) else stack.enter_context(Browser())
            return triage(url, profile, client.messages.create, model, browser, effort=EFFORT)

    return run


class TriageRequest(BaseModel):
    url: str
    model: str | None = None


def create_app(settings=None, run=None, check_url=public_url, clock=time.monotonic):
    """The FastAPI app. `run(url, model) -> Triage` and `check_url` are swappable so tests
    never call Claude, open a browser, or look up DNS; by default it's pipeline_runner."""
    settings = settings or settings_from_env()
    if run is None:
        run = pipeline_runner(load_profile(settings.profile))  # a ProfileError stops startup
    limiter = RateLimiter(settings.rate_limit, clock=clock)
    slots = asyncio.Semaphore(MAX_CONCURRENT)
    version = importlib.metadata.version("posting-triage")
    app = FastAPI(title="Posting Triage", version=version)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": version}

    @app.post("/triage", response_model=TriageResponse)
    async def triage_posting(body: TriageRequest, authorization: str | None = Header(None)):
        token = bearer_token(authorization)
        if token is None or not hmac.compare_digest(token.encode(), settings.token.encode()):
            raise HTTPException(401, "missing or wrong bearer token", {"WWW-Authenticate": "Bearer"})
        # Counted only after the token check, so made-up tokens can't fill the limiter.
        wait = limiter.take(token)
        if wait:
            raise HTTPException(429, "rate limit reached; try again later",
                                {"Retry-After": str(max(1, round(wait)))})
        model = body.model or DEFAULT_MODEL
        if model not in MODELS:
            raise HTTPException(400, f"model must be one of: {', '.join(MODELS)}")
        try:
            await asyncio.to_thread(check_url, body.url)  # DNS lookups block, so off the event loop
        except BlockedURL as e:
            raise HTTPException(400, str(e)) from None

        start = time.perf_counter()
        try:
            async with asyncio.timeout(settings.timeout_s):  # covers waiting for a slot, too
                result = await run_in_slot(slots, run, body.url, model)
        except TimeoutError:
            raise HTTPException(504, f"triage took longer than {settings.timeout_s:g} s") from None
        except anthropic.APITimeoutError:
            raise HTTPException(504, "the Anthropic API timed out") from None
        except anthropic.APIError as e:
            raise HTTPException(502, f"the Anthropic API failed: {type(e).__name__}") from None
        latency_ms = round((time.perf_counter() - start) * 1000)
        return TriageResponse.from_triage(result, model, latency_ms)

    return app


async def run_in_slot(slots, run, url, model):
    """Run `run` in a worker thread once one of the slots is free. The slot is given back
    when the thread finishes, not when the caller stops waiting: Python can't stop a thread,
    so an abandoned triage keeps its slot and the cap stays real."""
    await slots.acquire()
    job = asyncio.get_running_loop().run_in_executor(None, run, url, model)

    def finished(f):
        slots.release()
        if not f.cancelled():
            f.exception()  # mark it retrieved, so an abandoned job's error isn't logged as unhandled

    job.add_done_callback(finished)
    return await asyncio.shield(job)


def bearer_token(header):
    scheme, _, token = (header or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
