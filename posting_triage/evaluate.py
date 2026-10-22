"""Score predicted verdicts against gold ones. Pure functions, no I/O.

"apply" is the positive class: precision is the share of predicted applies that
were truly eligible (a wrong apply wastes a tailored application), recall the
share of eligible postings that got an apply. FLAG and SKIP both count as "not apply".
"""

from collections import Counter
from dataclasses import dataclass

VERDICTS = ("apply", "flag", "skip")


@dataclass(frozen=True)
class Score:
    n: int
    true_apply: int  # predicted apply, gold apply
    false_apply: int  # predicted apply, gold flag/skip
    missed_apply: int  # gold apply, predicted something else
    correct: int  # predicted verdict == gold verdict
    confusion: Counter  # (gold, predicted) -> count
    by_tag: dict  # hard-case tag -> (correct, total)

    @property
    def precision(self):
        """None when nothing was predicted apply: undefined, not zero."""
        predicted = self.true_apply + self.false_apply
        return self.true_apply / predicted if predicted else None

    @property
    def recall(self):
        gold = self.true_apply + self.missed_apply
        return self.true_apply / gold if gold else None

    @property
    def accuracy(self):
        return self.correct / self.n if self.n else None


def score(gold, predicted, tags=None):
    """`gold` and `predicted` are parallel lists of verdicts; `tags`, if given, a
    parallel list of each posting's hard-case tags."""
    if len(gold) != len(predicted) or (tags is not None and len(tags) != len(gold)):
        raise ValueError("gold, predicted, and tags must be the same length")
    pairs = list(zip(gold, predicted))
    tag_correct, tag_total = Counter(), Counter()
    for (g, p), posting_tags in zip(pairs, tags or [()] * len(pairs)):
        for tag in set(posting_tags):  # a tag listed twice on one posting still counts once
            tag_total[tag] += 1
            tag_correct[tag] += g == p
    return Score(
        n=len(pairs),
        true_apply=sum(g == "apply" and p == "apply" for g, p in pairs),
        false_apply=sum(g != "apply" and p == "apply" for g, p in pairs),
        missed_apply=sum(g == "apply" and p != "apply" for g, p in pairs),
        correct=sum(g == p for g, p in pairs),
        confusion=Counter(pairs),
        by_tag={tag: (tag_correct[tag], tag_total[tag]) for tag in sorted(tag_total)},
    )
