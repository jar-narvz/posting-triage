"""Read and write cached posting text under data/cache/ (gitignored).

One JSON file per posting, named by its candidate id. Labels and the eval both read
from here, so they always see the same text even after the live posting changes.
"""

import datetime
import json
import os
from collections import Counter
from pathlib import Path

CACHE_DIR = Path("data/cache")
# Worth fetching again: a server error or timeout may be gone next time.
RETRY_STATUSES = {"unreadable"}


def cache_path(posting_id, cache_dir=CACHE_DIR):
    return Path(cache_dir) / f"{posting_id}.json"


def load(posting_id, cache_dir=CACHE_DIR):
    """The cached entry as a dict, or None if this posting was never fetched."""
    path = cache_path(posting_id, cache_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save(posting_id, url, result, cache_dir=CACHE_DIR, now=None):
    """Write one fetch result. Writes to a temp file first so a crash never leaves half a file."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    entry = {
        "id": posting_id,
        "url": url,
        "fetched_at": now.isoformat(timespec="seconds"),
        "status": result.status,
        "source": result.source,
        "detail": result.detail,
        "text": result.text,
    }
    path = cache_path(posting_id, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=1))
    os.replace(tmp, path)
    return entry


def needs_fetch(posting_id, cache_dir=CACHE_DIR, refresh=False):
    if refresh:
        return True
    entry = load(posting_id, cache_dir)
    return entry is None or entry["status"] in RETRY_STATUSES


def cache_all(rows, fetch, cache_dir=CACHE_DIR, refresh=False, sleep=None, log=print):
    """Fetch and save every candidate row that needs it. Returns a Counter of
    (status, source) for everything now in the cache for these rows."""
    todo = [r for r in rows if needs_fetch(r["id"], cache_dir, refresh)]
    log(f"{len(rows) - len(todo)} already cached, {len(todo)} to fetch")
    for i, row in enumerate(todo, 1):
        if i > 1 and sleep:
            sleep()  # be polite to the job boards
        result = fetch(row["url"])
        save(row["id"], row["url"], result, cache_dir)
        log(
            f"[{i}/{len(todo)}] {result.status:10} {result.source:10} {len(result.text):6} chars  "
            f"{row['company']} — {row['title']}"
        )

    counts = Counter()
    for row in rows:
        entry = load(row["id"], cache_dir)
        if entry:
            counts[(entry["status"], entry["source"])] += 1
    return counts
