"""The static site: its eval table must match the README's, cell for cell, so a number
can't change in one place and stay stale in the other, and every file it links must exist."""

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class _TableRows(HTMLParser):
    """Collects the text of each row in the table with id="eval-table"."""

    def __init__(self):
        super().__init__()
        self.rows, self._in_table, self._cell = [], False, None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and ("id", "eval-table") in attrs:
            self._in_table = True
        elif self._in_table and tag == "tr":
            self.rows.append([])
        elif self._in_table and tag in ("td", "th"):
            self._cell = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self._in_table = False
        elif self._in_table and tag in ("td", "th"):
            self.rows[-1].append(self._cell.strip())
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell += data


def site_rows():
    parser = _TableRows()
    parser.feed((ROOT / "site" / "index.html").read_text())
    return parser.rows


def readme_rows():
    lines = (ROOT / "README.md").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| Approach |"))
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        cells = [c.strip().replace("**", "") for c in line.strip("|").split("|")]
        if not set("".join(cells)) <= set("-"):  # skip the |---| separator row
            rows.append(cells)
    return rows


def test_site_eval_table_matches_readme():
    assert site_rows() == readme_rows()


def test_site_eval_table_is_not_empty():
    # Guards the test above against both parsers finding nothing.
    assert len(site_rows()) == 8


class _LocalRefs(HTMLParser):
    """Collects every href, src and srcset that points at a file next to the page."""

    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src", "srcset") and value and "://" not in value and not value.startswith("#"):
                self.refs.append(value)


def test_every_local_file_the_site_links_exists():
    parser = _LocalRefs()
    parser.feed((ROOT / "site" / "index.html").read_text())
    assert parser.refs, "the page should link its stylesheet, diagrams and demo"
    missing = [ref for ref in parser.refs if not (ROOT / "site" / ref).is_file()]
    assert not missing
