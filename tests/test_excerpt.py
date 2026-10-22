from posting_triage.excerpt import HIGHLIGHT, RESET, excerpt, highlight, is_header

NAV = ["Home", "Teams", "Locations", "Blog", "Sign In", "Privacy Policy"]


def test_keeps_the_requirements_section_and_drops_navigation():
    text = "\n".join(NAV + [
        "About us",
        "We make the best widgets in the world.",
        "Qualifications",
        "Currently pursuing a PhD in Computer Science",
        "Strong C++",
        "Benefits",
        "Free lunch",
    ])
    result = excerpt(text)
    assert "Home" not in result.splitlines()
    assert "We make the best widgets in the world." not in result
    assert "Qualifications\nCurrently pursuing a PhD in Computer Science\nStrong C++" in result


def test_keeps_key_term_lines_outside_sections_with_a_gap_marker():
    text = "\n".join(["Software Engineer I", "Location: Remote (US)"] + NAV + [
        "You'll build APIs.",
        "2+ years of experience preferred",
    ])
    assert excerpt(text).splitlines() == [
        "Location: Remote (US)",
        "…",
        "2+ years of experience preferred",
    ]


def test_falls_back_to_the_top_when_nothing_matches():
    text = "\n".join(f"line {i}" for i in range(100))
    assert excerpt(text, max_lines=3).splitlines() == ["line 0", "line 1", "line 2"]


def test_caps_long_excerpts_and_points_to_the_full_text():
    text = "\n".join(f"{i} years required" for i in range(60))
    lines = excerpt(text, max_lines=5).splitlines()
    assert len(lines) == 6
    assert lines[-1] == "… (55 more relevant lines; press T for the full text)"


def test_recognizes_common_section_headers():
    for header in ("Minimum Qualifications:", "What we need to see:", "Requirements",
                   "What you'll bring", "Who you are", "Preferred Qualifications"):
        assert is_header(header), header
    assert not is_header("Our requirements for success are high and this is a long sentence about culture.")


def test_highlight_marks_deciding_words_only_when_color_is_on():
    line = "BS or MS in CS; 2+ years preferred"
    assert highlight(line, color=False) == line
    marked = highlight(line)
    for word in ("BS", "MS", "2+ years", "preferred"):
        assert f"{HIGHLIGHT}{word}{RESET}" in marked
    assert f"{HIGHLIGHT}CS" not in marked


def test_section_stops_at_pay_and_benefits_boilerplate():
    text = "\n".join([
        "Minimum Qualifications:",
        "- Bachelor's degree in CS",
        "Job Information",
        "The base salary range for this position is $100,000.",
        "Benefits",
        "Medical, dental, vision.",
    ])
    assert excerpt(text).splitlines() == ["Minimum Qualifications:", "- Bachelor's degree in CS"]


def test_weak_words_alone_do_not_pick_a_line():
    text = "\n".join([
        "To succeed, organizations must blend digital and human capabilities.",
        "Enter Email address (Required)",
        "3+ years of experience required",
    ])
    assert excerpt(text) == "3+ years of experience required"


def test_pay_and_legal_lines_are_left_out_even_with_key_terms():
    text = "\n".join([
        "What You'll Bring",
        "Currently pursuing a Masters degree or PhD.",
        "The first year base compensation for this role is $155,000.",
        "Dental coverage, including orthodontia.",
        "Our hourly rates are based on your location, year in school, degree, and experience.",
        "FOR U.S. APPLICANTS: we are an Equal Opportunity employer.",
    ])
    assert excerpt(text).splitlines() == ["What You'll Bring", "Currently pursuing a Masters degree or PhD."]
