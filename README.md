# posting-triage

Reads a job posting and answers APPLY, FLAG, SKIP, or DEAD, with a one-line reason quoted from the posting. It checks that the posting is live, has an LLM fill in a form of eligibility fields with the exact quote behind each one, checks that every quote really appears in the posting, and then applies deterministic rules against the applicant's profile. The LLM reads; code decides.

## Results

Full eval run, Oct 24, 2026: 200 synthetic postings (seed 2027) through the Batch API.

| Approach | Apply precision | Apply recall | Accuracy | Right reason | Cost |
|---|---|---|---|---|---|
| Keyword baseline (no LLM) | 54/98 = 55% | 54/70 = 77% | 111/200 = 56% | – | $0 |
| Direct prompt · Haiku 5.5 | 70/70 = 100% | 70/70 = 100% | 199/200 = 99.5% | 199/200 = 99.5% | $0.03 |
| **Pipeline · Haiku 5.5** | **70/70 = 100%** | **70/70 = 100%** | **200/200 = 100%** | **200/200 = 100%** | **$0.05** |
| Direct prompt · Sonnet 5.5 | 67/70 = 96% | 67/70 = 96% | 188/200 = 94% | 187/200 = 94% | $0.17 |
| Pipeline · Sonnet 5.5 | 70/70 = 100% | 70/70 = 100% | 200/200 = 100% | 200/200 = 100% | $0.44 |
| Direct prompt · Opus 5.5 | 70/70 = 100% | 70/70 = 100% | 200/200 = 100% | 200/200 = 100% | $0.62 |
| Pipeline · Opus 5.5 | 70/70 = 100% | 70/70 = 100% | 200/200 = 100% | 200/200 = 100% | $0.97 |

*Apply precision:* of the postings an approach said to apply to, how many it should have. *Right reason:* the verdict and the deciding field are both right. *Cost:* the whole run, 200 synthetic plus 5 real postings, at batch price.

**What it shows**

- **Any LLM approach beats keyword rules:** 56% → 94–100% accuracy. Keyword rules have no FLAG at all: every posting that needed a human look was wrongly answered APPLY or SKIP.
- **The pipeline scored 100% on every model; the direct prompt's accuracy depended on the model** (94–100%; Haiku's one miss was a posting with several locations, one of which matched). Most of Sonnet's direct misses broke a decision rule rather than misreading the posting: five times it FLAGged an ambiguous role type when another rule had already SKIPped. In the pipeline, "any SKIP beats any FLAG" is code, so that mistake can't happen.
- **Haiku is the default model.** It ties the best score for about 1/20 the cost of Opus. (The rule: the cheapest model within 5 points of the best apply precision.)
- **Every pipeline answer is checkable.** Each field carries the posting's exact words, and code confirms they appear in the text. A direct answer's reason is only the model's word.

**How far to trust it**

- **The synthetic scores are an upper bound.** Postings are generated from a target verdict, a deciding field, and a hand-reviewed phrase library, so the right answers are known by construction, not computed by the rules being tested. The benchmark is near its ceiling: it shows the approaches tie at the top, not by how much the pipeline would win on messier text.
- **Real spot check: 5 hand-labeled real postings**, re-checked against the labeling guide on Oct 24, 2026. Every LLM approach got all 5 verdicts right, and the baseline got 3 (two wrong APPLYs). Right reason was 80–100%. All 5 are SKIPs, so they test verdicts and reasons but can't measure apply precision, and 5 is too few to rank approaches.

**Reproducing it**

`.venv/bin/python eval/run_eval.py` re-scores a saved run with no API calls. The raw responses aren't committed, because they quote real postings, and neither is the cached text of the real postings. On a fresh checkout, run `triage cache` first so the real postings have text, then `eval/run_eval.py --submit` generates the same 200 synthetic postings and sends them through the Batch API (about $2.30 for all six LLM runs). Run the same command again to collect the results once the batches finish.
