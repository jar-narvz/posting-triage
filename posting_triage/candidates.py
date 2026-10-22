"""Pull candidate postings from the public Simplify and speedyapply READMEs into
data/candidates.csv, then take a seeded sample to label."""

import argparse
import csv
import hashlib
import html
import random
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from posting_triage.liveness import board_job

RAW = "https://raw.githubusercontent.com"
SOURCES = {
    "simplify-newgrad": (f"{RAW}/SimplifyJobs/New-Grad-Positions/HEAD/README.md", "new_grad"),
    "simplify-intern": (f"{RAW}/SimplifyJobs/Summer2027-Internships/HEAD/README.md", "intern"),
    "speedyapply-newgrad": (f"{RAW}/speedyapply/2027-SWE-College-Jobs/HEAD/NEW_GRAD_USA.md", "new_grad"),
    "speedyapply-intern": (f"{RAW}/speedyapply/2027-SWE-College-Jobs/HEAD/README.md", "intern"),
}
# Simplify also lists product, quant, and hardware roles; only these sections match target role types.
SIMPLIFY_SECTIONS = ("Software Engineering", "Data Science, AI & Machine Learning")
TAGS = ("🎓", "🛂", "🇺🇸")
COLUMNS = ("id", "url", "company", "title", "location", "source", "section", "tags")

# Titles the keyword baseline is likely to get wrong, or that need a careful read.
HARD_TITLE = re.compile(
    r"\b(graduate|ph\.?d|masters?|mba|senior|sr|staff|principal|ii|iii|l[3-5]|data scientist)\b"
    r"|\bi\s*/\s*ii\b|\b1\s*/\s*2\b|&",
    re.IGNORECASE,
)

US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
US_NAMES = {"sf", "nyc", "la", "us", "usa", "united states", "remote"}


def parse_simplify(text, source):
    """Rows from Simplify's HTML tables, keeping only the target sections and open postings."""
    rows = []
    for section, body in split_sections(text, "## "):
        if not any(name in section for name in SIMPLIFY_SECTIONS):
            continue
        company = ""
        for tr in re.findall(r"<tr>(.*?)</tr>", body, re.DOTALL):
            cells = re.findall(r"<td>(.*?)</td>", tr, re.DOTALL)
            if len(cells) < 4:
                continue  # header row
            name = strip_tags(cells[0]).replace("🔥", "").strip()
            company = company if name == "↳" else name  # ↳ = same company as the row above
            url = first_href(cells[3])
            if url is None:
                continue  # 🔒 closed: no apply link
            title, tags = split_tags(strip_tags(cells[1]))
            rows.append(
                {
                    "url": url,
                    "company": company,
                    "title": title,
                    "location": simplify_location(cells[2]),
                    "source": source,
                    "section": clean_section(section),
                    "tags": tags,
                }
            )
    return rows


def parse_speedyapply(text, source):
    """Rows from speedyapply's Markdown tables. Their USA files are US-only by construction."""
    rows = []
    for section, body in split_sections(text, "### "):
        header = None
        for line in body.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells[0] == "Company":
                header = cells
                continue
            if header is None or set(line) <= set("|-: "):
                continue  # separator row
            cell = dict(zip(header, cells))
            url = first_href(cell.get("Posting", ""))
            if url is None:
                continue
            title, tags = split_tags(strip_tags(cell["Position"]))
            rows.append(
                {
                    "url": url,
                    "company": strip_tags(cell["Company"]),
                    "title": title,
                    "location": strip_tags(cell["Location"]),
                    "source": source,
                    "section": clean_section(section),
                    "tags": tags,
                }
            )
    return rows


def split_sections(text, marker):
    """Yield (heading, body) for each heading that starts with `marker`."""
    parts = re.split(rf"^{re.escape(marker)}(.*)$", text, flags=re.MULTILINE)
    for i in range(1, len(parts) - 1, 2):
        yield parts[i].strip(), parts[i + 1]


