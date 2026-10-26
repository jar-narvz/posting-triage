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
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

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
ENV PORT=8080 \
    TRIAGE_PROFILE=/app/profile.yaml
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=4)"

# tini is process 1 and passes stop signals on; exec makes uvicorn its direct child.
# Any command given to `docker run` replaces CMD and still runs under tini.
ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "exec triage serve --host 0.0.0.0 --port \"$PORT\""]
