"""Run each approach on the synthetic benchmark and the real spot check, and print scores.

Approaches are functions (title, location, text) -> verdict, so the direct prompt and
the pipeline can join the baseline later without changing the scoring or the report.
"""

import argparse

from posting_triage.baseline import baseline_verdict
from posting_triage.evaluate import VERDICTS, score
from posting_triage.label import read_rows
from posting_triage.profile import load_profile
from posting_triage.synthetic import generate

# Labels follow the guide, which labels against the example profile, so the eval uses it too.
PROFILE = "profile.example.yaml"
LABELS = "data/labels.csv"
CANDIDATES = "data/candidates.csv"


def approaches(profile):
    return {
        "baseline": lambda title, location, text: baseline_verdict(title, location, profile.locations)[0],
    }


def real_postings(labels, candidates):
    """Hand-labeled postings, with the title and location as the candidate list shows
    them: the baseline must see what a person scrolling the list sees, not the gold fields."""
    by_id = {c["id"]: c for c in candidates}
    return [
        {"id": r["id"], "title": by_id[r["id"]]["title"], "location": by_id[r["id"]]["location"],
         "text": "", "gold_verdict": r["gold_verdict"], "hard": []}
        for r in labels
        if r["id"] in by_id
    ]


def run(postings, predict):
    gold = [p["gold_verdict"] for p in postings]
    predicted = [predict(p["title"], p["location"], p["text"]) for p in postings]
    return score(gold, predicted, [p["hard"] for p in postings])


def ratio(num, den):
    return f"{num}/{den} = {num / den:.0%}" if den else f"{num}/0 = n/a"


def format_scores(title, scores):
    lines = [title, f"  {'approach':10}  {'apply precision':18}  {'apply recall':18}  {'accuracy':18}"]
    for name, s in scores.items():
        lines.append(
            f"  {name:10}  {ratio(s.true_apply, s.true_apply + s.false_apply):18}  "
            f"{ratio(s.true_apply, s.true_apply + s.missed_apply):18}  {ratio(s.correct, s.n):18}"
        )
    return lines


def format_confusion(name, s):
    lines = [f"  {name}: rows = gold, columns = predicted", "  " + " " * 8 + "".join(f"{v:>8}" for v in VERDICTS)]
    for g in VERDICTS:
        lines.append(f"  {g:8}" + "".join(f"{s.confusion[(g, p)]:>8}" for p in VERDICTS))
    return lines


def format_tags(name, s):
    lines = [f"  {name}: accuracy on postings with each hard case"]
    for tag, (right, total) in s.by_tag.items():
        lines.append(f"    {ratio(right, total):14}  {tag}")
    return lines


def report(n, seed, profile, labels, candidates):
    synthetic = generate(n=n, seed=seed)
    real = real_postings(labels, candidates)
    fns = approaches(profile)
    syn_scores = {name: run(synthetic, f) for name, f in fns.items()}
    real_scores = {name: run(real, f) for name, f in fns.items()}

    lines = format_scores(f"Synthetic benchmark: {n} postings, seed {seed}", syn_scores)
    lines.append("")
    for name, s in syn_scores.items():
        lines += format_confusion(name, s) + [""] + format_tags(name, s) + [""]
    lines += format_scores(f"Real spot check: {len(real)} hand-labeled postings (too few to rank approaches)", real_scores)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", type=int, default=200, help="synthetic postings (default 200)")
    parser.add_argument("--seed", type=int, default=2027)
    args = parser.parse_args(argv)
    print(report(args.n, args.seed, load_profile(PROFILE), read_rows(LABELS), read_rows(CANDIDATES)))
    return 0
