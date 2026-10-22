import datetime
import json

from posting_triage.cache import cache_all, cache_path, load, needs_fetch, save
from posting_triage.liveness import PostingText

ROWS = [
    {"id": "aaa", "url": "https://a.example/1", "company": "A", "title": "SWE"},
    {"id": "bbb", "url": "https://b.example/2", "company": "B", "title": "MLE"},
]


def test_save_then_load_round_trips(tmp_path):
    when = datetime.datetime(2026, 10, 22, 12, 0, tzinfo=datetime.timezone.utc)
    save("aaa", "https://a.example/1", PostingText("ok", "browser", "SWE I — Café", ""), tmp_path, now=when)
    assert load("aaa", tmp_path) == {
        "id": "aaa",
        "url": "https://a.example/1",
        "fetched_at": "2026-10-22T12:00:00+00:00",
        "status": "ok",
        "source": "browser",
        "detail": "",
        "text": "SWE I — Café",
    }
    assert "Café" in cache_path("aaa", tmp_path).read_text()  # readable, not \u-escaped
    assert not list(tmp_path.glob("*.tmp"))


def test_load_missing_is_none(tmp_path):
    assert load("nope", tmp_path) is None


def test_needs_fetch_retries_only_unreadable(tmp_path):
    assert needs_fetch("aaa", tmp_path)
    save("aaa", "u", PostingText("ok", "greenhouse", "text"), tmp_path)
    save("bbb", "u", PostingText("not_found", "lever", detail="HTTP 404"), tmp_path)
    save("ccc", "u", PostingText("unreadable", "browser", detail="timeout"), tmp_path)
    assert not needs_fetch("aaa", tmp_path)
    assert not needs_fetch("bbb", tmp_path)
    assert needs_fetch("ccc", tmp_path)
    assert needs_fetch("aaa", tmp_path, refresh=True)


def test_cache_all_fetches_saves_and_skips_on_rerun(tmp_path):
    fetched = []

    def fetch(url):
        fetched.append(url)
        return PostingText("ok", "browser", f"text for {url}")

    logs = []
    counts = cache_all(ROWS, fetch, tmp_path, log=logs.append)
    assert fetched == ["https://a.example/1", "https://b.example/2"]
    assert counts == {("ok", "browser"): 2}
    assert json.loads(cache_path("bbb", tmp_path).read_text())["text"] == "text for https://b.example/2"
    assert logs[0] == "0 already cached, 2 to fetch"

    fetched.clear()
    assert cache_all(ROWS, fetch, tmp_path, log=lambda m: None) == {("ok", "browser"): 2}
    assert fetched == []


def test_cache_all_sleeps_between_fetches_only(tmp_path):
    sleeps = []
    cache_all(ROWS, lambda url: PostingText("ok", "browser", "x"), tmp_path,
              sleep=lambda: sleeps.append(1), log=lambda m: None)
    assert sleeps == [1]  # two fetches, one pause between them
