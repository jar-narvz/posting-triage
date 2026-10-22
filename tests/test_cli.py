from posting_triage.cli import main


def test_run_is_a_stub(capsys):
    assert main(["run"]) == 0
    assert "not implemented" in capsys.readouterr().out
