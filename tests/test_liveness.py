import pytest

from posting_triage.liveness import BoardJob, board_job, html_to_text

UUID = "3d182b7f-482e-45b2-8668-f04f0b5fda8e"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://boards.greenhouse.io/figma/jobs/6219995004?gh_jid=6219995004",
         BoardJob("greenhouse", "figma", "6219995004")),
        ("https://job-boards.greenhouse.io/doordashusa/jobs/8263774",
         BoardJob("greenhouse", "doordashusa", "8263774")),
        ("https://job-boards.eu.greenhouse.io/acme/jobs/123",
         BoardJob("greenhouse", "acme", "123")),
        ("https://boards.greenhouse.io/embed/job_app?for=acme&token=456",
         BoardJob("greenhouse", "acme", "456")),
        (f"https://jobs.lever.co/kobie/{UUID}", BoardJob("lever", "kobie", UUID)),
        (f"https://jobs.lever.co/kobie/{UUID}/apply", BoardJob("lever", "kobie", UUID)),
        (f"https://jobs.eu.lever.co/acme/{UUID}", BoardJob("lever", "acme", UUID, eu=True)),
        (f"https://jobs.ashbyhq.com/spruceid/{UUID}", BoardJob("ashby", "spruceid", UUID)),
        (f"https://jobs.ashbyhq.com/crusoe/{UUID}/application?embed=true",
         BoardJob("ashby", "crusoe", UUID)),
    ],
)
def test_board_urls_are_recognized(url, expected):
    assert board_job(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://careers.withwaymo.com/jobs?gh_jid=8202025",  # board token not in URL
        "https://boards.greenhouse.io/figma",  # board page, not a job
        "https://jobs.lever.co/kobie",
        "https://jobs.ashbyhq.com/spruceid",
        "https://jobs.ashbyhq.com/spruceid/not-a-uuid",
        "https://netflix.wd108.myworkdayjobs.com/en-US/netflix/job/Los-Gatos/SWE-Intern_JR42989",
        "https://lifeattiktok.com/search/7512345",
    ],
)
def test_other_urls_go_to_the_browser(url):
    assert board_job(url) is None


def test_every_board_url_in_candidates_parses():
    """Guard against URL shapes the real lists use that the parser misses."""
    import csv
    from pathlib import Path

    path = Path(__file__).parent.parent / "data" / "candidates.csv"
    with path.open() as f:
        urls = [row["url"] for row in csv.DictReader(f)]
    board_hosted = [
        u for u in urls
        if any(h in u for h in ("://boards.greenhouse.io/", "://job-boards.", "://jobs.lever.co/", "://jobs.ashbyhq.com/"))
    ]
    assert board_hosted, "expected some board-hosted URLs in the sample"
    assert [u for u in board_hosted if board_job(u) is None] == []


def test_html_to_text_keeps_structure():
    markup = (
        "<h2>About the role</h2><p>Build things&nbsp;at   scale.</p>"
        "<ul><li>BS in CS</li><li>2+ years <strong>preferred</strong></li></ul>"
        "<p>Pay &amp; benefits</p>"
    )
    assert html_to_text(markup) == (
        "About the role\nBuild things at scale.\n- BS in CS\n- 2+ years preferred\nPay & benefits"
    )


def test_html_to_text_drops_scripts_and_styles():
    markup = "<style>p{color:red}</style><p>Visible</p><script>var x = '<p>no</p>';</script>"
    assert html_to_text(markup) == "Visible"


def test_html_to_text_handles_br_and_plain_text():
    assert html_to_text("Line one<br>Line two<br/>Line three") == "Line one\nLine two\nLine three"
    assert html_to_text("no tags at all") == "no tags at all"
    assert html_to_text("") == ""
