"""Run each approach on the synthetic benchmark and the real spot check, and print scores.

By default this only reads saved runs under data/runs/ and costs nothing. Two flags
call the API: --pilot N sends N synthetic postings right away (full price, for checking
the path and measuring tokens), and --submit moves the full run's batches forward
(half price; run it again later to collect results and send retries).
"""

import argparse
import os
from pathlib import Path

from posting_triage import cache
from posting_triage.baseline import baseline_verdict
from posting_triage.batch import RUNS_DIR, advance, check_requests, immediate, load_saved, step, token_totals
from posting_triage.direct import direct_verdict
from posting_triage.evaluate import FIELD_COLUMNS, VERDICTS, field_accuracy, reason_accuracy, score
from posting_triage.extract import extract, pipeline_verdict, to_fields
from posting_triage.label import read_rows
from posting_triage.profile import load_profile
from posting_triage.synthetic import generate

# Labels follow the guide, which labels against the example profile, so the eval uses it too.
PROFILE = "profile.example.yaml"
LABELS = "data/labels.csv"
CANDIDATES = "data/candidates.csv"
MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")
EFFORT = "medium"  # the same on every model, so the comparison is between models, not settings
# $ per million tokens (input, output), standard API prices; batches cost half.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}
GOLD_COLUMNS = [c for columns in FIELD_COLUMNS.values() for c in columns]


def real_postings(labels, candidates, cache_dir=None):
    """Hand-labeled postings, with the title and location as the candidate list shows
    them: the baseline must see what a person scrolling the list sees, not the gold fields."""
    by_id = {c["id"]: c for c in candidates}
    postings = []
    for r in labels:
        if r["id"] not in by_id:
            continue
        entry = cache.load(r["id"], cache_dir or cache.CACHE_DIR)
        postings.append({
            "id": r["id"], "title": by_id[r["id"]]["title"], "location": by_id[r["id"]]["location"],
            "text": entry["text"] if entry and entry["status"] == "ok" else "",
            "gold_verdict": r["gold_verdict"], "deciding_field": r["deciding_field"],
            "gold": {c: r[c] for c in GOLD_COLUMNS}, "hard": [],
        })
    return postings


def solvers(profile, model):
    """approach -> solve(text, call), the function batch.advance replays each posting through."""
    return {
        "direct": lambda text, call: direct_verdict(text, profile, call, model, EFFORT),
        "pipeline": lambda text, call: pipeline_verdict(text, profile, call, model, EFFORT),
    }


def run_dir(run_root, approach, model):
    return Path(run_root) / f"{approach}-{model}"


def texts(postings):
    return {p["id"]: p["text"] for p in postings if p["text"]}


def saved_results(run_root, approach, model, profile, postings):
    """{id: Verdict} if the run is complete, else (done, total)."""
    solve = solvers(profile, model)[approach]
    check_requests(run_dir(run_root, approach, model), texts(postings), solve)
    saved, _ = load_saved(run_dir(run_root, approach, model))
    done, needed = step(texts(postings), solve, saved)
    return done if not needed else (len(done), len(done) + len(needed))


def saved_fields(run_root, model, postings):
    """{id: labels.csv-form fields, or None}: the pipeline's extractions, replayed from its saved run."""
    def solve(text, call):
        return extract(text, call, model, EFFORT)[0]

    check_requests(run_dir(run_root, "pipeline", model), texts(postings), solve)  # extract builds the pipeline's first request
    saved, _ = load_saved(run_dir(run_root, "pipeline", model))
    done, _ = step(texts(postings), solve, saved)
    return {pid: to_fields(e) if e else None for pid, e in done.items()}


def collect(run_root, profile, postings, models):
    """(results, fields, incomplete): approach name -> {id: (verdict, field)}; pipeline
    name -> {id: fields}; incomplete name -> (done, total). The baseline needs no run."""
    results = {"baseline": {p["id"]: (baseline_verdict(p["title"], p["location"], profile.locations)[0], "")
                            for p in postings}}
    fields, incomplete = {}, {}
    for model in models:
        for approach in ("direct", "pipeline"):
            name = f"{approach} · {model.removeprefix('claude-')}"
            got = saved_results(run_root, approach, model, profile, postings)
            if isinstance(got, tuple):
                incomplete[name] = got
                continue
            results[name] = {pid: (v.verdict, v.field) for pid, v in got.items()}
            if approach == "pipeline":
                fields[name] = saved_fields(run_root, model, postings)
    return results, fields, incomplete


# ---------------------------------------------------------------------------
# Report


def ratio(num, den):
    return f"{num}/{den} = {num / den:.0%}" if den else f"{num}/0 = n/a"


def scored(postings, predictions):
    """Score and reason accuracy for the postings this approach answered."""
    answered = [p for p in postings if p["id"] in predictions]
    gold = [p["gold_verdict"] for p in answered]
    predicted = [predictions[p["id"]][0] for p in answered]
    reason = reason_accuracy([(p["gold_verdict"], p["deciding_field"]) for p in answered],
                             [predictions[p["id"]] for p in answered])
    return score(gold, predicted, [p["hard"] for p in answered]), reason


def format_scores(title, rows):
    lines = [title, f"  {'approach':22}  {'apply precision':16}  {'apply recall':16}  {'accuracy':16}  right reason"]
    for name, (s, reason) in rows.items():
        why = "-" if name == "baseline" else ratio(*reason)  # the baseline names no deciding field
        lines.append(
            f"  {name:22}  {ratio(s.true_apply, s.true_apply + s.false_apply):16}  "
            f"{ratio(s.true_apply, s.true_apply + s.missed_apply):16}  {ratio(s.correct, s.n):16}  {why}"
        )
    return lines


