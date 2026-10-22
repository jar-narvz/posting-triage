"""The labeling guide's verdict policy for profile.example.yaml, written independently
of posting_triage.synthetic, so tests can check the benchmark's answer key against it."""

PASS, FLAG, SKIP = "pass", "flag", "skip"

PROFILE_TRACKS = {"new_grad", "summer_2027", "spring_coop"}
TARGET_ROLES = {"swe", "ml_ai", "data_engineer", "frontend_fullstack"}
MATCHING_PLACES = {"San Francisco, CA", "San Jose, CA", "Los Angeles, CA", "Remote (US)"}
RULE_ORDER = ["role_type", "track", "degree", "role_level", "experience", "graduation", "location"]


def policy_effect(slot, v):
    """Pass / flag / skip for one field. `v` holds that field's values, plus
    "track" when judging location (spring co-ops accept any US location)."""
    if slot == "role_type":
        return FLAG if v["role_type"] == "ambiguous" else PASS if v["role_type"] in TARGET_ROLES else SKIP
    if slot == "track":
        return PASS if v["track"] in PROFILE_TRACKS else SKIP
    if slot == "degree":
        above = v["degree"] in ("masters", "phd")
        return (SKIP if v["degree_strength"] == "required" else FLAG) if above else PASS
    if slot == "role_level":
        return {"mid": SKIP, "senior": SKIP, "unclear": FLAG}.get(v["role_level"], PASS)
    if slot == "experience":
        if v["experience_years"] == "":
            return PASS
        if v["experience_strength"] == "preferred":
            return FLAG
        return SKIP if float(v["experience_years"]) > 1 else PASS
    if slot == "graduation":
        start, end = v["grad_start"] or "0000-00", v["grad_end"] or "9999-99"
        return PASS if start <= "2027-05" <= end else FLAG
    if slot == "location":
        if v["locations"] == "":
            return FLAG
        places = {p.strip() for p in v["locations"].split(";")}
        if places & MATCHING_PLACES or v["remote"] == "true":
            return PASS
        if v.get("track") == "spring_coop" and not any(p.endswith("Canada") for p in places):
            return PASS
        return SKIP
    raise AssertionError(slot)


def policy_verdict(gold):
    """(verdict, deciding field) for a full set of gold values: the first rule that fires."""
    for slot in RULE_ORDER:
        outcome = policy_effect(slot, gold)
        if outcome != PASS:
            return outcome, slot
    return "apply", ""
