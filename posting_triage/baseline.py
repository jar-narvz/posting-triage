"""Keyword baseline (no LLM): title and location rules only.

Decision 6 as written: what a person would set up in ten minutes, so beating it is
the honest bar. It reads only the title and the listed location, never the posting
text, and it never says FLAG. Don't make it smarter; its mistakes are the point.
"""

import re

from posting_triage.profile import location_matches

TITLE_KEYWORDS = ("Senior", "II", "III", "L4", "Staff", "graduate", "masters", "phd", "Data Scientist")
# Whole words, any case: "II" matches "I/II" but not "III" (hence its own entry), and "graduate" doesn't match "Undergraduate".
TITLE_PATTERN = re.compile(r"\b(" + "|".join(re.escape(k) for k in TITLE_KEYWORDS) + r")\b", re.IGNORECASE)


def baseline_verdict(title, location, profile_locations):
    """("apply" | "skip", reason). A blank location isn't in any region, so it skips."""
    hit = TITLE_PATTERN.search(title)
    if hit:
        return "skip", f'title: "{hit.group(0)}"'
    if not location_matches(location, profile_locations):
        return "skip", f'location: "{location}"' if location.strip() else "location: none listed"
    return "apply", "no keyword or location match"