def format_confusion(name, s):
    lines = [f"  {name}: rows = gold, columns = predicted", "  " + " " * 8 + "".join(f"{v:>8}" for v in VERDICTS)]
    for g in VERDICTS:
        lines.append(f"  {g:8}" + "".join(f"{s.confusion[(g, p)]:>8}" for p in VERDICTS))
    return lines


def format_tags(rows):
    """Accuracy on postings with each hard case: one row per tag, one column per approach."""
    names = list(rows)
    tags = sorted({tag for s, _ in rows.values() for tag in s.by_tag})
    lines = ["  accuracy on postings with each hard case", "  " + " " * 40 + "".join(f"{n[:14]:>16}" for n in names)]
    for tag in tags:
        cells = []
        for s, _ in rows.values():
            right, total = s.by_tag.get(tag, (0, 0))
            cells.append(f"{right}/{total}" if total else "-")
        lines.append(f"  {tag[:40]:40}" + "".join(f"{c:>16}" for c in cells))
    return lines


def format_fields(postings, fields):
    lines = ["  pipeline extraction accuracy by field", "  " + " " * 22 + "".join(f"{f:>12}" for f in FIELD_COLUMNS)]
    for name, by_id in fields.items():
        answered = [p for p in postings if p["id"] in by_id]
        acc = field_accuracy([p["gold"] for p in answered], [by_id[p["id"]] for p in answered])
        lines.append(f"  {name:22}" + "".join(f"{right / total:>12.0%}" if total else f"{'n/a':>12}"
                                              for right, total in acc.values()))
    return lines


def section(title, postings, results, fields):
    rows = {name: scored(postings, preds) for name, preds in results.items()}
    lines = format_scores(title, rows) + [""]
    for name, (s, _) in rows.items():
        lines += format_confusion(name, s) + [""]
    if any(s.by_tag for s, _ in rows.values()):
        lines += format_tags(rows) + [""]
    if fields:
        lines += format_fields(postings, fields) + [""]
    return lines


def report(n, seed, profile, labels, candidates, run_root=RUNS_DIR / "main", models=MODELS):
    synthetic = generate(n=n, seed=seed)
    real = real_postings(labels, candidates)
    results, fields, incomplete = collect(run_root, profile, synthetic + real, models)
    lines = section(f"Synthetic benchmark: {n} postings, seed {seed}", synthetic, results, fields)
    if real:
        lines += section(f"Real spot check: {len(real)} hand-labeled postings (too few to rank approaches)",
                         real, results, fields)
    for name, (done, total) in incomplete.items():
        lines.append(f"not finished: {name} ({done}/{total} postings answered)")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Spending money


def cost(model, totals, batch):
    """Dollars for a run's token totals. Cache writes bill at 1.25x input, reads at 0.1x."""
    price_in, price_out = PRICES[model]
    dollars = (totals["input_tokens"] * price_in + totals["cache_creation_input_tokens"] * price_in * 1.25
               + totals["cache_read_input_tokens"] * price_in * 0.1 + totals["output_tokens"] * price_out) / 1e6
    return dollars / 2 if batch else dollars


def run_llm(client, run_root, profile, postings, models, log=print):
    """Advance every (approach, model) run. True once all of them are finished."""
    finished = True
    for model in models:
        for approach, solve in solvers(profile, model).items():
            out = advance(client, run_dir(run_root, approach, model), texts(postings), solve, log=log)
            finished = finished and out is not None
    return finished


def spend_summary(run_root, models, batch):
    lines = []
    for model in models:
        for approach in ("direct", "pipeline"):
            totals = token_totals(run_dir(run_root, approach, model))
            lines.append(f"  {approach} · {model}: {totals['input_tokens']:,} in, {totals['output_tokens']:,} out, "
                         f"{totals['cache_read_input_tokens']:,} cache reads  ≈ ${cost(model, totals, batch):.2f}")
    return "\n".join(lines)


def load_env(path=".env"):
    """KEY=VALUE lines into os.environ, without overriding what's already set. Standard
    library only; the SDK then finds ANTHROPIC_API_KEY on its own."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", type=int, default=200, help="synthetic postings (default 200)")
    parser.add_argument("--seed", type=int, default=2027)
    parser.add_argument("--models", nargs="+", default=list(MODELS), choices=MODELS)
    parser.add_argument("--pilot", type=int, metavar="N", help="send N synthetic postings now, at full price")
    parser.add_argument("--submit", action="store_true", help="advance the full run's batches (half price)")
    args = parser.parse_args(argv)
    profile = load_profile(PROFILE)

    if args.pilot:
        run_root, n, real_labels = RUNS_DIR / f"pilot-{args.pilot}", args.pilot, []
    else:
        run_root, n, real_labels = RUNS_DIR / "main", args.n, read_rows(LABELS)
    if args.pilot or args.submit:
        import anthropic

        load_env()
        client = anthropic.Anthropic()
        postings = generate(n=n, seed=args.seed) + real_postings(real_labels, read_rows(CANDIDATES))
        done = run_llm(immediate(client) if args.pilot else client, run_root, profile, postings, args.models)
        print("spent so far:\n" + spend_summary(run_root, args.models, batch=not args.pilot))
        if not done:
            print("batches still running; run the same command again later to collect them")
    print(report(n, args.seed, profile, real_labels, read_rows(CANDIDATES), run_root, args.models))
    return 0
