"""Synthetic benchmark: postings whose correct answers are known by construction.

Every phrase here carries its true field values and its effect under
profile.example.yaml (pass, flag, or skip). A posting is built from a target
verdict and deciding field, choosing phrases that make exactly that rule fire,
so its gold answers never come from the rules module. See docs/design.md.
"""

import random
from collections import Counter
from dataclasses import dataclass, field

PASS, FLAG, SKIP = "pass", "flag", "skip"
INTERN, FULLTIME = "intern", "fulltime"


@dataclass(frozen=True)
class Phrase:
    """One piece of posting text and what it means.

    text:   inserted verbatim; it is also the gold quote for its fields.
            "{role}" is filled with the role phrase for title patterns.
    values: the gold field values this phrase sets (labels.csv column names).
    effect: pass / flag / skip under profile.example.yaml.
    kinds:  which postings it fits (internships, full-time roles, or both).
    hard:   a short tag if the keyword baseline or a careless reader gets it wrong.
    """

    text: str
    values: dict
    effect: str
    kinds: tuple = (INTERN, FULLTIME)
    hard: str = ""
    duties: tuple = field(default=(), compare=False)


def P(text, effect, kinds=(INTERN, FULLTIME), hard="", duties=(), **values):
    return Phrase(text, values, effect, tuple(kinds), hard, tuple(duties))


SWE_DUTIES = (
    "Design, build, and ship backend services used by millions of people.",
    "Write well-tested code and take part in code reviews.",
    "Debug production issues alongside senior engineers.",
)
ML_DUTIES = (
    "Train and evaluate machine learning models on large datasets.",
    "Deploy models to production and monitor their quality.",
    "Work with researchers to turn prototypes into reliable systems.",
)
DATA_ENG_DUTIES = (
    "Build and maintain batch and streaming data pipelines.",
    "Model data in our warehouse so other teams can trust it.",
    "Improve the reliability and cost of our Spark and Airflow jobs.",
)
FULLSTACK_DUTIES = (
    "Build user-facing features end to end, from React components to APIs.",
    "Work closely with designers to polish the product experience.",
    "Own features from design review through launch.",
)
DS_DUTIES = (
    "Design and analyze A/B tests to guide product decisions.",
    "Build statistical models and dashboards for business stakeholders.",
    "Present findings to leadership.",
)
HARDWARE_DUTIES = (
    "Design and test RF circuits for our flight hardware.",
    "Run bench tests and debug boards in the lab.",
    "Write test plans for hardware bring-up.",
)
MIXED_DUTIES = (
    "Split your time between building data pipelines and training forecasting models.",
    "Partner with our data science team on experiments and analysis.",
    "Ship models and the pipelines that feed them.",
)

# Rule 3a: role type. Used in the title, so the title alone decides it.
ROLE = [
    P("Software Engineer", PASS, role_type="swe", duties=SWE_DUTIES),
    P("Backend Engineer", PASS, role_type="swe", duties=SWE_DUTIES),
    P("Machine Learning Engineer", PASS, role_type="ml_ai", duties=ML_DUTIES),
    P("Data Engineer", PASS, role_type="data_engineer", duties=DATA_ENG_DUTIES),
    P("Full-Stack Engineer", PASS, role_type="frontend_fullstack", duties=FULLSTACK_DUTIES),
    P("Technology Analyst, Software Engineering", PASS, hard="off-target-sounding swe title",
      role_type="swe", duties=SWE_DUTIES),
    P("Data & ML Engineer", FLAG, hard="ambiguous role type",
      role_type="ambiguous", duties=MIXED_DUTIES),
    P("Data Scientist", SKIP, role_type="data_scientist", duties=DS_DUTIES),
    P("Hardware Engineer", SKIP, role_type="other", duties=HARDWARE_DUTIES),
]

# Rule 5: role level. Title patterns; the level decides internship vs full-time.
LEVEL = [
    P("{role} Intern", PASS, [INTERN], role_level="intern"),
    P("{role}, New Grad", PASS, [FULLTIME], role_level="new_grad"),
    P("{role} Graduate", PASS, [FULLTIME], hard="Graduate in a bachelor's-level title", role_level="new_grad"),
    P("{role}, New Grad (Senior Living Platform)", PASS, [FULLTIME], hard="Senior as a team name, not a level",
      role_level="new_grad"),
    P("{role} I", PASS, [FULLTIME], role_level="entry"),
    P("Junior {role}", PASS, [FULLTIME], role_level="entry"),
    P("{role} I/II", PASS, [FULLTIME], hard="mixed levels I/II", role_level="entry"),
    P("{role}", FLAG, [FULLTIME], role_level="unclear"),
    P("Senior {role}", SKIP, [FULLTIME], role_level="senior"),
    P("Staff {role}", SKIP, [FULLTIME], role_level="senior"),
    P("{role} II", SKIP, [FULLTIME], role_level="mid"),
]
# The sentence that makes a level-less title genuinely unclear.
UNCLEAR_LEVEL_TEXT = "We're open to candidates at a range of experience levels, from recent graduates to experienced engineers."

