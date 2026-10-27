# Posting Triage Tool — Design Doc

Oct 21, 2026 · @jared

## Abstract

The posting-triage tool reads a job posting and decides, before any resume is tailored, whether the applicant should apply, skip, or look closer. It first checks that the posting is still live, then extracts the eligibility fields a human checks (role level, degree, experience, graduation window, location) and returns a verdict with the reason behind it.

It replaces a set of filtering rules that currently live inside a daily prompt. Those rules have never been measured. The tool is evaluated against a keyword baseline on a synthetic benchmark of postings whose correct answers are known by construction, and the result is reported as precision and recall on the "apply" verdict plus per-field extraction accuracy. A small set of hand-labeled real postings serves as a separate real-world spot check.

## Glossary

| Term | Meaning in this project |
| --- | --- |
| Posting | One job listing: title, company, location, description, and apply link. |
| Track | The kind of role: new grad, Summer 2027 internship, or Spring 2027 co-op. Some rules differ by track. |
| Eligibility fields | The five things checked on every posting: role level, degree requirement, years of experience, graduation window, and location. |
| Verdict | The tool's output per posting: **apply**, **flag**, or **skip**, always with a reason. |
| Flag | Shown to the user with a warning instead of hidden. Used for a graduation-window mismatch and for anything uncertain. |
| Dead link | A posting URL that returns a 404, a "no longer available" page, or under ~500 characters of real posting text. |
| Ground truth | The correct verdict and field values for a posting. Known by construction for synthetic postings; labeled by hand for the real-world spot check. |
| Synthetic benchmark | Generated postings built from a target verdict and a library of phrases with known values, so every field's correct answer is known without hand labeling. |
| Baseline | A keyword-rule classifier with no LLM. The LLM must beat it to justify itself. |
| Precision (apply) | Of the postings the tool says to apply to, the share that were truly eligible. The metric that matters most here. |
| Recall (apply) | Of the truly eligible postings, the share the tool said to apply to. |
| 🎓 tag | The marker the Simplify and speedyapply repos put on postings that require an advanced degree. |

## Problem statement

Time goes into tailoring and applying to postings that were never a fit, and the filtering that should prevent it is unmeasured and partly wrong.

### Current state: the problem

