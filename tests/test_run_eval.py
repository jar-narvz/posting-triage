"""The eval report: wiring and formatting, on small made-up inputs."""

import datetime

from posting_triage.evaluate import score
from posting_triage.profile import Profile
from posting_triage.run_eval import approaches, format_confusion, real_postings, report, run

PROFILE = Profile(
    degree="bachelors",
    graduation_date=datetime.date(2027, 5, 1),
    locations=("Bay Area", "Los Angeles", "Remote"),
    tracks=("new_grad", "summer_2027", "spring_coop"),
    target_role_types=("swe",),
    excluded_role_types=(),
)
CANDIDATES = [
    {"id": "a1", "title": "Software Engineer, New Grad", "location": "San Jose, CA"},
    {"id": "b2", "title": "Senior Software Engineer", "location": "SF"},
    {"id": "c3", "title": "Unlabeled Engineer", "location": "SF"},
]
LABELS = [
    {"id": "a1", "gold_verdict": "apply", "locations": "gold value, not shown to approaches"},
    {"id": "b2", "gold_verdict": "skip"},
    {"id": "zz", "gold_verdict": "skip"},  # not in candidates: dropped
]


def test_real_postings_use_the_candidate_listing_not_gold_fields():
    real = real_postings(LABELS, CANDIDATES)
    assert [(p["id"], p["location"], p["gold_verdict"]) for p in real] == [
        ("a1", "San Jose, CA", "apply"),
        ("b2", "SF", "skip"),
    ]


def test_run_scores_an_approach():
    baseline = approaches(PROFILE)["baseline"]
    s = run(real_postings(LABELS, CANDIDATES), baseline)
    assert (s.n, s.true_apply, s.false_apply, s.correct) == (2, 1, 0, 2)


def test_report_has_both_sections_and_is_repeatable():
    text = report(20, 7, PROFILE, LABELS, CANDIDATES)
    assert "Synthetic benchmark: 20 postings, seed 7" in text
    assert "Real spot check: 2 hand-labeled postings" in text
    assert text.count("baseline") >= 4  # both tables, confusion, hard cases
    assert text == report(20, 7, PROFILE, LABELS, CANDIDATES)


def test_undefined_rates_print_as_n_a():
    text = report(20, 7, PROFILE, [{"id": "b2", "gold_verdict": "skip"}], CANDIDATES)
    real_section = text.split("Real spot check")[1]
    assert "0/0 = n/a" in real_section  # recall with no gold applies


def test_confusion_rows_are_gold_and_columns_predicted():
    lines = format_confusion("x", score(["apply", "skip"], ["skip", "skip"]))
    assert lines[1].split() == ["apply", "flag", "skip"]
    assert lines[2].split() == ["apply", "0", "0", "1"]
    assert lines[4].split() == ["skip", "0", "0", "1"]