# Rule 3b: track, as a suffix on the title.
TRACK = [
    P(" - Summer 2027", PASS, [INTERN], track="summer_2027"),
    P(" - Spring 2027 Co-op", PASS, [INTERN], track="spring_coop"),
    P(" - Summer or Fall 2027", PASS, [INTERN], hard="several terms, one matches", track="summer_2027"),
    P(" - Fall 2026", SKIP, [INTERN], track="other"),
    P(" - Winter 2027", SKIP, [INTERN], track="other"),
    P(" - 2027 Start", PASS, [FULLTIME], track="new_grad"),
    P("", PASS, [FULLTIME], track="new_grad"),
]

# Rule 4: degree. A requirements bullet, or nothing (silent).
DEGREE = [
    P("", PASS, degree="", degree_strength=""),
    P("Bachelor's degree in Computer Science or a related field", PASS, degree="bachelors", degree_strength="required"),
    P("BS/MS in Computer Science, Engineering, or a related field", PASS, hard="BS/MS means a BS is enough",
      degree="bachelors", degree_strength="required"),
    P("Currently pursuing a Bachelor's or Master's degree in Computer Science", PASS, [INTERN],
      degree="bachelors", degree_strength="required"),
    P("Bachelor's degree or equivalent practical experience", PASS, hard="equivalent experience accepted",
      degree="none", degree_strength=""),
    P("Master's degree in Computer Science preferred", FLAG, hard="higher degree only preferred",
      degree="masters", degree_strength="preferred"),
    P("BS required; MS or PhD preferred", FLAG, hard="higher degree only preferred",
      degree="masters", degree_strength="preferred"),
    P("PhD in Computer Science or a related field required", SKIP, degree="phd", degree_strength="required"),
    P("Currently pursuing a Master's or PhD degree", SKIP, [INTERN], degree="masters", degree_strength="required"),
    P("Master's degree in Computer Science, Statistics, or a related field required", SKIP,
      degree="masters", degree_strength="required"),
]

# Rule 6: experience. Only full-time roles ask for years.
EXPERIENCE = [
    P("", PASS, experience_years="", experience_strength=""),
    P("0-1 years of professional software development experience", PASS, [FULLTIME],
      experience_years="0", experience_strength="required"),
    P("1+ years of experience writing production code", PASS, [FULLTIME],
      experience_years="1", experience_strength="required"),
    P("2+ years of professional experience preferred", FLAG, [FULLTIME], hard="years preferred, not required",
      experience_years="2", experience_strength="preferred"),
    P("Ideally 3+ years of industry experience", FLAG, [FULLTIME], hard="years preferred, not required",
      experience_years="3", experience_strength="preferred"),
    P("3+ years of professional software development experience", SKIP, [FULLTIME],
      experience_years="3", experience_strength="required"),
    P("5+ years of experience building distributed systems", SKIP, [FULLTIME],
      experience_years="5", experience_strength="required"),
]

# Rule 7: graduation window. Never SKIP: a mismatch is a FLAG.
GRADUATION = [
    P("", PASS, grad_start="", grad_end=""),
    P("Expected graduation between December 2026 and August 2027", PASS, grad_start="2026-12", grad_end="2027-08"),
    P("Must graduate by June 2027", PASS, grad_start="", grad_end="2027-06"),
    P("Expected graduation between December 2027 and June 2028", FLAG, grad_start="2027-12", grad_end="2028-06"),
    P("Must be returning to school after the internship", FLAG, [INTERN], hard="internship requires returning to school",
      grad_start="2027-09", grad_end=""),
    P("Must have graduated by December 2026", FLAG, [FULLTIME], grad_start="", grad_end="2026-12"),
]

