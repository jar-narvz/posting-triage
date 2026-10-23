"""Stage 3: turn extracted fields + the profile into a verdict. Pure functions, no I/O.

Fields come in the labels.csv format (strings, "" when the posting is silent), so the
same code judges gold labels and LLM extractions. Every rule runs; any SKIP beats any
FLAG, and the deciding field is the first rule, in the labeling guide's order, that gave
the winning outcome. The order picks the reason shown, never the verdict. Liveness
(rule 1) happens before this stage.
"""

from dataclasses import dataclass

from posting_triage.candidates import is_us_location
from posting_triage.profile import location_matches

APPLY, FLAG, SKIP = "apply", "flag", "skip"
PASS = None
RULE_ORDER = ["role_type", "track", "degree", "role_level", "experience", "graduation", "location"]
DEGREE_RANK = {"none": 0, "bachelors": 1, "masters": 2, "phd": 3}
MAX_REQUIRED_YEARS = 1  # "1+ years required" is fine for a new grad; more is a SKIP
# Fields a rule reads besides its own: location's spring co-op exception reads the track.
ALSO_READS = {"location": {"track"}}


@dataclass(frozen=True)
class Verdict:
    verdict: str
    field: str  # the deciding field; "" for APPLY
    quote: str | None  # the posting's words behind it, when there are any


def decide(fields, profile, quotes=None, unverified=()):
    """`quotes` maps a rule's field to the text it came from; `unverified` lists
    fields whose quote wasn't found in the posting even after a retry."""
    quotes, unverified = quotes or {}, set(unverified)
    if "form" in unverified:  # no usable extraction at all
        return Verdict(FLAG, "quote", None)
    # Rule 2: a value we can't trace to the posting can't decide anything, so any rule that
    # reads one is set aside. A verified SKIP still stands; otherwise the posting is FLAG.
    outcomes = {f: RULES[f](fields, profile) for f in RULE_ORDER
                if not ({f} | ALSO_READS.get(f, set())) & unverified}
    skips = [f for f, o in outcomes.items() if o is SKIP]
    if skips:
        return Verdict(SKIP, skips[0], quotes.get(skips[0]))
    if unverified:
        first = next((f for f in RULE_ORDER if f in unverified), None)
        return Verdict(FLAG, "quote", quotes.get(first))
    flags = [f for f, o in outcomes.items() if o is FLAG]
    if flags:
        return Verdict(FLAG, flags[0], quotes.get(flags[0]))
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
