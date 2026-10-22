import pytest

from posting_triage.cli import main


def test_run_is_a_stub(capsys):
    assert main(["run"]) == 0
    assert "not implemented" in capsys.readouterr().out


def test_cache_command_fetches_every_candidate(tmp_path, monkeypatch, capsys):
    from posting_triage.liveness import PostingText

    candidates = tmp_path / "candidates.csv"
    candidates.write_text(
        "id,url,company,title,location,source,section,tags\n"
        "aaa,https://boards.greenhouse.io/acme/jobs/1,Acme,SWE,SF,s,x,\n"
        "bbb,https://acme.wd1.myworkdayjobs.com/job/2,Acme,MLE,SF,s,x,\n"
    )
    fetched = []

    def fake_fetch_posting(url, browser):
        fetched.append((url, browser))
        return PostingText("ok", "browser" if browser else "greenhouse", "text")

    monkeypatch.setattr("posting_triage.cli.fetch_posting", fake_fetch_posting)
    monkeypatch.setattr("posting_triage.cli.Browser", FakeBrowser)
    cache_dir = tmp_path / "cache"
    args = ["cache", "--candidates", str(candidates), "--cache-dir", str(cache_dir), "--delay", "0"]

    assert main(args) == 0
    assert [url for url, _ in fetched] == [
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://acme.wd1.myworkdayjobs.com/job/2",
    ]
    assert fetched[0][1] is None  # browser not started for the API link
    assert isinstance(fetched[1][1], FakeBrowser)
    assert FakeBrowser.closed
    assert sorted(p.name for p in cache_dir.iterdir()) == ["aaa.json", "bbb.json"]
    assert "2 candidates: 2 ok" in capsys.readouterr().out


def test_cache_command_no_browser_never_starts_one(tmp_path, monkeypatch):
    from posting_triage.liveness import PostingText

    candidates = tmp_path / "candidates.csv"
    candidates.write_text("id,url,company,title\nbbb,https://acme.example/job/2,Acme,MLE\n")
    monkeypatch.setattr("posting_triage.cli.Browser", lambda: pytest.fail("browser started"))
    monkeypatch.setattr(
        "posting_triage.cli.fetch_posting",
        lambda url, browser: PostingText("unreadable", "browser", detail="browser not started"),
    )
    args = ["cache", "--candidates", str(candidates), "--cache-dir", str(tmp_path / "c"),
            "--delay", "0", "--no-browser"]
    assert main(args) == 0


class FakeBrowser:
    closed = False

    def __enter__(self):
        FakeBrowser.closed = False
        return self

    def __exit__(self, *exc):
        FakeBrowser.closed = True