# Rule 8: location. Shown as "Location: ..." under the title; "" means none listed.
# US locations outside Bay Area / LA pass only on the spring co-op track.
LOCATION = [
    P("San Francisco, CA", PASS, locations="San Francisco, CA", remote="false"),
    P("San Jose, CA", PASS, locations="San Jose, CA", remote="false"),
    P("Los Angeles, CA", PASS, locations="Los Angeles, CA", remote="false"),
    P("Remote (US)", PASS, locations="Remote (US)", remote="true"),
    P("Seattle, WA; San Jose, CA", PASS, hard="several locations, one matches",
      locations="Seattle, WA; San Jose, CA", remote="false"),
    P("", FLAG, locations="", remote="false"),
    P("Seattle, WA", SKIP, locations="Seattle, WA", remote="false"),
    P("New York, NY", SKIP, locations="New York, NY", remote="false"),
    P("Boston, MA", SKIP, locations="Boston, MA", remote="false"),
    P("Toronto, ON, Canada", SKIP, locations="Toronto, ON, Canada", remote="false"),
]
# Locations that pass anyway for a spring co-op (any US location).
US_LOCATIONS = {"Seattle, WA", "New York, NY", "Boston, MA"}

# The slots in verdict-rule order. A posting's verdict is decided by the first
# slot whose phrase doesn't pass; same order as docs/labeling-guide.md.
SLOTS = [
    ("role_type", ROLE),
    ("track", TRACK),
    ("degree", DEGREE),
    ("role_level", LEVEL),
    ("experience", EXPERIENCE),
    ("graduation", GRADUATION),
    ("location", LOCATION),
]
# Which slots share a verdict rule (rule 3 covers both role type and track).
RULE_OF = {"role_type": 3, "track": 3, "degree": 4, "role_level": 5, "experience": 6, "graduation": 7, "location": 8}


def effect(slot, phrase, chosen):
    """A phrase's effect, given the phrases already chosen for this posting.
    Only location depends on anything else: a spring co-op accepts any US location."""
    if slot == "location" and phrase.text in US_LOCATIONS and chosen["track"].values["track"] == "spring_coop":
        return PASS
    return phrase.effect


# ---------------------------------------------------------------------------
# Generator


COMPANY_FIRST = ["Northwind", "Bluefin", "Cedar", "Harbor", "Quill", "Lumen", "Juniper", "Kestrel",
                 "Meridian", "Orchid", "Pinecrest", "Riverbend", "Solstice", "Tidewater", "Vantage", "Willow"]
COMPANY_SECOND = ["Labs", "Systems", "Health", "Robotics", "Analytics", "Software", "Networks", "Cloud"]
NAV = ["Careers", "Teams", "Locations", "Students", "Search jobs", "Sign in", "Life at work", "Blog"]
BLURBS = [
    "We build tools that help small businesses run their operations from a single place.",
    "Our platform helps hospitals coordinate care across teams and devices.",
    "We make infrastructure software that thousands of engineering teams rely on every day.",
    "We're a fast-growing startup building the data layer for modern logistics.",
]
RESPONSIBILITY_HEADERS = ["What you'll do", "Responsibilities", "The role", "In this role, you will"]
QUALIFICATION_HEADERS = ["Minimum Qualifications", "What you'll need", "Requirements", "Qualifications", "Who you are"]
SKILLS = [
    "Strong programming skills in Python, Java, or C++",
    "Solid understanding of data structures and algorithms",
    "Clear written and verbal communication",
    "Experience with Git and collaborative development",
    "Familiarity with cloud platforms such as AWS or GCP",
]
BENEFITS = ["Benefits", "- Medical, dental, and vision coverage", "- Paid time off and parental leave",
            "We are an equal opportunity employer."]

# Share of postings per verdict; FLAG and SKIP are spread evenly over the fields that can cause them.
VERDICT_SHARE = {"apply": 0.35, "flag": 0.30, "skip": 0.35}
DECIDERS = {
    "flag": [slot for slot, phrases in SLOTS if any(p.effect == FLAG for p in phrases)],
    "skip": [slot for slot, phrases in SLOTS if any(p.effect == SKIP for p in phrases)],
}
# Per-slot chance of a hard-case phrase; about half of postings end up with one. Titles get more,
# since title tricks (Graduate, I/II, Senior as a team name) are what the keyword baseline misreads.
HARD_PICK = {"role_level": 0.35}
HARD_PICK_DEFAULT = 0.12


def plan_scenarios(n):
    """(verdict, deciding_field) for n postings: the verdict shares above,
    split evenly across deciding fields, leftovers to the first fields."""
    counts = {v: round(n * share) for v, share in VERDICT_SHARE.items()}
    counts["apply"] += n - sum(counts.values())
    scenarios = [("apply", "")] * counts["apply"]
    for verdict in ("flag", "skip"):
        fields = DECIDERS[verdict]
        for i in range(counts[verdict]):
            scenarios.append((verdict, fields[i % len(fields)]))
    return scenarios


