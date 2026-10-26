# One image for the API (the default command) and the CLI (decision 10):
#   docker run -p 8080:8080 --env-file .env -v "$PWD/profile.yaml:/app/profile.yaml:ro" posting-triage
#   docker run --rm --env-file .env -v "$PWD/profile.yaml:/app/profile.yaml:ro" posting-triage triage run <url>
# The base image has Chromium and its system libraries for this exact Playwright version
# (pinned in pyproject.toml), but not the playwright package itself.
FROM mcr.microsoft.com/playwright/python:v1.64.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# tini runs as process 1 and reaps orphaned processes. Chromium leaves helper processes
# behind when it closes; without an init they pile up as zombies (4 per browser, measured).
# Installed before the code is copied, so code changes don't re-run apt-get.
# It's what `docker run --init` uses, built in because App Runner can't pass --init.
# The same step upgrades the base image's packages (security fixes) and removes the media
# libraries (ffmpeg, gstreamer, fluidsynth, openexr) that Firefox and WebKit use for playback.
# Chromium's headless shell, the only browser the app starts, links none of them, and they
# held almost all of the image scan's critical and high findings. autoremove then drops the
# packages that only they needed.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends tini \
    && apt-get purge -y \
        gstreamer1.0-libav gstreamer1.0-plugins-bad gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good libgstreamer-plugins-bad1.0-0 \
        libavcodec60 libavfilter9 libavformat60 libavutil58 libpostproc57 \
        libswresample4 libswscale7 libx264-164 libx265-199 libopenh264-7 \
        libfluidsynth3 libopenexr-3-1-30 \
    && apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/*

# On AWS Lambda, the Lambda Web Adapter (a Lambda extension) turns each invocation into an
# HTTP request to this server, so the same image runs there unchanged (decision 10).
# Anywhere else the file just sits unused. v1.1.0, pinned by the digest of its multi-arch
# index, so each architecture gets its own build of that exact release.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0@sha256:17cfd08eff1dfea3f6a9a1e9c65fdac80aa4919b6085e746615530f43f57d2f1 \
    /lambda-adapter /opt/extensions/lambda-adapter

# Installed system-wide: this image's pip (in /usr/local) allows it, and the image runs one
# app, so a venv would add nothing (and would need the python3-venv package, which isn't here).
WORKDIR /app
COPY pyproject.toml README.md ./
COPY posting_triage ./posting_triage
# The aws extra (boto3) lets the API read its settings from Parameter Store on AWS.
RUN pip install --no-cache-dir ".[aws]"

# Not root: the image's own unprivileged user. If a page ever broke out of Chromium,
# it would land as pwuser, not root.
USER pwuser

# The profile is mounted at run time, never built in: it holds personal data.
# (On AWS it comes from Parameter Store instead; see TRIAGE_SSM_PREFIX.)
# The adapter forwards to PORT and waits for /health before Lambda sends any request.
ENV PORT=8080 \
    TRIAGE_PROFILE=/app/profile.yaml \
    AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/health
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=4)"

# tini is process 1 and passes stop signals on; exec makes uvicorn its direct child.
# Any command given to `docker run` replaces CMD and still runs under tini.
ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "exec triage serve --host 0.0.0.0 --port \"$PORT\""]
