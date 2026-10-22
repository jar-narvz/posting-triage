import pytest

from posting_triage.label import Back, Prompter, Quit, SkipPosting


class ScriptedIO:
    """Stand-in for Terminal: plays back keys and typed lines, records output."""

    def __init__(self, *inputs):
        self.inputs = list(inputs)
        self.output = []
        self.opened = []

    def key(self):
        return self.inputs.pop(0)

    def line(self, prompt):
        self.output.append(prompt)
        return self.inputs.pop(0)

    def show(self, text=""):
        self.output.append(text)

    def open(self, url):
        self.opened.append(url)


LEVELS = [("i", "intern", "intern"), ("g", "new_grad", "new grad"), ("u", "unclear", "unclear")]


def test_choose_returns_the_value_for_a_key():
    io = ScriptedIO("g")
    assert Prompter(io, "https://x").choose("Role level", LEVELS) == "new_grad"
    assert "[i] intern  [g] new grad  [u] unclear" in io.output[0]


def test_choose_reasks_on_an_unknown_key():
    io = ScriptedIO("z", "i")
    assert Prompter(io, "https://x").choose("Role level", LEVELS) == "intern"
    assert any("press one of: i g u" in line for line in io.output)


def test_open_shows_the_posting_and_asks_again():
    io = ScriptedIO("O", "u")
    assert Prompter(io, "https://x/job").choose("Role level", LEVELS) == "unclear"
    assert io.opened == ["https://x/job"]


@pytest.mark.parametrize("key, control", [("B", Back), ("S", SkipPosting), ("Q", Quit)])
def test_control_keys_raise(key, control):
    with pytest.raises(control):
        Prompter(ScriptedIO(key), "https://x").choose("Role level", LEVELS)


def test_text_parses_and_reasks_on_error():
    def years(answer):
        if not answer.strip().isdigit():
            raise ValueError("type a whole number")
        return int(answer)

    io = ScriptedIO("two", "2")
    assert Prompter(io, "https://x").text("Years", years) == 2
    assert "  type a whole number" in io.output


def test_text_accepts_control_keys_too():
    with pytest.raises(Back):
        Prompter(ScriptedIO("B"), "https://x").text("Years")
    io = ScriptedIO("O", "Seattle, WA")
    assert Prompter(io, "https://x").text("Locations") == "Seattle, WA"
    assert io.opened == ["https://x"]
