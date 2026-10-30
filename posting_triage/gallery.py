"""Turn `triage run --json` output into the static site's gallery of real results.

The gallery lives between two markers in site/index.html, so the page stays plain HTML
with no JavaScript. Quotes are cut to a few words: the site shows short quotes from
real postings, never their full text."""

import argparse
import csv
import datetime
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse

MAX_QUOTE_WORDS = 15
START, END = "<!-- gallery:start -->", "<!-- gallery:end -->"
FIELD_NAMES = {"role_type": "role type", "role_level": "role level"}


def short_quote(quote, max_words=MAX_QUOTE_WORDS):
    words = quote.split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:") + " …"


def reason(result):
    """The line under the verdict: the deciding field and its quote, or why there's none."""
    field = FIELD_NAMES.get(result["deciding_field"], result["deciding_field"])
    if result["verdict"] == "apply":
        return "every rule passed"
    if result["verdict"] == "dead":
        return "the posting was removed"
    if result["quote"]:
        return f'{field}: "{short_quote(result["quote"])}"'
    return f"{field}: {result['detail'] or 'no quote'}"


def gallery_rows(results, candidates):
    """One row per result, in order. Company and title come from the candidates list
    (the triage answer doesn't carry them); an unknown URL shows its host instead."""
    known = {c["url"]: c for c in candidates}
    rows = []
    for r in results:
        c = known.get(r["url"], {})
        rows.append({
            "company": c.get("company") or urlparse(r["url"]).hostname,
            "title": c.get("title", ""),
            "url": r["url"],
            "verdict": r["verdict"],
            "reason": reason(r),
            "careers_page": r["careers_page"],
        })
    return rows


def render(rows, model, date):
    e = html.escape
    items = []
    for row in rows:
        link = ""
        if row["careers_page"]:
            link = f' <a href="{e(row["careers_page"])}">careers page</a>'
        items.append(
            f'      <li><b class="v {e(row["verdict"])}">{e(row["verdict"].upper())}</b>'
            f'<span><a href="{e(row["url"])}">{e(row["company"])}</a> · {e(row["title"])}'
            f'<br><span class="why">{e(row["reason"])}</span>{link}</span></li>'
        )
    return "\n".join([
        START,
        f'    <p class="note">{len(rows)} real postings, run live on {e(date)} with {e(model)}.</p>',
        '    <ul class="gallery">',
        *items,
        "    </ul>",
        f"    {END}",
    ])


def replace_block(page, block):
    pattern = re.compile(re.escape(START) + ".*?" + re.escape(END), re.S)
    if len(pattern.findall(page)) != 1:
        raise ValueError(f"the page needs exactly one {START} … {END} block")
    return pattern.sub(lambda _: block, page)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", help="a file of `triage run --json` output, one JSON object per line")
    parser.add_argument("--candidates", default="data/candidates.csv")
    parser.add_argument("--page", default="site/index.html")
    parser.add_argument("--date", default=datetime.date.today().strftime("%b %-d, %Y"))
    args = parser.parse_args(argv)

    results = [json.loads(line) for line in Path(args.results).read_text().splitlines() if line.strip()]
    with open(args.candidates, newline="") as f:
        candidates = list(csv.DictReader(f))
    models = {r["model"] for r in results}
    if len(models) != 1:
        raise SystemExit(f"expected one model in the results, got {sorted(models)}")
    page = Path(args.page)
    page.write_text(replace_block(page.read_text(), render(gallery_rows(results, candidates), models.pop(), args.date)))
    print(f"wrote {len(results)} results into {page}")
    return 0