def strip_tags(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def first_href(fragment):
    match = re.search(r'href="([^"]+)"', fragment)
    return clean_url(html.unescape(match.group(1))) if match else None


def clean_url(url):
    """Drop tracking parameters so the same posting from two lists dedups to one URL."""
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.startswith("utm_") and not (k == "ref" and v.lower() == "simplify")
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def split_tags(title):
    tags = "".join(t for t in TAGS if t in title)
    for t in TAGS:
        title = title.replace(t, "")
    return " ".join(title.split()), tags


def simplify_location(cell):
    cell = re.sub(r"<summary>.*?</summary>", "", cell)  # "4 locations" label
    cell = re.sub(r"</?br\s*/?>", "; ", cell)
    return "; ".join(p.strip() for p in strip_tags(cell).split(";") if p.strip())


def clean_section(heading):
    """'💻 Software Engineering New Grad Roles' -> 'Software Engineering New Grad Roles'."""
    return re.sub(r"^[^\w]+", "", heading).replace(":", "").strip()


def is_us_location(location):
    """True if any of the listed locations is in the US (or plain/US remote)."""
    for place in location.split(";"):
        place = place.strip()
        lower = place.lower()
        if lower in US_NAMES or (lower.startswith("remote") and re.search(r"\bus(a)?\b|united states", lower)):
            return True
        last = place.rsplit(",", 1)[-1].strip()
        if last in US_STATES:
            return True
    return False


def posting_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:10]


def same_posting_key(url):
    """Two URLs for one board job (e.g. Ashby's .../{id} and .../{id}/application) share a key."""
    job = board_job(url)
    return (job.board, job.token.lower(), job.job_id) if job else url


def collect(texts):
    """texts: {source: README text}. Returns deduped US rows with ids, in a stable order."""
    seen = {}
    for source, text in texts.items():
        parse = parse_simplify if source.startswith("simplify") else parse_speedyapply
        for row in parse(text, source):
            if source.startswith("simplify") and not is_us_location(row["location"]):
                continue
            row["id"] = posting_id(row["url"])
            seen.setdefault(same_posting_key(row["url"]), row)  # first source wins on duplicates
    return sorted(seen.values(), key=lambda r: r["id"])


def is_hard(row):
    return "🎓" in row["tags"] or bool(HARD_TITLE.search(row["title"]))


def sample(rows, n, seed, hard_share=1 / 3):
    """Seeded sample of n rows, split evenly between new grad and intern,
    with about `hard_share` of each half drawn from likely hard cases."""
    rng = random.Random(seed)
    track = {name: group for name, (_, group) in SOURCES.items()}
    pools = {}
    for row in rows:
        key = (track.get(row["source"], "intern"), is_hard(row))
        pools.setdefault(key, []).append(row)

    per_track = n // 2
    targets = {}
    for group in ("new_grad", "intern"):
        hard = round(per_track * hard_share)
        targets[(group, True)] = hard
        targets[(group, False)] = per_track - hard
    targets[("intern", False)] += n - 2 * per_track  # odd n

    picked = []
    for key, want in targets.items():
        pool = pools.get(key, [])
        picked += rng.sample(pool, min(want, len(pool)))
    # A pool that ran short is topped up from whatever is left.
    chosen = {r["id"] for r in picked}
    rest = [r for r in rows if r["id"] not in chosen]
    picked += rng.sample(rest, min(n - len(picked), len(rest)))
    rng.shuffle(picked)  # so labeling doesn't front-load the hard cases
    return picked


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({k: row[k] for k in COLUMNS} for row in rows)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "posting-triage"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/candidates.csv")
    parser.add_argument("-n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=2027)
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists() and not args.force:
        # The READMEs change daily, so a rerun picks different postings and
        # orphans any labels already made against this file.
        print(f"{out} already exists; pass --force to replace it.", file=sys.stderr)
        return 1

    texts = {name: fetch(url) for name, (url, _) in SOURCES.items()}
    rows = collect(texts)
    picked = sample(rows, args.n, args.seed)
    write_csv(picked, out)

    hard = sum(is_hard(r) for r in picked)
    by_source = {s: sum(r["source"] == s for r in picked) for s in SOURCES}
    print(f"{len(rows)} open US postings; wrote {len(picked)} to {out} ({hard} likely hard cases)")
    for source, count in by_source.items():
        print(f"  {source}: {count}")
    return 0
