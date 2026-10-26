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
| `TRIAGE_DOCS` | `on` | `off` hides `/docs`, `/redoc`, and `/openapi.json`; any other value stops startup |
| `TRIAGE_SSM_PREFIX` | (unset) | On AWS: read the token, the Anthropic key, and the profile from Parameter Store under this prefix instead of the three settings above |

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
- **The Lambda Web Adapter** in `/opt/extensions/` (v1.1.0, pinned by the digest of its multi-arch index). On Lambda it turns each invocation into an HTTP request to the server; anywhere else it's unused. The smoke test checks it matches the image's architecture.
- **boto3**, only to read the API's settings from Parameter Store on AWS.

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

## AWS

Everything runs in **us-east-2** with the AWS CLI profile `triage`. The account ID is looked up when a command runs, so it never appears in a file:

```bash
ACCT=$(aws sts get-caller-identity --profile triage --region us-east-2 --query Account --output text)
```

### The deployed API (Phase 1: deployed by hand from a Mac)

Decision 11, built step by step from Oct 26, 2026, each step shown and approved before it runs. GitHub Actions takes over deploys (OIDC) when the code is pushed (Phase 2). The creation commands are added below as each step runs.

| Resource | Name | Monthly cost |
|---|---|---|
| 3 SecureString parameters | `/posting-triage/anthropic-api-key`, `/posting-triage/api-token`, `/posting-triage/profile` | free (standard tier, default AWS key) |
| ECR repository (keeps the last 3 images) | `posting-triage` | about $0.10 per GB stored |
| CloudWatch log group (14-day retention) | `/aws/lambda/posting-triage` | about $0 at this volume |
| IAM role: logs + read `/posting-triage/*` | `posting-triage-lambda` | free |
| Lambda function: arm64, 2048 MB, 120 s, reserved concurrency 2 | `posting-triage` | $0 when idle |
| Function URL (auth `NONE`; the app checks the token) | on `posting-triage` | free |

The function's own settings hold no secrets: `TRIAGE_SSM_PREFIX=/posting-triage`, `TRIAGE_DOCS=off`, `HOME=/tmp` (Lambda's filesystem is read-only except `/tmp`).

The Anthropic key comes from its own Console workspace with a $5 monthly spend limit. It's typed straight into the parameter, never into a file or chat.

#### Creation commands (run in this order)

1. Parameters (SecureString, standard tier, the default `aws/ssm` key). Run these in a real terminal: the hidden prompt needs a keyboard.

```bash
read -rs "KEY?Anthropic key: " && aws ssm put-parameter --name /posting-triage/anthropic-api-key --type SecureString --value "$KEY" --profile triage --region us-east-2 && unset KEY
aws ssm put-parameter --name /posting-triage/api-token --type SecureString --value "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" --profile triage --region us-east-2
aws ssm put-parameter --name /posting-triage/profile --type SecureString --value file://profile.yaml --profile triage --region us-east-2
```

2. ECR repository (immutable tags, scan on push) that keeps the 3 newest images, then the image, tagged with its commit:

```bash
aws ecr create-repository --repository-name posting-triage --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true --profile triage --region us-east-2
aws ecr put-lifecycle-policy --repository-name posting-triage --lifecycle-policy-text '{"rules":[{"rulePriority":1,"description":"Keep only the 3 newest images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":3},"action":{"type":"expire"}}]}' --profile triage --region us-east-2
REG="${ACCT}.dkr.ecr.us-east-2.amazonaws.com"
TAG=$(git rev-parse --short HEAD)
aws ecr get-login-password --profile triage --region us-east-2 | docker login --username AWS --password-stdin "$REG"
docker build --platform linux/arm64 --provenance=false -t "posting-triage:${TAG}" .
docker tag "posting-triage:${TAG}" "$REG/posting-triage:${TAG}" && docker push "$REG/posting-triage:${TAG}"
```

3. Log group with 14-day retention, made before the function (otherwise Lambda creates it with no expiry):

