# Deploying posting-triage

One Docker image runs both the REST API (its default command) and the CLI (design decision 10). This page covers building and running it locally, what it needs, what was measured, and how to keep it patched. The AWS deploy will be added here, with a teardown command for every resource.

## Build

```bash
docker build -t posting-triage .
```

The first build downloads the base image, `mcr.microsoft.com/playwright/python:v1.64.0-noble` (about 3.5 GB unpacked; it took 27 minutes on a home connection). Later builds reuse it.

## Run the API

```bash
docker run --rm -p 8080:8080 --env-file .env -v "$PWD/profile.yaml:/app/profile.yaml:ro" posting-triage
curl http://127.0.0.1:8080/health
```

`POST /triage` needs `Authorization: Bearer <TRIAGE_API_TOKEN>`. The API refuses to start without a token, a key, or a readable profile, and says which one is missing.

## Run the CLI

```bash
docker run --rm --env-file .env -v "$PWD/profile.yaml:/app/profile.yaml:ro" posting-triage triage run <posting-url>
```

Any command given to `docker run` replaces the default one, and still runs under `tini`.

## Settings

| Variable | Default | What it is |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `TRIAGE_API_TOKEN` | (required for the API) | The bearer token for `POST /triage` |
| `TRIAGE_RATE_LIMIT` | `10` | Requests per minute per token |
| `TRIAGE_TIMEOUT_S` | `90` | Seconds before `POST /triage` gives up with a 504 |
| `TRIAGE_PROFILE` | `/app/profile.yaml` | Path to the applicant's profile inside the container |
| `PORT` | `8080` | Port the API listens on inside the container |

Secrets and the profile are supplied when the container runs, never built in. `.dockerignore` is an allowlist (`pyproject.toml`, `README.md`, `posting_triage/`), so `.env`, `profile.yaml`, and `data/` can't be copied into the image.

## What's in the image, and why

- **Non-root.** It runs as `pwuser`, the base image's unprivileged user.
- **`tini` as process 1.** Chromium leaves helper processes behind when it closes. Without an init they pile up as zombies (measured: 4 per browser); with `tini`, none. It's what `docker run --init` uses, built in because not every platform can pass `--init`.
- **Chromium runs without its sandbox.** The sandbox needs a custom seccomp profile or extra privileges, which a default container doesn't have. Playwright's docs don't recommend this image for untrusted sites, and job postings are untrusted, so the other defenses matter:
  - every browser connection goes through a filtering proxy that allows only public addresses (no cloud metadata, no internal services)
  - V8's JIT compiler is off (`--js-flags=--jitless`), a common exploit target
  - non-root, as above
  - only the token holder can make the API fetch anything
  - the deployed API should use its own Anthropic key with a monthly spend limit, so a stolen key has a capped cost
- **One uvicorn worker.** The rate limit and the 2-at-a-time cap live in memory, so more workers would each keep their own.

## Measured (Oct 25, 2026, Docker Desktop on an arm64 Mac)

| What | Result |
|---|---|
| Image size | 3.75 GB (base 3.45 GB, Python dependencies about 0.3 GB) |
| Memory, idle | 92 MB |
| Memory, peak under load | 617 MB: 6 real non-board postings sent at once, 2 running at a time (the cap) |
| Load test | all 6 returned 200; queued as designed, finishing between 12.6 s and 38.8 s |
| Zombie processes after the load test | 0 |
| `/dev/shm` | Docker's default 64 MB was enough |

Peak memory comes from the container's cgroup counter (`/sys/fs/cgroup/memory.peak`), which includes file cache; `docker stats` peaked at 580 MiB. Size the container at 1 GB or more. AWS will likely run amd64, so the amd64 image size (reported by CI on each push) and memory should be re-checked there.

## Smoke test

```bash
docker build -t posting-triage:ci . && scripts/docker_smoke.sh posting-triage:ci
```

It starts the image with a dummy token and key and the example profile, and checks health, auth, the SSRF guard, Chromium (JIT off, no zombies), non-root, and CLI mode. It never calls Claude. CI runs the same script on every push (`.github/workflows/docker.yml`).

## Keeping Chromium patched

Each Playwright release ships a newer Chromium, so updating Playwright is how browser security fixes arrive. Because the browser runs without its sandbox, do this regularly (monthly, or soon after a Chromium security release):

1. Bump the `playwright` pin in `pyproject.toml` and the base image tag in the `Dockerfile` **together**. They must match, or Playwright can't find its browsers.
2. Check the tag exists: `docker manifest inspect mcr.microsoft.com/playwright/python:v<version>-noble`.
3. Reinstall locally, then run `pytest`, `pytest -m browser`, and the smoke test.

## Cleanup (local)

```bash
docker rm -f $(docker ps -aq --filter ancestor=posting-triage) 2>/dev/null
docker rmi posting-triage posting-triage:ci
docker rmi mcr.microsoft.com/playwright/python:v1.64.0-noble
```

The last line frees about 3.5 GB, but the next build downloads the base image again.
