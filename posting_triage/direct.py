""""LLM decides" comparison prompt. Used only by the eval.

The model gets everything the pipeline uses (the same field definitions, the profile,
and the verdict rules in order) and returns the verdict itself. Comparing it with the
pipeline shows whether splitting reading from deciding (decision 1) was worth it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from posting_triage.extract import FIELD_GUIDE, ExtractionError, response_text, user_message
from posting_triage.rules import MAX_REQUIRED_YEARS, Verdict

INTRO = """\
You decide whether one applicant should apply to one job posting. Answer apply, flag, or skip:
- apply: nothing in the posting rules the applicant out.
- skip: the posting clearly rules the applicant out.
- flag: the posting might rule them out, but the wording leaves room, so a person should look.

Walk the rules below in order. The first rule that gives flag or skip is the answer, and its field is the deciding field. Give the exact words from the posting behind it, copied character for character; use several passages only when the evidence is in separate places. For apply, the deciding field is "none" and there are no quotes.

A field the posting never mentions puts no limit on the applicant, except location: a posting that lists no location at all is flag.

"""

RULES = """\
Rules, in order:
1. role_type: ambiguous is flag. A role type the applicant excludes, or one that isn't among their target role types (other included), is skip.
2. track: a track that isn't among the applicant's tracks is skip.
3. degree: a degree above the applicant's is skip if required, flag if only preferred.
4. role_level: mid or senior is skip; unclear is flag.
5. experience: any years that are only preferred is flag. More than {max_years} year required is skip.
6. graduation: a window that doesn't include the applicant's graduation month is flag (never skip).
7. location: no location listed is flag. Otherwise it passes if any listed place is in one of the applicant's locations (Bay Area means the nine-county San Francisco Bay Area; Los Angeles means Los Angeles County, not Orange County), or if the role is fully remote and the applicant accepts Remote, or if the track is spring_coop and any listed place is in the US. Anything else is skip.
8. Nothing above fired: apply.
"""


def profile_text(profile):
    return (
        "The applicant:\n"
        f"- degree: {profile.degree}, graduating {profile.graduation_date:%Y-%m}\n"
        f"- locations: {', '.join(profile.locations)}\n"
        f"- tracks: {', '.join(profile.tracks)}\n"
        f"- target role types: {', '.join(profile.target_role_types)}\n"
        f"- excluded role types: {', '.join(profile.excluded_role_types) or 'none'}\n"
    )


def system(profile):
    return INTRO + profile_text(profile) + "\n" + RULES.format(max_years=MAX_REQUIRED_YEARS) + "\n" + FIELD_GUIDE


class DirectAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["apply", "flag", "skip"]
    deciding_field: Literal["role_type", "track", "degree", "role_level", "experience", "graduation", "location",
                            "none"]
    quotes: list[str]


def request_params(text, profile, model, effort="medium"):
    """Keyword arguments for client.messages.create, or a batch request's params."""
    return {
        "model": model,
        "max_tokens": 16000,
        "system": [{"type": "text", "text": system(profile), "cache_control": {"type": "ephemeral"}}],
        "messages": [user_message(text)],
        "output_config": {"effort": effort,
                          "format": {"type": "json_schema", "schema": DirectAnswer.model_json_schema()}},
    }


def parse(message):
    """The answer as a rules.Verdict. Its quotes aren't checked: this is the comparison, not the tool."""
    a = DirectAnswer.model_validate_json(response_text(message))
    if a.verdict == "apply":
        return Verdict("apply", "", None)
    field = "" if a.deciding_field == "none" else a.deciding_field
    return Verdict(a.verdict, field, "; ".join(q.strip() for q in a.quotes if q.strip()) or None)


def direct_verdict(text, profile, call, model, effort="medium"):
    """One request, no retry. No usable answer counts as FLAG, as it does for the pipeline."""
    try:
        return parse(call(**request_params(text, profile, model, effort)))
    except (ExtractionError, ValueError):
        return Verdict("flag", "quote", None)