```bash
aws logs create-log-group --log-group-name /aws/lambda/posting-triage --profile triage --region us-east-2
aws logs put-retention-policy --log-group-name /aws/lambda/posting-triage --retention-in-days 14 --profile triage --region us-east-2
```

Teardown, in this order (the function first, then what it uses), then revoke the key in the Anthropic Console:

```bash
aws lambda delete-function-url-config --function-name posting-triage --profile triage --region us-east-2
aws lambda delete-function --function-name posting-triage --profile triage --region us-east-2
aws logs delete-log-group --log-group-name /aws/lambda/posting-triage --profile triage --region us-east-2
aws iam delete-role-policy --role-name posting-triage-lambda --policy-name read-parameters --profile triage --region us-east-2
aws iam detach-role-policy --role-name posting-triage-lambda --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole --profile triage --region us-east-2
aws iam delete-role --role-name posting-triage-lambda --profile triage --region us-east-2
aws ecr delete-repository --repository-name posting-triage --force --profile triage --region us-east-2
aws ssm delete-parameters --names /posting-triage/anthropic-api-key /posting-triage/api-token /posting-triage/profile --profile triage --region us-east-2
```

### Budget alert (created first)

A $5 monthly cost budget, `posting-triage-monthly`, with email alerts when actual spend passes 80% and when forecast spend passes 100%. Credits are excluded, so the budget tracks real usage instead of reading $0 while the credit pays. Budgets with email alerts are free. The Budgets API lives only in us-east-1.

Teardown:

```bash
aws budgets delete-budget --account-id "$ACCT" --budget-name posting-triage-monthly --profile triage --region us-east-1
```

### Lambda prototype (Oct 26, 2026; torn down)

A throwaway test of whether Chromium runs on Lambda, built and torn down the same day (about 52 minutes on AWS, a few cents). Function: arm64, 2048 MB, 120 s timeout, the image plus the Lambda Web Adapter v1.1.0 pinned by digest, a function URL, and reserved concurrency 2.

What it showed:

- **Chromium needs `--no-zygote` on Lambda.** Without it every tab crashed ("Target crashed"); Chromium's log showed the zygote's credential change was forbidden ("Operation not permitted"). The flag is now in `CHROMIUM_ARGS`. Don't set `TINI_SUBREAPER` there either: Lambda forbids that too, and the app won't start.
- **Workday pages render empty on Lambda**, even though Workday sends the same files as anywhere else; other JavaScript sites (TikTok, Waymo, iCIMS) read fine. That's why Workday now goes through its API (decision 5), which answers from AWS.
- **Measured:** `/health` about 22 s cold and 0.2 s warm; a triage that needs the browser about 60 s cold and 3–11 s warm, so warm it up before a demo. Peak memory 912 MB of 2048. No token or a wrong token → 401; the cloud metadata address → 400.
- **On Lambda, an error's traceback is logged only when the next request arrives**, because Lambda freezes the environment once the response is sent. Send one more request before concluding there was no error. It uses a fake Anthropic key and a throwaway API token, so no real secrets reach AWS. The function runs as the role `posting-triage-proto`, which can only write its own logs. Run the teardown in this order: the function URL and the function first, then its log group, then the role (detach its policy first), then the image repository. In zsh, write `${ACCT}` before a colon, because zsh reads `$ACCT:r` as a modifier.

Teardown:

```bash
aws lambda delete-function-url-config --function-name posting-triage-proto --profile triage --region us-east-2
aws lambda delete-function --function-name posting-triage-proto --profile triage --region us-east-2
aws logs delete-log-group --log-group-name /aws/lambda/posting-triage-proto --profile triage --region us-east-2
aws iam detach-role-policy --role-name posting-triage-proto --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole --profile triage --region us-east-2
aws iam delete-role --role-name posting-triage-proto --profile triage --region us-east-2
aws ecr delete-repository --repository-name posting-triage-proto --force --profile triage --region us-east-2
docker logout "$ACCT.dkr.ecr.us-east-2.amazonaws.com"
```
