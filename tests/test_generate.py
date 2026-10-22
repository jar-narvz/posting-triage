"""Checks on generated postings: the answer key must agree with the labeling guide's
policy (written separately in guide_policy.py), and every quote must be real text."""

from collections import Counter

import pytest

from guide_policy import policy_verdict
from posting_triage.label import LABEL_COLUMNS
from posting_triage.synthetic import DECIDERS, generate, plan_scenarios

POSTINGS = generate()


def test_same_seed_same_postings_and_a_new_seed_differs():
    assert generate(n=30, seed=7) == generate(n=30, seed=7)
    assert generate(n=30, seed=7) != generate(n=30, seed=8)


def test_plan_has_the_verdict_mix_and_covers_every_deciding_field():
    counts = Counter(plan_scenarios(200))
    verdicts = Counter(v for v, _ in plan_scenarios(200))
    assert verdicts == {"apply": 70, "flag": 60, "skip": 70}
    for verdict, fields in DECIDERS.items():
        for field in fields:
            assert counts[(verdict, field)] >= 10, (verdict, field)


@pytest.mark.parametrize("n", [1, 7, 50, 200])
def test_plan_has_exactly_n_postings(n):
    assert len(plan_scenarios(n)) == n


@pytest.mark.parametrize("posting", POSTINGS, ids=lambda p: p["id"])
def test_answer_key_matches_the_guides_rule_order(posting):
    assert policy_verdict(posting["gold"]) == (posting["gold_verdict"], posting["deciding_field"])


@pytest.mark.parametrize("posting", POSTINGS, ids=lambda p: p["id"])
def test_every_quote_appears_verbatim_in_the_text(posting):
    for field, quote in posting["quotes"].items():
        if quote is not None:
            assert quote in posting["text"], field


def test_gold_has_every_field_column():
    fields = set(LABEL_COLUMNS) - {"id", "url", "company", "title", "gold_verdict", "deciding_field",
                                   "notes", "labeled_at"}
    for posting in POSTINGS:
        assert set(posting["gold"]) == fields


def test_hard_cases_are_common_but_not_everywhere():
    with_hard = sum(bool(p["hard"]) for p in POSTINGS)
    assert 40 <= with_hard <= 150
    tags = Counter(tag for p in POSTINGS for tag in p["hard"])
    assert min(tags.values()) >= 5, tags


def test_ids_and_titles():
    assert len({p["id"] for p in POSTINGS}) == len(POSTINGS)
    assert all("{role}" not in p["title"] for p in POSTINGS)


def test_missing_location_means_no_location_line():
    for posting in POSTINGS:
        assert ("Location:" in posting["text"]) == bool(posting["location"])
