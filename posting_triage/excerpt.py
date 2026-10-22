"""Pull the eligibility-relevant lines out of a posting so labeling doesn't mean
reading a whole careers page: the requirements section(s), plus any other line
that mentions a degree, years, graduation, or where the job is."""

import re

# Short lines that start a requirements-style section.
SECTION_HEADER = re.compile(
    r"^(minimum|basic|preferred|required|desired|key|additional)?\s*"
    r"(qualifications?|requirements?)\b"
    r"|^what (we|you)('ll| will)? (need|need to see|bring|look for|are looking for)"
    r"|^what we('re| are) looking for"
    r"|^(who you are|about you|you have|you bring|you might be|you should have|ideal candidate)"
    r"|^education\b",
    re.IGNORECASE,
)
# Lines that end a requirements section: pay, benefits, legal boilerplate.
SECTION_END = re.compile(
    r"^(benefits|perks|compensation|pay|salary|the (base )?(salary|pay)|【?for pay|job information|"
    r"what we offer|why (join|you'll love)|our (benefits|culture|values)|about (us|the (company|team))|"
    r"equal (opportunity|employment)|eeo|for los angeles county|disclaimer|privacy|"
    r"accommodations?|additional information)",
    re.IGNORECASE,
)
# Words that decide a verdict. Matched case-insensitively.
KEY_TERMS = re.compile(
    r"\b(ph\.?\s?d|doctorate|doctoral|master'?s|bachelor'?s|degree|undergraduate|"
    r"\d+\+?\s*(years?|yrs)|years? of|preferred|required|must|minimum|"
    r"graduat\w*|enrolled|pursuing|returning|remote|hybrid|on-?site|in-office|relocat\w*)\b",
    re.IGNORECASE,
)
# Degree abbreviations, matched case-sensitively so "ms" in a word isn't caught.
DEGREE_ABBREV = re.compile(r"\b(BS|BA|MS|MBA|B\.S\.|M\.S\.|B\.A\.)(?=\W|$)")

SECTION_LINES = 18  # how far a requirements section is followed
MAX_LINES = 45
HIGHLIGHT = "\033[1;33m"  # bold yellow
RESET = "\033[0m"


def is_header(line):
    return len(line) <= 70 and bool(SECTION_HEADER.search(line.strip(" :-•*")))


def has_key_term(line):
    return bool(KEY_TERMS.search(line) or DEGREE_ABBREV.search(line))


def excerpt(text, max_lines=MAX_LINES):
    """The lines worth reading, in their original order, with "…" where lines were cut."""
    lines = text.splitlines()
    keep = set()
    for i, line in enumerate(lines):
        if is_header(line):
            keep.add(i)
            for j in range(i + 1, min(i + 1 + SECTION_LINES, len(lines))):
                if SECTION_END.search(lines[j].strip(" :-•*")):
                    break
                keep.add(j)
        elif has_key_term(line):
            keep.add(i)
    if not keep:
        keep = set(range(min(max_lines, len(lines))))

    out, last = [], None
    for i in sorted(keep)[:max_lines]:
        if last is not None and i != last + 1:
            out.append("…")
        out.append(lines[i])
        last = i
    if len(keep) > max_lines:
        out.append(f"… ({len(keep) - max_lines} more relevant lines; press T for the full text)")
    return "\n".join(out)


def highlight(text, color=True):
    """Wrap verdict-deciding words in bold yellow (terminal colors). No-op when color is off."""
    if not color:
        return text
    marked = KEY_TERMS.sub(lambda m: f"{HIGHLIGHT}{m.group(0)}{RESET}", text)
    return DEGREE_ABBREV.sub(lambda m: f"{HIGHLIGHT}{m.group(0)}{RESET}", marked)
