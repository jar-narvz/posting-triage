"""Stage 2: the LLM fills the eligibility-field schema, each value with its quotes.
Quotes are checked against the posting text; a missing quote gets one retry.

This module holds the schema the LLM must fill, the conversion of its answer into
the labels.csv format the rules read, the quote check (decision 2), and the prompt.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from posting_triage.rules import decide

Strength = Literal["required", "preferred"] | None


class Part(BaseModel):
    # Structured outputs need every property listed and nothing extra allowed.
    model_config = ConfigDict(extra="forbid")


class RoleType(Part):
    value: Literal["swe", "ml_ai", "data_engineer", "data_scientist", "frontend_fullstack", "other", "ambiguous"]
    quotes: list[str]  # exact passages; several when the evidence is in separate places


class Track(Part):
    value: Literal["new_grad", "summer_2027", "spring_coop", "other"] | None
    quotes: list[str]  # exact passages; several when the evidence is in separate places


class RoleLevel(Part):
    value: Literal["intern", "new_grad", "entry", "mid", "senior", "unclear"]
    quotes: list[str]  # exact passages; several when the evidence is in separate places


class Degree(Part):
    value: Literal["none", "bachelors", "masters", "phd"] | None
    strength: Strength
    quotes: list[str]  # exact passages; several when the evidence is in separate places


class Experience(Part):
    years: float | None
    strength: Strength
    quotes: list[str]  # exact passages; several when the evidence is in separate places


class Graduation(Part):
    start: str | None  # YYYY-MM
    end: str | None
    quotes: list[str]  # exact passages; several when the evidence is in separate places


class Location(Part):
    places: list[str]
    remote: bool
    quotes: list[str]  # exact passages; several when the evidence is in separate places


class Extraction(Part):
    """One entry per verdict rule, named as in rules.RULE_ORDER."""
    role_type: RoleType
    track: Track
    degree: Degree
    role_level: RoleLevel
    experience: Experience
    graduation: Graduation
    location: Location


def json_schema():
    """The schema for output_config.format."""
    return Extraction.model_json_schema()


def to_fields(e):
    """The labels.csv form of an extraction: strings, "" for silent, as rules.decide reads them."""
    has_degree = e.degree.value not in (None, "none")
    return {
        "role_type": e.role_type.value,
        "track": e.track.value or "",
        "degree": e.degree.value or "",
        "degree_strength": (e.degree.strength or "required") if has_degree else "",
        "role_level": e.role_level.value,
        "experience_years": "" if e.experience.years is None else f"{e.experience.years:g}",
        "experience_strength": "" if e.experience.years is None else e.experience.strength or "required",
        "grad_start": e.graduation.start or "",
        "grad_end": e.graduation.end or "",
        "locations": "; ".join(p.strip() for p in e.location.places if p.strip()),
        "remote": "true" if e.location.remote else "false",
    }


def to_quotes(e):
    """Field name -> its quotes joined into one reason line, or None if silent."""
    joined = {name: "; ".join(q.strip() for q in getattr(e, name).quotes if q.strip())
              for name in Extraction.model_fields}
    return {name: text or None for name, text in joined.items()}


# ---------------------------------------------------------------------------
# Quote check (decision 2)

QUOTE_MARKS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def normalize(text):
    """Collapse whitespace and treat curly and straight quotes alike; nothing looser."""
    return " ".join(text.translate(QUOTE_MARKS).split())


def problems(e, text):
    """Field name -> what's wrong with it. Empty means every value traces to the posting.
    These fields get one retry; any still listed after it make the verdict FLAG."""
    haystack = normalize(text)
    found = {}
    fields = to_fields(e)
    stated = {
        "role_type": True,
        "track": bool(fields["track"]),
        "degree": bool(fields["degree"]),
        "role_level": True,
        "experience": bool(fields["experience_years"]),
        "graduation": bool(fields["grad_start"] or fields["grad_end"]),
        "location": bool(fields["locations"]) or e.location.remote,
    }
    for name in Extraction.model_fields:
        # "" is in every text, so blank quotes count as none.
        quotes = [q for q in (normalize(q) for q in getattr(e, name).quotes) if q]
        missing = [q for q in quotes if q not in haystack]
        if missing:
            found[name] = "quote not found in the posting: " + ", ".join(repr(q) for q in missing)
        elif not quotes and stated[name]:
            found[name] = "has a value but no quote"
    for month in (e.graduation.start, e.graduation.end):
        if month is not None and not MONTH.fullmatch(month):
            found["graduation"] = f"month must be YYYY-MM, got {month!r}"
    return found


# ---------------------------------------------------------------------------
# Prompt and requests

# The labeling guide's field definitions, restated for a reader. It never sees the
# profile (the rules apply that) or the synthetic phrase library (that's the answer key).
INTRO = """\
You read one job posting and fill in a form about who can apply. You do not judge whether anyone should apply.

For every field, give the value and the exact words from the posting it came from:
- `quotes` is a list of passages, each copied character for character from the posting text: no paraphrase, no ellipses, no added words. The shortest passages that show the value are best.
- Use more than one passage only when the value comes from separate places in the posting, e.g. a degree in the minimum qualifications and a higher one in the preferred qualifications, or locations listed in two places.
- If the posting never mentions a field, set its value to null and its quotes to an empty list. Do not guess.
- If the posting mentions it but the wording could go either way, give the value and mark it "preferred" (or "unclear" for role level).

"""

# Shared with the direct-verdict prompt, so both approaches read postings by the same definitions.
FIELD_GUIDE = """\
Fields:

role_type (decide from the title first, then the description)
- swe: backend, infrastructure, systems, mobile, embedded, SRE, "Software Engineer". If the main job is writing software, it is swe whatever the title says.
- ml_ai: ML engineering, applied AI, model training or serving, LLM work.
- data_engineer: pipelines, ETL, warehouses, Spark/Airflow.
- data_scientist: statistics, experimentation, analytics, or a "Data Scientist" title.
- frontend_fullstack: frontend, full-stack, web.
- other: software isn't the core of the job (PM, hardware, IT support, BI dashboards, QA-only, non-engineering research).
- ambiguous: the role genuinely splits between two of the types above, e.g. half data pipelines, half data science.

track
- new_grad: "New Grad", "University Grad", "2027 start", or any full-time entry-level role with no term named. For a full-time role with no term, quote the title.
- summer_2027: a Summer 2027 internship, or an internship with no term named.
- spring_coop: a Spring 2027 co-op.
- other: fall or winter terms, part-time co-ops, any other term.
- If several terms are listed, pick one of new_grad, summer_2027, or spring_coop when any of them applies ("Summer or Fall 2027" is summer_2027).

degree: the highest degree the posting asks for, and whether it is required or only preferred.
- "BS/MS", "Bachelor's or Master's", or "currently pursuing a Bachelor's, Master's, or PhD": bachelors, required (a lower degree is enough).
- "BS required, MS preferred": masters, preferred.
- "MS or PhD required": masters, required.
- "or equivalent practical experience": none.
- Nothing about degrees: null.
- "Graduate" in a title such as "Software Engineer Graduate" names a new-grad program, not a degree. A title ending "- PhD" is a degree requirement.

role_level
- intern: "Intern", "Internship", "Co-op".
- new_grad: "New Grad", "University Grad", "Graduate", "College Grad", "Early Career".
- entry: "Engineer I", "Engineer 1", "Junior", "Associate", "Entry Level".
- mid: "II", "III", "L4", "Mid-level".
- senior: "Senior", "Sr.", "Staff", "Principal", "Lead" as a level. A word like "Senior" inside a team or product name is not a level.
- When several levels are listed ("I/II", "New Grad or Experienced"), give the lowest.
- unclear: no level words, and the description doesn't settle it. Quote the passage that leaves it open, or the title.

experience: the minimum years asked for.
- "0-2 years" is 0, "1+ years" is 1, "6 months" is 0.5.
- preferred: "preferred", "nice to have", "a plus", "ideally", "bonus", or anything listed under preferred qualifications. required: "required", "must have", "minimum", or a plain statement in a requirements list.
- Prior internships or projects are not years: null.

graduation: the graduation window, as start and end months in YYYY-MM form. Leave an open end null.
- "between Dec 2026 and Aug 2027": start 2026-12, end 2027-08.
- "must graduate by June 2027": start null, end 2027-06.
- "graduating in 2027": start 2027-01, end 2027-12.
- A single month or year date: that month (or that year's January to December) as both start and end.
- A Summer 2027 internship that requires returning to school afterwards: start 2027-09, end null.
- Nothing about graduation: both null.

location
- places: every location listed, as written. An empty list if none is listed.
- remote: true only if fully remote work is allowed ("Remote", "Remote (US)", "remote-first"). Hybrid is false.
"""
SYSTEM = INTRO + FIELD_GUIDE


def user_message(text, retry_note=None):
    content = f"<posting>\n{text}\n</posting>"
    if retry_note:
        content += "\n\n" + retry_note
    return {"role": "user", "content": content}


def request_params(text, model, effort="medium", retry_note=None):
    """Keyword arguments for client.messages.create, or a batch request's params."""
    return {
        "model": model,
        "max_tokens": 16000,
        # The instructions are the same for every posting, so cache them.
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [user_message(text, retry_note)],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": json_schema()}},
    }


def retry_note(found):
    """What to tell the model on its one retry: which fields failed and why."""
    lines = [f"- {name}: {problem}" for name, problem in found.items()]
    return ("A previous reading of this posting had these problems:\n" + "\n".join(lines) +
            "\nFill in the whole form again. Every quote must be copied exactly from the posting above.")


class ExtractionError(Exception):
    """The model returned no usable form (a refusal, or output cut off)."""


def response_text(message):
    """The JSON text of a structured-output response, or ExtractionError."""
    if message.stop_reason != "end_turn":
        raise ExtractionError(f"stop_reason {message.stop_reason}")
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise ExtractionError("no text in the response")
    return text


def parse(message):
    """The Extraction in a response, or ExtractionError."""
    return Extraction.model_validate_json(response_text(message))


def extract(text, call, model, effort="medium"):
    """(extraction or None, problems) after at most one retry. `call` sends one
    request's params and returns the response, e.g. client.messages.create."""
    found = {}
    for attempt in range(2):
        note = retry_note(found) if attempt else None
        try:
            e = parse(call(**request_params(text, model, effort, note)))
        except (ExtractionError, ValueError) as err:  # pydantic's ValidationError is a ValueError
            e, found = None, {"form": str(err)}
            continue
        found = problems(e, text)
        if not found:
            break
    return e, found


def pipeline_verdict(text, profile, call, model, effort="medium"):
    """The tool's answer for one posting: extract, check quotes, apply the rules."""
    e, found = extract(text, call, model, effort)
    if e is None:
        return decide({}, profile, unverified={"form"})
    return decide(to_fields(e), profile, to_quotes(e), unverified=set(found))
