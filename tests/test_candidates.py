import csv
from pathlib import Path

import pytest

from posting_triage.candidates import (
    clean_url,
    collect,
    is_hard,
    is_us_location,
    main,
    parse_simplify,
    parse_speedyapply,
    sample,
)

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLIFY = (FIXTURES / "simplify_sample.md").read_text()
SPEEDY = (FIXTURES / "speedyapply_sample.md").read_text()


def test_simplify_rows():
    rows = parse_simplify(SIMPLIFY, "simplify-newgrad")
    # Beta is closed (🔒) and Delta is in a non-target section, so neither appears.
    assert [r["company"] for r in rows] == ["Alpha", "Alpha", "Gamma"]
    first, second, third = rows
    assert first["url"] == "https://job-boards.greenhouse.io/alpha/jobs/111"
    assert first["location"] == "SF"
    assert first["section"] == "Software Engineering New Grad Roles"
    # ↳ resolves to the company above; tags move out of the title.
    assert second["title"] == "Machine Learning Engineer Graduate"
    assert second["tags"] == "🎓🛂"
    assert second["location"] == "Seattle, WA; Toronto, ON, Canada"
    assert second["url"] == "https://jobs.lever.co/alpha/222?lever-source=x"
    assert third["location"] == "London, UK; Toronto, ON, Canada"


def test_speedyapply_rows_handle_both_table_layouts():
    rows = parse_speedyapply(SPEEDY, "speedyapply-intern")
    assert [(r["company"], r["section"]) for r in rows] == [("Epsilon", "FAANG+"), ("Zeta & Co", "Other")]
    assert rows[1]["title"] == "Data & ML Engineer Intern"
    assert rows[1]["location"] == "Remote - San Francisco, CA +1"
    assert rows[1]["url"] == "https://jobs.ashbyhq.com/zeta/5f0c"


@pytest.mark.parametrize(
    "url, cleaned",
    [
        ("https://a.example/j/1?utm_source=Simplify&ref=Simplify", "https://a.example/j/1"),
        ("https://a.example/jobs?gh_jid=42&utm_medium=x", "https://a.example/jobs?gh_jid=42"),
        ("https://a.example/j/1?ref=partner", "https://a.example/j/1?ref=partner"),
    ],
)
def test_clean_url_drops_only_tracking(url, cleaned):
    assert clean_url(url) == cleaned


@pytest.mark.parametrize(
    "location, us",
    [
        ("SF", True),
        ("NYC", True),
        ("Austin, TX", True),
        ("Remote in USA", True),
        ("United States", True),
        ("London, UK", False),
        ("Toronto, ON, Canada", False),
        ("Remote in Canada", False),
        ("London, UK; Seattle, WA", True),
    ],
)
def test_us_location(location, us):
    assert is_us_location(location) is us


def test_collect_filters_non_us_and_dedups():
    texts = {"simplify-newgrad": SIMPLIFY, "speedyapply-intern": SPEEDY}
    rows = collect(texts)
    titles = {r["title"] for r in rows}
    assert "Software Developer" not in titles  # Gamma: London/Toronto only
    assert len(rows) == 4
    assert len({r["id"] for r in rows}) == 4

    duplicated = collect({"simplify-newgrad": SIMPLIFY, "simplify-intern": SIMPLIFY})
    assert len(duplicated) == 2
    assert {r["source"] for r in duplicated} == {"simplify-newgrad"}  # first source wins


@pytest.mark.parametrize(
    "title, tags, hard",
    [
        ("Machine Learning Engineer Graduate", "", True),
        ("Software Engineer I/II", "", True),
        ("Software Engineer II", "", True),
        ("Research Engineer - PhD", "", True),
        ("Data & ML Engineer", "", True),
        ("Software Engineer Intern", "🎓", True),
        ("Software Engineer, New Grad", "", False),
        ("Software Engineer Intern", "🛂", False),
    ],
)
def test_is_hard(title, tags, hard):
    assert is_hard({"title": title, "tags": tags}) is hard


def fake_rows(count):
    rows = []
    for i in range(count):
        source = ("simplify-newgrad", "simplify-intern")[i % 2]
        title = "Software Engineer II" if i % 3 == 0 else "Software Engineer"
        rows.append({"id": f"{i:04d}", "title": title, "tags": "", "source": source})
    return rows


def test_sample_is_seeded_and_balanced():
    rows = fake_rows(600)
    first = sample(rows, 150, seed=1)
    assert first == sample(rows, 150, seed=1)
    assert first != sample(rows, 150, seed=2)
    assert len({r["id"] for r in first}) == 150
    newgrad = [r for r in first if r["source"] == "simplify-newgrad"]
    assert len(newgrad) == 75
    assert sum(is_hard(r) for r in first) == 50


def test_sample_tops_up_when_a_pool_runs_short():
    rows = [r for r in fake_rows(600) if not (r["source"] == "simplify-newgrad" and is_hard(r))]
    picked = sample(rows, 150, seed=1)
    assert len(picked) == 150
    assert len({r["id"] for r in picked}) == 150


def test_sample_returns_everything_when_asked_for_too_many():
    assert len(sample(fake_rows(10), 150, seed=1)) == 10


def test_main_writes_csv_and_refuses_to_overwrite(tmp_path, monkeypatch, capsys):
    texts = {
        "simplify-newgrad": SIMPLIFY,
        "simplify-intern": "",
        "speedyapply-newgrad": "",
        "speedyapply-intern": SPEEDY,
    }
    monkeypatch.setattr(
        "posting_triage.candidates.fetch",
        lambda url: next(t for name, t in texts.items() if url.endswith(SOURCE_FILES[name])),
    )
    out = tmp_path / "data" / "candidates.csv"
    assert main(["--out", str(out), "-n", "3"]) == 0
    with out.open() as f:
        written = list(csv.DictReader(f))
    assert len(written) == 3
    assert list(written[0]) == ["id", "url", "company", "title", "location", "source", "section", "tags"]

    out.write_text("labeled against this\n")
    assert main(["--out", str(out)]) == 1
    assert out.read_text() == "labeled against this\n"
    assert "--force" in capsys.readouterr().err


SOURCE_FILES = {
    "simplify-newgrad": "New-Grad-Positions/HEAD/README.md",
    "simplify-intern": "Summer2027-Internships/HEAD/README.md",
    "speedyapply-newgrad": "NEW_GRAD_USA.md",
    "speedyapply-intern": "2027-SWE-College-Jobs/HEAD/README.md",
}