def wanted_effects(slot, verdict, deciding):
    """Which effects a slot's phrase may have so that `deciding` is the first rule to fire."""
    if verdict == "apply":
        return {PASS}
    order = [s for s, _ in SLOTS]
    if order.index(slot) < order.index(deciding):
        return {PASS}
    if slot == deciding:
        return {verdict}
    if RULE_OF[slot] == RULE_OF[deciding]:
        return {PASS}  # e.g. role type FLAG with a skipping track would make rule 3 ambiguous
    return {PASS, FLAG, SKIP}  # after the deciding rule: anything, it can't change the verdict


def least_used(rng, phrases, used):
    """A random one of the hard phrases whose tag the benchmark has used least so far, so
    every hard case gets enough postings for its accuracy row to mean something."""
    fewest = min(used[p.hard] for p in phrases)
    return rng.choice([p for p in phrases if used[p.hard] == fewest])


def pick_phrases(rng, kind, verdict, deciding, used):
    """One phrase per slot for this scenario, or None if this kind can't produce it.
    `used` counts the hard-case tags in the postings built so far."""
    chosen = {}
    for slot, phrases in SLOTS:
        wanted = wanted_effects(slot, verdict, deciding)
        fits = [p for p in phrases if kind in p.kinds and effect(slot, p, chosen) in wanted]
        if not fits:
            return None
        hard = [p for p in fits if p.hard]
        easy = [p for p in fits if not p.hard]
        # Hard phrases only when the dice say so, or when nothing else fits (e.g. "Data & ML" for a role-type FLAG).
        chosen[slot] = least_used(rng, hard, used) if hard and (not easy or rng.random() < HARD_PICK.get(slot, HARD_PICK_DEFAULT)) else rng.choice(easy)
    return chosen


def build_posting(rng, index, verdict, deciding, used):
    kinds = [INTERN, FULLTIME]
    rng.shuffle(kinds)
    for kind in kinds:
        chosen = pick_phrases(rng, kind, verdict, deciding, used)
        if chosen:
            break
    else:
        raise ValueError(f"no phrases can make {deciding} decide {verdict}")

    role, level, track = chosen["role_type"], chosen["role_level"], chosen["track"]
    title = level.text.format(role=role.text) + track.text
    location = chosen["location"].text
    company = f"{rng.choice(COMPANY_FIRST)} {rng.choice(COMPANY_SECOND)}"
    unclear = level.values["role_level"] == "unclear"

    requirements = [chosen[s].text for s in ("degree", "experience", "graduation") if chosen[s].text]
    requirements += rng.sample(SKILLS, 2)
    rng.shuffle(requirements)
    lines = rng.sample(NAV, rng.randint(3, 6)) + [title]
    if location:
        lines.append(f"Location: {location}")
    lines += [f"About {company}", rng.choice(BLURBS), rng.choice(RESPONSIBILITY_HEADERS)]
    lines += [f"- {duty}" for duty in role.duties]
    if unclear:
        lines.append(UNCLEAR_LEVEL_TEXT)
    lines.append(rng.choice(QUALIFICATION_HEADERS))
    lines += [f"- {r}" for r in requirements]
    lines += BENEFITS

    gold = {}
    for phrase in chosen.values():
        gold.update(phrase.values)
    quotes = {
        "role_type": role.text,
        "role_level": UNCLEAR_LEVEL_TEXT if unclear else level.text.format(role=role.text),
        "track": track.text.removeprefix(" - ") or None,
        **{slot: chosen[slot].text or None for slot in ("degree", "experience", "graduation", "location")},
    }
    hard = [p.hard for p in chosen.values() if p.hard]
    if chosen["track"].values["track"] == "spring_coop" and location in US_LOCATIONS:
        hard.append("spring co-op outside Bay Area / LA")
    return {
        "id": f"syn-{index:03d}",
        "title": title,
        "company": company,
        "location": location,
        "kind": kind,
        "text": "\n".join(lines),
        "gold_verdict": verdict,
        "deciding_field": deciding,
        "gold": gold,
        "quotes": quotes,
        "hard": hard,
    }


def generate(n=200, seed=2027):
    """n postings with known answers. Same n and seed, same postings."""
    rng = random.Random(seed)
    scenarios = plan_scenarios(n)
    rng.shuffle(scenarios)
    used, postings = Counter(), []
    for i, (verdict, deciding) in enumerate(scenarios, 1):
        postings.append(build_posting(rng, i, verdict, deciding, used))
        used.update(postings[-1]["hard"])
    return postings
