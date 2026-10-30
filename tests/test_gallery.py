"""The site's gallery: short quotes only, escaped HTML, and the committed page obeys both."""

import json
import re
from pathlib import Path

import pytest

from posting_triage.gallery import (
    END,
    MAX_QUOTE_WORDS,
    START,
    gallery_rows,
    main,
    reason,
    render,
    replace_block,
    short_quote,
)

ROOT = Path(__file__).resolve().parent.parent


def result(verdict="skip", field="degree", quote="Currently enrolled in a PhD program", **kw):
    return {"url": "https://jobs.example.com/1", "verdict": verdict, "deciding_field": field, "quote": quote,
            "careers_page": None, "detail": "", "model": "claude-haiku-5-5", "latency_ms": 1, **kw}


def test_a_short_quote_is_kept_whole():
    assert short_quote("SDE II, OIH") == "SDE II, OIH"


def test_a_long_quote_is_cut_to_the_word_limit():
    quote = " ".join(f"w{i}" for i in range(40))
    cut = short_quote(quote)
    assert cut.endswith(" …")
    assert len(cut.removesuffix(" …").split()) == MAX_QUOTE_WORDS


def test_a_cut_drops_a_trailing_comma():
    assert short_quote("a b, c d", max_words=2) == "a b …"


@pytest.mark.parametrize(
    "r, expected",
    [
        (result(), 'degree: "Currently enrolled in a PhD program"'),
        (result(field="role_level", quote="SDE II"), 'role level: "SDE II"'),
        (result(verdict="apply", field="", quote=None), "every rule passed"),
        (result(verdict="dead", field="liveness", quote=None), "the posting was removed"),
        (result(verdict="flag", field="liveness", quote=None, detail="couldn't verify (no posting text)"),
         "liveness: couldn't verify (no posting text)"),
    ],
)
def test_reason_line(r, expected):
    assert reason(r) == expected


def test_company_and_title_come_from_the_candidates_list():
    rows = gallery_rows([result()], [{"url": "https://jobs.example.com/1", "company": "Acme", "title": "SWE Intern"}])
    assert (rows[0]["company"], rows[0]["title"]) == ("Acme", "SWE Intern")


def test_an_unknown_url_shows_its_host():
    assert gallery_rows([result()], [])[0]["company"] == "jobs.example.com"


def test_render_escapes_posting_text():
    rows = gallery_rows([result(quote='<script>alert("x")</script>')], [{"url": "https://jobs.example.com/1",
                                                                         "company": "A&B", "title": "<i>"}])
    html = render(rows, "claude-haiku-5-5", "Oct 29, 2026")
    assert "<script>" not in html and "<i>" not in html
    assert "A&amp;B" in html


def test_a_dead_posting_links_its_careers_page():
    rows = gallery_rows([result(verdict="dead", careers_page="https://jobs.lever.co/acme")], [])
    assert '<a href="https://jobs.lever.co/acme">careers page</a>' in render(rows, "m", "d")


def test_replace_block_swaps_only_the_marked_part():
    page = f"<h1>x</h1>\n{START}\nold\n{END}\n<p>y</p>"
    assert replace_block(page, f"{START}new{END}") == f"<h1>x</h1>\n{START}new{END}\n<p>y</p>"


@pytest.mark.parametrize("page", ["no markers", f"{START}a{END}{START}b{END}"])
def test_replace_block_needs_exactly_one_block(page):
    with pytest.raises(ValueError):
        replace_block(page, "")


def test_main_writes_the_page(tmp_path):
    (tmp_path / "r.jsonl").write_text(json.dumps(result()) + "\n")
    (tmp_path / "c.csv").write_text("url,company,title\nhttps://jobs.example.com/1,Acme,SWE Intern\n")
    page = tmp_path / "index.html"
    page.write_text(f"<main>{START}{END}</main>")
    assert main([str(tmp_path / "r.jsonl"), "--candidates", str(tmp_path / "c.csv"), "--page", str(page),
                 "--date", "Oct 29, 2026"]) == 0
    text = page.read_text()
    assert "Acme" in text and "1 real postings, run live on Oct 29, 2026 with claude-haiku-5-5" in text


def test_main_refuses_results_from_more_than_one_model(tmp_path):
    lines = [json.dumps(result()), json.dumps(result(model="claude-opus-5-5"))]
    (tmp_path / "r.jsonl").write_text("\n".join(lines))
    (tmp_path / "c.csv").write_text("url,company,title\n")
    with pytest.raises(SystemExit):
        main([str(tmp_path / "r.jsonl"), "--candidates", str(tmp_path / "c.csv")])


def test_the_published_gallery_quotes_stay_short():
    # The committed page itself, not just the function: no gallery quote over the limit.
    page = (ROOT / "site" / "index.html").read_text()
    block = page[page.index(START):page.index(END)]
    quotes = re.findall(r"&quot;(.*?)&quot;", block)
    assert quotes, "the gallery should show at least one quote"
    for q in quotes:
        assert len(q.removesuffix(" …").split()) <= MAX_QUOTE_WORDS, q
