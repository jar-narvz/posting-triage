"""Scoring on small cases worked out by hand."""

import pytest

from posting_triage.evaluate import score

# 6 postings: 3 gold apply. Predicted apply on 4 of them, 2 truly eligible.
GOLD = ["apply", "apply", "apply", "flag", "skip", "skip"]
PRED = ["apply", "apply", "skip", "apply", "apply", "skip"]


def test_counts_precision_recall_accuracy():
    s = score(GOLD, PRED)
    assert (s.n, s.true_apply, s.false_apply, s.missed_apply, s.correct) == (6, 2, 2, 1, 3)
    assert s.precision == 2 / 4
    assert s.recall == 2 / 3
    assert s.accuracy == 3 / 6


def test_flag_and_skip_are_both_not_apply_but_differ_for_accuracy():
    s = score(["flag"], ["skip"])
    assert (s.false_apply, s.missed_apply, s.correct) == (0, 0, 0)


def test_confusion_counts_gold_predicted_pairs():
    s = score(GOLD, PRED)
    assert s.confusion[("apply", "apply")] == 2
    assert s.confusion[("skip", "apply")] == 1
    assert s.confusion[("flag", "apply")] == 1
    assert s.confusion[("apply", "skip")] == 1
    assert s.confusion[("flag", "skip")] == 0
    assert sum(s.confusion.values()) == 6


def test_precision_is_undefined_when_nothing_is_predicted_apply():
    s = score(["apply", "skip"], ["skip", "skip"])
    assert s.precision is None
    assert s.recall == 0


def test_recall_is_undefined_with_no_gold_applies():
    assert score(["skip"], ["apply"]).recall is None


def test_empty_input():
    s = score([], [])
    assert (s.n, s.precision, s.recall, s.accuracy) == (0, None, None, None)


def test_accuracy_by_hard_case_tag():
    tags = [["graduate"], ["graduate", "i/ii"], [], ["i/ii"], [], []]
    s = score(GOLD, PRED, tags)
    # graduate: postings 1 (right) and 2 (right); i/ii: postings 2 (right) and 4 (wrong)
    assert s.by_tag == {"graduate": (2, 2), "i/ii": (1, 2)}


def test_a_tag_repeated_on_one_posting_counts_once():
    assert score(["apply"], ["skip"], [["x", "x"]]).by_tag == {"x": (0, 1)}


@pytest.mark.parametrize("tags", [None, [[]] * 6])
def test_no_tags_means_no_tag_breakdown(tags):
    assert score(GOLD, PRED, tags).by_tag == {}


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError):
        score(["apply"], [])
    with pytest.raises(ValueError):
        score(["apply"], ["apply"], tags=[])
