"""Stage 3: turn extracted fields + the profile into a verdict. Pure functions, no I/O.

Fields come in the labels.csv format (strings, "" when the posting is silent), so the
same code judges gold labels and LLM extractions. The rules run in the labeling guide's
order and the first one to fire decides. Liveness (rule 1) happens before this stage.
"""

from dataclasses import dataclass

from posting_triage.candidates import is_us_location
from posting_triage.profile import location_matches

APPLY, FLAG, SKIP = "apply", "flag", "skip"
PASS = None
RULE_ORDER = ["role_type", "track", "degree", "role_level", "experience", "graduation", "location"]
DEGREE_RANK = {"none": 0, "bachelors": 1, "masters": 2, "phd": 3}
MAX_REQUIRED_YEARS = 1  # "1+ years required" is fine for a new grad; more is a SKIP


@dataclass(frozen=True)
class Verdict:
    verdict: str
    field: str  # the deciding field; "" for APPLY
    quote: str | None  # the posting's words behind it, when there are any


def decide(fields, profile, quotes=None, unverified=()):
    """`quotes` maps a rule's field to the text it came from; `unverified` lists
    fields whose quote wasn't found in the posting even after a retry."""
    quotes = quotes or {}
    if unverified:  # rule 2: a value we can't trace to the posting can't decide anything
        in_order = [f for f in RULE_ORDER if f in unverified] or sorted(unverified)
        return Verdict(FLAG, "quote", quotes.get(in_order[0]))
    for field in RULE_ORDER:
        outcome = RULES[field](fields, profile)
        if outcome is not PASS:
            return Verdict(outcome, field, quotes.get(field))
    return Verdict(APPLY, "", None)


def role_type(f, profile):
    if f["role_type"] == "ambiguous":
        return FLAG
    if f["role_type"] in profile.excluded_role_types or f["role_type"] not in profile.target_role_types:
        return SKIP
    return PASS


def track(f, profile):
    return PASS if not f["track"] or f["track"] in profile.tracks else SKIP


def degree(f, profile):
    if DEGREE_RANK.get(f["degree"], 0) <= DEGREE_RANK[profile.degree]:
        return PASS
    return FLAG if f["degree_strength"] == "preferred" else SKIP


def role_level(f, profile):
    return {"mid": SKIP, "senior": SKIP, "unclear": FLAG}.get(f["role_level"], PASS)


def experience(f, profile):
    if f["experience_years"] == "":
        return PASS
    if f["experience_strength"] == "preferred":
        return FLAG  # the guide flags any preferred years: the wording leaves room either way
    return SKIP if float(f["experience_years"]) > MAX_REQUIRED_YEARS else PASS


def graduation(f, profile):
    # Never SKIP: an applicant outside the window may still apply, so show it with the reason.
    grad = profile.graduation_date.strftime("%Y-%m")
    start, end = f["grad_start"] or "0000-00", f["grad_end"] or "9999-99"
    return PASS if start <= grad <= end else FLAG


def location(f, profile):
    if not f["locations"].strip():
        return FLAG  # decision 3's exception: usually a page that didn't load fully
    if f["remote"] == "true" and any(p.strip().lower() == "remote" for p in profile.locations):
        return PASS
    if location_matches(f["locations"], profile.locations):
        return PASS
    if f["track"] == "spring_coop" and is_us_location(f["locations"]):
        return PASS  # spring co-ops accept any US location
    return SKIP


RULES = {
    "role_type": role_type,
    "track": track,
    "degree": degree,
    "role_level": role_level,
    "experience": experience,
    "graduation": graduation,
    "location": location,
}
