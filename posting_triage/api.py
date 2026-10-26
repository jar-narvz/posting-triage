"""REST API: a thin layer over triage() (decision 7). It checks who's asking and what
they asked for (decisions 8 and 9), then calls the same function the CLI calls and
returns the same TriageResponse. No verdict logic lives here.

    GET  /health  -> {"status": "ok", "version": ...}             no auth
    POST /triage  {"url": ..., "model": optional}  -> TriageResponse
                  401 no or wrong token · 429 rate limited · 400 bad or non-public URL
                  504 timed out · 502 the Anthropic call failed

Settings come from the environment (see .env.example). On AWS, TRIAGE_SSM_PREFIX names
where the token, the Anthropic key, and the profile are kept in Parameter Store instead.
The app refuses to start without a token, an Anthropic key, or a readable profile.
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

from posting_triage.liveness import Browser, may_need_browser
from posting_triage.parameters import read_parameters
from posting_triage.profile import load_profile, profile_from_yaml
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
    profile: str = "profile.yaml"  # a path, unless profile_yaml is set
    api_key: str | None = None  # None: the Anthropic SDK reads ANTHROPIC_API_KEY itself
    profile_yaml: str | None = None  # the profile itself, as kept in Parameter Store
    docs: bool = True  # /docs, /redoc, /openapi.json; off on AWS, where only its owner calls it


def settings_from_env(env=os.environ, read_parameters=read_parameters):
    """Settings, or RuntimeError naming what's missing: the app fails closed. With
    TRIAGE_SSM_PREFIX set, the token, key, and profile come only from Parameter Store."""
    prefix = env.get("TRIAGE_SSM_PREFIX", "").strip()
    if prefix:
        stored = read_parameters(prefix)
        token = stored["api-token"].strip()
        api_key = stored["anthropic-api-key"].strip()
        profile_yaml = stored["profile"]
    else:
        token, api_key, profile_yaml = env.get("TRIAGE_API_TOKEN", "").strip(), None, None
        if not env.get("ANTHROPIC_API_KEY", "").strip():
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
    if not token:
        raise RuntimeError("TRIAGE_API_TOKEN is not set: the API won't start without a token")
    if api_key == "":
        raise RuntimeError("the stored anthropic-api-key is empty")
    docs = env.get("TRIAGE_DOCS", "on").strip().lower()
    if docs not in ("on", "off"):
        raise RuntimeError(f"TRIAGE_DOCS must be on or off, not {docs!r}")
    try:
        return Settings(
            token=token,
            rate_limit=int(env.get("TRIAGE_RATE_LIMIT", "10")),
            timeout_s=float(env.get("TRIAGE_TIMEOUT_S", "90")),
            profile=env.get("TRIAGE_PROFILE", "profile.yaml"),
            api_key=api_key,
            profile_yaml=profile_yaml,
            docs=docs == "on",
        )
    except ValueError as e:
        raise RuntimeError(f"TRIAGE_RATE_LIMIT and TRIAGE_TIMEOUT_S must be numbers: {e}") from None


def pipeline_runner(profile, api_key=None):
    """run(url, model) -> Triage, the real thing: Claude, plus a browser for links no board
    API covers or whose API may refuse (Workday). Chromium starts only if a page is fetched.
    Each call gets its own browser (sync Playwright can't be shared across threads)."""
    client = anthropic.Anthropic(api_key=api_key, timeout=CLIENT_TIMEOUT_S, max_retries=CLIENT_RETRIES)

    def run(url, model):
        with contextlib.ExitStack() as stack:
            browser = stack.enter_context(Browser()) if may_need_browser(url) else None
            return triage(url, profile, client.messages.create, model, browser, effort=EFFORT)

    return run


class TriageRequest(BaseModel):
    url: str
    model: str | None = None


def create_app(settings=None, run=None, check_url=public_url, clock=time.monotonic):
    """The FastAPI app. `run(url, model) -> Triage` and `check_url` are swappable so tests
    never call Claude, open a browser, or look up DNS; by default it's pipeline_runner."""
    settings = settings or settings_from_env()
    if run is None:  # a ProfileError stops startup
        if settings.profile_yaml is not None:
            profile = profile_from_yaml(settings.profile_yaml, source="the stored profile")
        else:
            profile = load_profile(settings.profile)
        run = pipeline_runner(profile, settings.api_key)
    limiter = RateLimiter(settings.rate_limit, clock=clock)
    slots = asyncio.Semaphore(MAX_CONCURRENT)
    version = importlib.metadata.version("posting-triage")
    # With docs off, the public URL answers only /health and /triage: nothing to explore.
    docs = {} if settings.docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Posting Triage", version=version, **docs)

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
