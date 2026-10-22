import datetime

from posting_triage.cli import EXAMPLE_PROFILE, init_profile
from posting_triage.profile import load_profile


def scripted(*answers):
    """Stand-in for input(): returns the answers in order and records each question."""
    queue = list(answers)
    asked = []

    def ask(question):
        asked.append(question)
        return queue.pop(0)

    ask.asked = asked
    return ask


def test_all_defaults_write_the_example_profile(tmp_path):
    path = tmp_path / "profile.yaml"
    assert init_profile(path, ask=scripted("", "", "", "", "", "")) == 0
    assert load_profile(path) == load_profile(EXAMPLE_PROFILE)


def test_answers_are_written_and_load_back(tmp_path):
    path = tmp_path / "profile.yaml"
    ask = scripted(
        "masters",
        "2026-12",
        "Seattle, Remote: US",
        "new_grad, spring_coop",
        "swe, ml_ai",
        "-",
    )
    assert init_profile(path, ask=ask) == 0
    profile = load_profile(path)
    assert profile.degree == "masters"
    assert profile.graduation_date == datetime.date(2026, 12, 1)
    assert profile.locations == ("Seattle", "Remote: US")
    assert profile.tracks == ("new_grad", "spring_coop")
    assert profile.target_role_types == ("swe", "ml_ai")
    assert profile.excluded_role_types == ()


def test_bad_answer_is_asked_again(tmp_path, capsys):
    path = tmp_path / "profile.yaml"
    ask = scripted("bs", "bachelors", "May 2027", "2027-05", "", "", "", "")
    assert init_profile(path, ask=ask) == 0
    assert len(ask.asked) == 8
    out = capsys.readouterr().out
    assert "degree must be one of" in out
    assert "YYYY-MM" in out


def test_excluding_a_targeted_type_is_asked_again(tmp_path, capsys):
    path = tmp_path / "profile.yaml"
    ask = scripted("", "", "", "", "swe", "swe", "data_scientist")
    assert init_profile(path, ask=ask) == 0
    assert "already listed" in capsys.readouterr().out
    assert load_profile(path).excluded_role_types == ("data_scientist",)


def test_existing_profile_is_kept_unless_confirmed(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("original\n")
    for answer in ("", "n", "no", "anything"):
        ask = scripted(answer)
        assert init_profile(path, ask=ask) == 1
        assert len(ask.asked) == 1  # stops before asking any profile questions
        assert path.read_text() == "original\n"


def test_existing_profile_is_overwritten_on_yes(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("original\n")
    assert init_profile(path, ask=scripted("y", "", "", "", "", "", "")) == 0
    assert load_profile(path).degree == "bachelors"
