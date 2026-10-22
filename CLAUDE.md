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
2. Every extracted field carries the exact quote it came from (or null if the posting is silent). Code checks each quote appears in the posting text. If a quote is missing from the text: retry the LLM once; if it fails again, FLAG.
3. Absent is not uncertain. A field the posting never mentions = no constraint. Ambiguous wording (e.g. "2+ years preferred") = FLAG. Exception: a missing location = FLAG.
4. Rules in code, profile in config. `profile.yaml` holds degree, graduation date, locations, tracks, target role types, and excluded role types. Excluded role type = SKIP; any role type not in `target_role_types` (including "other") = SKIP; ambiguous role type (e.g. "Data & ML Engineer") = FLAG. A posting whose track isn't in `tracks` = SKIP; if it lists several terms, any one in `tracks` counts as a match.
5. Liveness first. Greenhouse, Lever, and Ashby links go through their public job-board APIs. Everything else (Workday, Apple, other JS-rendered pages) opens in a headless browser (Playwright), only for links the APIs can't handle. Dead = return the company careers page. A page that still can't be read = FLAG ("couldn't verify"), never DEAD.
6. Baseline (no LLM): SKIP if the title contains (as a whole word, any case) Senior, II, III, L4, Staff, graduate, masters, phd, or Data Scientist; SKIP if location isn't Bay Area, Los Angeles, or Remote; else APPLY.
7. Eval on a synthetic benchmark. Postings are generated from a target verdict + deciding field and a hand-reviewed phrase library with known values, so gold answers are known by construction (not computed by the rules module). Hand-labeled real postings in `data/labels.csv` are a separate real-world spot check; synthetic scores are an upper bound.

## Model choice
Eval runs claude-haiku-5-5, claude-sonnet-5-5, and claude-opus-5-5. The tool defaults to the cheapest model within 5 points of the best apply-precision. Use the Batch API for eval runs.
