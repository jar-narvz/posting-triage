# Posting Triage Tool

## What this is
A tool that reads a job posting and returns APPLY, FLAG, or SKIP (or DEAD) with a one-line reason quoted from the posting. It checks that a posting is live, has an LLM extract eligibility fields with quoted evidence, then applies deterministic rules against the applicant's profile. The project's headline is its eval: precision/recall on "apply" and per-field extraction accuracy for a keyword baseline vs. an LLM-decides prompt vs. this pipeline, across three Claude models, on a synthetic benchmark with known answers.

Owner: Jared Narvaez (UC Berkeley CS, May 2027). This is a public portfolio repo.

## Rules for working in this repo
- Plan first; wait for my OK before creating or editing files.
- I must be able to defend every engineering decision in an interview. After each phase:
  explain the key code in plain language, then ask me 3 questions about why it works the way it does.
  Don't move on until I've answered.
- Keep it simple: standard library first, then only the dependencies listed in the design. Ask before adding any other.
- Never put an API key, personal data, or full posting text in a commit. Keys go in `.env` (gitignored).
- Tests come with the code, not after. Run `pytest` before telling me a phase is done.
- Don't change a confirmed design decision without asking. If one seems wrong, tell me why.
- Work in small commits: one logical change per commit (e.g. one module plus its tests), never a whole phase in one commit.
- Commit messages: short imperative summary line (e.g. "Add keyword baseline and tests"), plus a body line on why if it isn't obvious.
- Run pytest before each commit; don't commit failing tests.
- Show me the files and the commit message before each commit, and don't push until I say so.

## Confirmed design decisions
1. The LLM reads, code decides. The LLM fills a structured form; a rules module turns the form + `profile.yaml` into a verdict. A direct "LLM decides" prompt exists only as an eval comparison.
2. Every extracted field carries the exact quote it came from (or null if the posting is silent). Code checks each quote appears in the posting text. If a quote is missing from the text: retry the LLM once; if it fails again, that value can't decide anything: a SKIP from a verified field still stands, otherwise FLAG.
3. Absent is not uncertain. A field the posting never mentions = no constraint. Ambiguous wording (e.g. "2+ years preferred") = FLAG. Exception: a missing location = FLAG.
4. Rules in code, profile in config. `profile.yaml` holds degree, graduation date, locations, tracks, target role types, and excluded role types. Excluded role type = SKIP; any role type not in `target_role_types` (including "other") = SKIP; ambiguous role type (e.g. "Data & ML Engineer") = FLAG. A posting whose track isn't in `tracks` = SKIP; if it lists several terms, any one in `tracks` counts as a match. Every rule runs: any SKIP beats any FLAG, and the deciding field is the first rule, in the labeling guide's order, that gave the winning verdict.
5. Liveness first. Greenhouse, Lever, Ashby, and Workday links go through their job-board APIs (Workday's is the undocumented JSON its job page calls; any answer but 200 or 404, e.g. a 403 refusal, falls back to the browser). Everything else (Apple, other JS-rendered pages) opens in a headless browser (Playwright), only for links the APIs can't handle. Changed Oct 26, 2026: Workday pages render empty on AWS Lambda. Dead = return the company careers page. A page that still can't be read = FLAG ("couldn't verify"), never DEAD.
6. Baseline (no LLM): SKIP if the title contains (as a whole word, any case) Senior, II, III, L4, Staff, graduate, masters, phd, or Data Scientist; SKIP if location isn't Bay Area, Los Angeles, or Remote; else APPLY.
7. Eval on a synthetic benchmark. Postings are generated from a target verdict + deciding field and a hand-reviewed phrase library with known values, so gold answers are known by construction (not computed by the rules module). Hand-labeled real postings in `data/labels.csv` are a separate real-world spot check; synthetic scores are an upper bound.

## Model choice
Eval runs claude-haiku-5-5, claude-sonnet-5-5, and claude-opus-5-5. The tool defaults to the cheapest model within 5 points of the best apply-precision. Use the Batch API for eval runs.

## Deployment work (added Oct 23, 2026) — work in progress
This repo is still a work in progress. Before planning any deployment task, check what
actually exists in the code; never assume a module or phase from the original plan is done.

### Approved new dependencies
fastapi, uvicorn[standard], httpx (for FastAPI's TestClient). Ask before adding anything else,
including AWS SDKs (deploys use the AWS CLI inside GitHub Actions, not app code).
Added Oct 25–26, 2026: the AWS Lambda Web Adapter v1.1.0 (in the image, pinned by digest), and
boto3 (the `aws` extra), used only to read the API's settings from Parameter Store at startup.

### Proposed design decisions (confirm each with me before building on it)
7. The API is a thin layer. Endpoints call the same functions the CLI calls; no verdict
   logic lives in the API. The CLI and API share one response schema (pydantic).
8. Live LLM calls are private. POST /triage requires a bearer token from an env var
   (TRIAGE_API_TOKEN). The public GitHub Pages site stays static, with no live AI calls
   (the original web-page spec). The API also has a per-token rate limit and a request timeout.
9. The API refuses to fetch anything but public http(s) URLs: no localhost, private IP
   ranges, or link-local addresses (e.g. the cloud metadata address 169.254.169.254).
   This prevents server-side request forgery through the liveness checker.
10. One Docker image runs both the CLI and the API.
11. AWS: one region (us-east-2), one service (Lambda behind a function URL). The image lives
    in ECR; the Anthropic key, API token, and profile live in Parameter Store as SecureStrings,
    read by the app with boto3 at startup; logs go to CloudWatch. GitHub Actions deploys using
    an OIDC role, so no long-lived AWS keys exist anywhere. (Oct 26, 2026: Parameter Store
    replaced Secrets Manager: free, same encryption; only built-in rotation is lost.)

### AWS safety rules
- Never create a billable AWS resource without first showing me the exact commands and the
  expected monthly cost, and waiting for my OK.
- The first AWS step is always a budget alert. Every resource gets a teardown command in
  docs/deploy.md.
- Never commit AWS account IDs, ARNs with account IDs, keys, or tokens. Use GitHub secrets
  and variables.
