"""Scoring on small cases worked out by hand."""

import pytest

from pathlib import Path

from posting_triage.evaluate import field_accuracy, made_up_quotes, reason_accuracy, score, unquoted_verdicts
from posting_triage.profile import load_profile

PROFILE = load_profile(Path(__file__).parent.parent / "profile.example.yaml")

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


GOLD_ROW = {"role_type": "swe", "track": "new_grad", "degree": "masters", "degree_strength": "preferred",
            "role_level": "entry", "experience_years": "", "experience_strength": "", "grad_start": "",
            "grad_end": "2027-06", "locations": "Seattle, WA; San Jose, CA", "remote": "false"}


def test_field_accuracy_needs_every_column_of_a_field():
    wrong_strength = GOLD_ROW | {"degree_strength": "required"}
    acc = field_accuracy([GOLD_ROW, GOLD_ROW], [GOLD_ROW, wrong_strength], PROFILE)
    assert acc["degree"] == (1, 2)
    assert acc["role_type"] == (2, 2)


def location_right(gold, predicted):
    return field_accuracy([gold], [predicted], PROFILE)["location"] == (1, 1)


def test_location_is_right_when_the_rule_reads_it_the_same_way():
    # "Seattle, WA; San Jose, CA" passes the Bay Area profile, however the places are written.
    assert location_right(GOLD_ROW, GOLD_ROW | {"locations": "USA, WA, Seattle; US, CA, San Jose"})
    assert location_right(GOLD_ROW, GOLD_ROW | {"locations": "San Jose"})


def test_location_is_wrong_when_the_rule_would_decide_differently():
    assert not location_right(GOLD_ROW, GOLD_ROW | {"locations": "Seattle, WA"})  # pass -> skip
    assert not location_right(GOLD_ROW, GOLD_ROW | {"locations": ""})  # pass -> flag
    boston = GOLD_ROW | {"locations": "Boston, MA"}
    assert not location_right(boston, boston | {"locations": "Boston; Los Angeles"})  # skip -> pass


def test_location_needs_the_same_remote_flag():
    assert not location_right(GOLD_ROW, GOLD_ROW | {"remote": "true"})


def test_location_is_judged_with_the_gold_track():
    # A spring co-op accepts any US location; a wrong track must not make location wrong too.
    coop = GOLD_ROW | {"track": "spring_coop", "locations": "Austin, TX"}
    assert location_right(coop, coop | {"track": "new_grad"})


def test_no_extraction_is_wrong_on_every_field():
    assert set(field_accuracy([GOLD_ROW], [None], PROFILE).values()) == {(0, 1)}


def test_reason_accuracy_needs_verdict_and_field():
    gold = [("skip", "degree"), ("flag", "location"), ("apply", "")]
    predicted = [("skip", "degree"), ("flag", "experience"), ("apply", "")]
    assert reason_accuracy(gold, predicted) == (2, 3)


def test_field_and_reason_inputs_must_line_up():
    with pytest.raises(ValueError):
        field_accuracy([GOLD_ROW], [], PROFILE)
    with pytest.raises(ValueError):
        reason_accuracy([("apply", "")], [])


POSTING = {"a": "Requires a BS in Computer Science.\nMust be graduating by June 2027.", "b": "Remote, US only."}


def test_an_answer_with_any_quote_not_in_the_posting_is_made_up():
    quotes = {"a": ["Requires a BS in Computer Science.", "PhD required"], "b": ["Remote, US only."]}
    assert made_up_quotes(quotes, POSTING) == (1, 2)


def test_quotes_are_matched_like_the_pipeline_matches_its_own():
    # Line breaks, runs of spaces, and curly quote marks don't make a real quote look made up.
    texts = {"a": "Must be  graduating\nby June 2027. It's a “new grad” role."}
    quotes = {"a": ["Must be graduating by June 2027.", "It’s a \"new grad\" role."]}
    assert made_up_quotes(quotes, texts) == (0, 1)


def test_answers_without_quotes_are_not_counted():
    # An APPLY gives no quotes, a failed answer gives None, and blank quotes are no quote.
    assert made_up_quotes({"a": [], "b": None}, POSTING) == (0, 0)
    assert made_up_quotes({"a": ["", "  "]}, POSTING) == (0, 0)


def test_a_flag_or_skip_with_no_quote_is_unbacked_except_a_missing_location():
    predicted = {"a": ("skip", "experience"), "b": ("flag", "location"), "c": ("apply", ""), "d": ("skip", "degree")}
    quotes = {"a": [], "b": [], "c": [], "d": ["Requires a BS in Computer Science."]}
    assert unquoted_verdicts(predicted, quotes) == 1
    assert unquoted_verdicts({"a": ("flag", "graduation")}, {"a": None}) == 1  # no usable answer quotes nothing