- A wrong "apply" is the expensive mistake. Each one costs a tailored resume, sometimes a cover letter, and the application itself, then often ends in an auto-rejection within a day or two.
- The causes are the same few fields every time: role level (senior, II, L4), degree (Master's or PhD), years of experience, graduation window, and location outside the Bay Area and Los Angeles.
- Years of experience is the hardest field to judge. "2+ years preferred" is sometimes soft and sometimes a real cutoff.
- Dead links waste time too. In a typical week, dozens of postings in the daily list are dead or closed, and a dead link can hide a company careers page with other roles worth applying to.

### Current state: the existing solution

The current filter is a daily scheduled prompt that pulls postings from the Simplify and speedyapply repos and filters them. Its rules are good, but they live in prose:

- **Graduate-degree filter.** Excludes a posting only on an explicit signal: the 🎓 tag, "MS/PhD", or a trailing "- PhD". It learned that "Graduate", "New Graduate" and "College Grad" at TikTok, HPE, Salesforce and Adobe mean bachelor's-level programs. When unsure, it keeps the posting.
- **Other filters.** Data Scientist titles, location priority, and spring-only rules (no single-school postings, no 2+ prior co-op rotations).
- **Dead links.** A fetch counts as failed under ~500 characters of posting text.

Its core problems:

1. **Never measured.** Nobody knows how often it is right, so it can't be improved on purpose.
2. **Not portable.** It depends on personal tools and scheduled tasks, so no one else can run it.
3. **Coarse.** It filters on degree and title only. Level, experience, and graduation window are not checked at all.
4. **No reasons.** A dropped posting disappears; a kept one doesn't say what is borderline about it.

### Comparable tools

These tools surface roles well but leave eligibility checking to the applicant.

| Tool | Works | Doesn't work |
| --- | --- | --- |
| LinkedIn | Easy Apply; alerts tailored to role types; niche and specific roles; a company's other roles are easy to reach | Postings aren't filtered by eligibility; degree, experience, and location requirements must be read manually; Easy Apply can send the default resume instead of a tailored one |
| Simplify | Many roles; sorted newest first; apply and quick-apply options | Too broad: specific roles must be found by hand; locations span the whole world; no filtering by requirements; quick apply needs an account and profile; one resume at a time |
| Handshake | Built for students: shows roles employers open only to students; quick apply that still takes a tailored resume | Mostly smaller companies; large and mid-size companies rarely post there |

**What this means for the design:** the gap these tools share is reading requirements, which is exactly stages 2 and 3 (field extraction and verdict). The one-resume limits are real pain points but a non-goal here, since the tool stops at the verdict.

Handshake shows that eligibility filtering works when employers set it up for students. Large companies post where that filtering doesn't exist, so the tool has to recover eligibility from the posting text itself.

### Desired state

- Before tailoring anything, the applicant knows which postings they are eligible for and why.
- When a posting is borderline, they see the specific reason (e.g. "requires graduation by Dec 2026") and make the call themselves.
- A dead posting never reaches them, and its company's careers page does instead.
- Anyone, including a hiring manager reading the repo, can see how accurate the triage is and on what data.

## Solution statement

### Functional requirements

1. **Liveness check.** Detect dead or closed postings before any other step, and point to the company's careers page instead.
2. **Field extraction.** For each live posting, extract the five eligibility fields from the posting text.
3. **Verdict with reason.** Return apply, flag, or skip, plus a one-line reason naming the field that decided it.
4. **Flag, don't hide, the graduation window.** A graduation-window mismatch produces a flag, never a skip; the applicant may apply anyway.
5. **Configurable profile.** The applicant's facts (graduation date, degree, target locations, tracks) live in a config file, not in code.
6. **Evaluation.** Score the classifier and the keyword baseline on the same synthetic benchmark, report precision and recall on "apply" and per-field extraction accuracy, and report a hand-labeled real-world spot check separately.
7. **Runnable by others.** Anyone can clone the repo and run it on public postings with their own API key, and a public web page shows a gallery of real results and a recorded demo without making live AI calls.

### Non-functional requirements

- **Precision over recall on "apply".** A wrong "apply" costs a tailored application; a wrong "flag" costs a glance.
- **Explainable.** Every verdict traces back to a quoted phrase in the posting.
- **Uncertain means flag.** When the evidence is missing or ambiguous, the tool flags rather than guesses.
- **Cheap.** Deterministic checks run before any LLM call, so the LLM only sees postings that need judgment.
- **Defensible.** Every design choice can be explained in an interview.
- **No private data.** No resume content, application history, contacts, or licensed fonts in the repo.

### Non-goals

- **Predicting hidden ATS screens.** Ground truth is what the posting says, not whether an application was later rejected.
- **Tailoring resumes or applying.** The tool stops at the verdict.
- **Ranking postings by how good a fit they are.** It answers "eligible?", not "how likely to get an interview?".
- **Finding new postings.** It triages a list it is given. Pointing a dead link to the careers page is the one exception.

## Solution design

The LLM reads, code decides. Each posting passes a cheap liveness check, then an LLM extracts the five eligibility fields plus role type, each with quoted evidence, then plain rules turn the fields plus the applicant's profile into a verdict.

### Key decisions

1. **Extract fields, don't ask for a verdict.** The LLM returns structured fields, not "apply/skip". *Why:* the verdict becomes explainable field by field, the profile can change without re-prompting, and extraction errors can be measured per field. *Alternative:* one prompt that outputs the verdict directly. Simpler, but a wrong answer can't be traced. B (extract fields, code decides) is the tool; A (LLM decides directly) is built only as a comparison in the eval, to show whether the split was worth it.
2. **Every field carries a quote.** Each extracted value comes with the posting phrase it came from, or `null` if the posting is silent. *Why:* the reason line in the output is that quote, and a value with no quote is easy to catch as a hallucination: code checks that each quote actually appears in the posting text. Quotes beat a confidence score, since an LLM's self-reported confidence is unreliable. If a quote isn't found in the posting, the tool retries the LLM once. If it fails again, that value can't decide the verdict: a SKIP from a field whose quote checks out still stands, and otherwise the posting is flagged.
3. **Absent is not uncertain.** A posting that says nothing about graduation dates has no constraint, so it is not flagged. A posting whose wording could go either way ("2+ years preferred") is flagged. *Why:* otherwise almost every posting would be flagged and the flag would mean nothing. One exception: a missing location is flagged, since a posting with no location usually means the page didn't load fully.
4. **Rules in code, profile in config.** Verdict logic is a small, tested Python module; the applicant's facts live in `profile.yaml`, including target role types and role types to exclude (e.g. Data Scientist). *Why:* deterministic, unit-testable, and anyone can run it with their own profile. The LLM extracts role type alongside the other fields; an excluded role type, or any role type outside the target list, is skipped, and an ambiguous one (e.g. "Data & ML Engineer") is flagged. Flag is reserved for uncertainty: a role the tool can name but the applicant doesn't want is a skip. Tracks work the same way: a posting for a term outside the profile's tracks (e.g. a fall internship) is skipped, and a posting that lists several terms matches if any one is in the profile. Every rule runs, and any SKIP beats any FLAG; the deciding field is the first rule, in the labeling guide's order, that gave the winning verdict. *Why:* a flag asks the applicant to judge, and a posting another rule already rules out leaves nothing to judge.
5. **Liveness first, through the job board's own API where one exists.** Greenhouse, Lever, Ashby, and Workday postings are checked through their job-board endpoints (for Workday, the undocumented JSON endpoint its own job page calls); anything else (Apple and other JavaScript-rendered pages) is opened in a headless browser (Playwright), which only runs on links the APIs can't handle. A 404 from a board API means the posting is gone. Some companies refuse Workday's API (HTTP 403), so any other Workday answer falls back to the browser. *Why:* JavaScript-rendered pages look empty to a plain fetch, and the ~500-character rule alone would call live postings dead. Workday moved from the browser to its API on Oct 26, 2026: on AWS Lambda its pages render empty in Chromium, while its API answers from AWS; the API is also faster and reports removed postings with a clean 404. A page that still can't be read is flagged as "couldn't verify", never marked dead.
6. **Baseline = the existing rules, as written.** Skip on "Senior", "II", "III", "L4", "Staff", "graduate", "masters", "phd", or "Data Scientist" as a whole word in the title (any case), or a location outside Bay Area, Los Angeles, or Remote. *Why:* it's what a person would write in ten minutes, so beating it is the honest bar. The Data Scientist rule gives the baseline the same role-type preference as the pipeline, so any win comes from reading the posting better. "III" was added after whole-word matching stopped "II" from catching it; the labeling guide already counts III as mid level.
7. **The API is a thin layer.** The REST API's endpoints call the same functions as the CLI, so no verdict logic lives in the API. The API and `triage run --json` return one shared pydantic schema: `url, verdict, deciding_field, quote, careers_page, detail, model, latency_ms`. *Why:* TODO (Jared).
8. **Live LLM calls are private.** `POST /triage` requires a bearer token (`TRIAGE_API_TOKEN`, compared in constant time), and the server refuses to start without one. Each token gets 10 requests a minute, a request gives up after 90 s, and at most 2 triages run at once. The public web page stays static, with no live AI calls. *Why:* TODO (Jared). *Alternative:* on Lambda, a shared counter (DynamoDB) or API Gateway throttling instead of the in-memory limiter; kept the in-memory limiter plus a cap of 2 function copies.
9. **Only public http(s) URLs are fetched.** A URL must be http or https on port 80 or 443, and every address its hostname resolves to must be public; anything else (localhost, private ranges, link-local addresses such as the cloud metadata address 169.254.169.254) is refused with a 400. Every browser connection goes through a filtering proxy that checks each destination and connects to the exact address it checked, which also covers redirects, iframes, page resources, and DNS rebinding. *Why:* TODO (Jared). *Alternative:* a Playwright route guard on each request; replaced by the proxy, which sees connections the guard can't (service workers, WebSockets) and closes DNS rebinding.
10. **One Docker image runs both the CLI and the API.** Built on Playwright's base image for the pinned Playwright version, running as an unprivileged user, with tini as process 1 and the media libraries Chromium doesn't use removed (the registry's scan went from 337 findings to 0). The Lambda Web Adapter in the image lets the same image run on Lambda unchanged. *Why:* TODO (Jared).
11. **AWS: Lambda behind a function URL, in one region (us-east-2).** The image lives in ECR (immutable tags, scanned on push); the Anthropic key, the API token, and the profile live in Parameter Store as encrypted SecureStrings, read once at startup with boto3; logs go to CloudWatch for 14 days. The function's role can only read its own parameters and write its logs, and at most 2 copies run at once. Deploys run from the Mac (`scripts/deploy.sh`) with temporary `aws login` credentials, so no long-lived AWS key exists anywhere. *Why:* TODO (Jared). *Alternatives:* App Runner (closed to new customers), ECS Express Mode (about $40 a month) and Lightsail containers ($10–15 a month, secrets only as plain environment variables) for compute; Secrets Manager (about $1 a month, adds rotation) for secrets; GitHub Actions deploying through OIDC, blocked because this account is an AWS Builder ID project whose policy denies identity providers; a stored access key in GitHub, rejected.

### How each functional requirement is met

| Requirement | Met by |
| --- | --- |
| 1. Liveness check | Stage 1: board API, else headless browser; dead postings return the careers-page URL; unreadable pages are flagged |
| 2. Field extraction | Stage 2: LLM call with a JSON schema, one value + quote per field |
| 3. Verdict with reason | Stage 3: rules module picks the deciding field and prints its quote |
| 4. Flag the graduation window | Rule: a graduation-window mismatch maps to flag, never skip |
| 5. Configurable profile | `profile.yaml`, read by the rules module only |
| 6. Evaluation | `eval/` scores baseline, direct-verdict prompt, and the pipeline on the synthetic benchmark, plus the real-world spot check |
| 7. Runnable by others | Public postings from the Simplify and speedyapply repos; API key from an environment variable |

### Edge cases

- **"Graduate" in the title.** TikTok's "Machine Learning Engineer Graduate" is bachelor's-level; a TikTok title ending "- PhD" is not. The baseline gets these wrong; the benchmark includes several on purpose.
- **Mixed levels.** "Software Engineer I/II" or "New Grad or Experienced": eligible at the lowest level listed.
- **Preferred vs required experience.** "Required" decides; "preferred" produces a flag.
- **Several locations.** Eligible if any one listed location, or Remote, matches the profile.
- **Track-specific location.** Spring co-ops accept anywhere in the US, so location rules depend on the track.
- **Live page that looks dead.** JavaScript-rendered boards, handled by decision 5. Workday is read through its API instead, and falls back to the browser when a company refuses the API.
- **Restricted programs.** Single-school postings and "2+ prior co-op rotations" skip on the spring track.

## Solution implementation

### Workflow

```
posting URL
   │
   ▼
1. Liveness ── dead ──────────► DEAD  (+ careers page)
   │        └─ unreadable ────► FLAG  "couldn't verify"
   ▼ live
2. LLM extracts fields + quotes ── quote not in text (after 1 retry) ──► FLAG, unless a verified field skips
   │
   ▼
3. Rules module (fields + profile.yaml) ──► APPLY / FLAG / SKIP + deciding quote
```

Only live postings reach the LLM, and the LLM never decides the verdict: it hands fields and quotes to a rules module that reads the applicant's profile.

### Output example

Real results from Oct 26, 2026, in the command line's format (long Workday URLs shortened with `…`). Each line is the verdict and the posting's URL; the indented line is the deciding field and the posting's own words (none for APPLY). The S&P Global line is what the deployed API answered on AWS Lambda, where Workday's pages render empty, so it can't verify the posting and flags it instead of guessing.

```
$ triage run <GM posting> <TikTok posting> <S&P Global posting>

FLAG   https://generalmotors.wd5.myworkdayjobs.com/…/2027-Summer-Intern---Machine-Learning-Engineer--AV-AI-Platform_JR-202621695
       graduation: "Must be graduating between December 2027 and August 2029"
APPLY  https://lifeattiktok.com/search/7668701361741007109
FLAG   https://spgi.wd5.myworkdayjobs.com/…/Software-Engineer---Summer-Intern-2027_331717-2
       couldn't verify (no posting text)
```

The eval prints one table: precision and recall on "apply" for the baseline, the direct-verdict prompt, and the pipeline, plus per-field extraction accuracy.

### Synthetic benchmark

Hand-labeling ~100 real postings field by field proved too slow to be worth it, so the headline eval uses generated postings with known answers instead.

- **Scenario first.** Each posting starts from a target verdict and the field that decides it (e.g. "SKIP, decided by degree"). The deciding field gets a phrase that fires. For a SKIP, earlier fields may pass or FLAG and later ones get any phrase; for a FLAG, earlier fields pass and later ones may pass or FLAG but never SKIP, since any SKIP beats any FLAG. The gold verdict is therefore known by construction, not computed by the rules module, so a test can check the rules module against it.
- **Phrase library.** Every phrase carries its true field value (e.g. "2+ years of experience preferred" → 2, preferred) and is reviewed by hand once. Each field's gold quote is the exact phrase inserted.
- **Realism filler.** Navigation, company blurbs, responsibilities, benefits, and varied section headers surround the requirements, so extraction works the way it does on real pages.
- **Known limit.** Real postings are messier than generated ones and use phrasings the library doesn't have, so synthetic scores are an upper bound. The hand-labeled real postings are reported next to them to show the gap.

## Proposed plan

The MVP is the eval, not the app: a benchmark with known answers, the baseline, and the pipeline scored side by side. Without that number the repo is just another wrapper.

### MVP

- A 200-posting synthetic benchmark with known answers, at least 40 of them hard cases ("Graduate" titles, "preferred" experience, mixed levels), plus a small hand-labeled set of real postings as a spot check.
- Baseline rules, extraction prompt, rules module, `profile.yaml`.
- `eval/` script printing precision and recall on "apply" for each approach.
- README with the results table and the key decisions behind it.

### Phases

1. **Benchmark and spot check.** Build the synthetic benchmark from a reviewed phrase library, and keep a few hand-labeled real postings (following the labeling guide) as a real-world check. Real posting text is cached locally, so labels and the eval read the same text.
2. **Baseline and eval harness.** Score the keyword rules. This sets the number to beat before any LLM code exists.
3. **Extraction and verdict rules.** Build stages 2 and 3, with unit tests on the rules module.
4. **Liveness check.** Board APIs for Greenhouse, Lever, and Ashby; headless-browser fallback (Playwright) for the rest, with a flag for pages it still can't read.
5. **Ship.** Results in the README, CI running the tests. Then publish the web page: a gallery of real results, the eval table, and a recorded demo of one posting going through the pipeline.

## Resolved questions

- **Extract fields vs. ask for a verdict?** Extract fields; the direct-verdict prompt is an eval comparison only.
- **Which LLM, and what cost is acceptable?** The eval runs Claude Haiku 5.5, Sonnet 5.5, and Opus 5.5 (roughly $0.04, $0.80, and $1.60 per 100 postings). The tool uses the cheapest model within 5 points of the best apply-precision. Below 5 points, a 100-posting test set can't tell models apart; at 5 or more, the more accurate model wins, since API cost is trivial next to the time a wrong "apply" wastes.
- **A posting with no location stated?** Flagged (decision 3).
- **Include the Data Scientist title filter?** Yes, as a role-type setting in the profile (decision 4).
- **CLI only, or a web page too?** Both: a public web page with a gallery of real results and a recorded (not live) demo, plus a CLI anyone can run locally with their own API key. No live AI calls on the page, so it costs nothing to host.
