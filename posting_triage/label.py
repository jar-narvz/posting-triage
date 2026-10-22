"""Interactive labeling session behind `triage label`.

Answers are single keypresses where possible. Lowercase keys pick an answer;
uppercase keys are controls, so they never collide with an answer:
    O  open the posting in your browser      B  back to the previous question
    S  skip this posting                     Q  quit (nothing saved for this posting)
"""

import sys
import webbrowser


class Back(Exception):
    """Go back one question."""


class SkipPosting(Exception):
    """Record this posting as skipped and move on."""


class Quit(Exception):
    """Stop the session without saving the posting in progress."""


CONTROLS = {"B": Back, "S": SkipPosting, "Q": Quit}
CONTROL_HELP = "O open · B back · S skip · Q quit"


class Terminal:
    """Real keyboard and screen. Tests use a scripted stand-in with the same methods."""

    def key(self):
        if not sys.stdin.isatty():
            line = sys.stdin.readline()
            if not line:
                raise Quit  # end of piped input
            return line[:1] if line.strip() else "\n"
        return read_key()

    def line(self, prompt):
        try:
            return input(prompt)
        except EOFError:
            raise Quit from None

    def show(self, text=""):
        print(text, flush=True)

    def open(self, url):
        webbrowser.open(url)


def read_key():
    """One keypress, without waiting for Enter (macOS/Linux)."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        key = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if key == "\x03":  # Ctrl-C arrives as a character in raw mode
        raise KeyboardInterrupt
    return "\n" if key == "\r" else key


class Prompter:
    """Asks one question at a time for one posting."""

    def __init__(self, io, url):
        self.io = io
        self.url = url

    def choose(self, question, options):
        """options: list of (key, value, label). Returns the chosen value."""
        values = {key: value for key, value, _ in options}
        labels = {key: label for key, _, label in options}
        menu = "  ".join(f"[{key}] {label}" for key, _, label in options)
        while True:
            self.io.show(f"{question}  {menu}")
            key = self.io.key()
            if self._control(key):
                continue
            if key in values:
                self.io.show(f"  → {labels[key]}")
                return values[key]
            self.io.show(f"  press one of: {' '.join(values)}  ({CONTROL_HELP})")

    def text(self, question, parse=str.strip):
        """A typed answer. `parse` may raise ValueError to ask again."""
        while True:
            answer = self.io.line(f"{question}: ")
            if self._control(answer.strip()):
                continue
            try:
                return parse(answer)
            except ValueError as e:
                self.io.show(f"  {e}")

    def _control(self, key):
        """Handle a control key. Returns True if the question should be asked again."""
        if key == "O":
            self.io.open(self.url)
            return True
        if key in CONTROLS:
            raise CONTROLS[key]
        return False
