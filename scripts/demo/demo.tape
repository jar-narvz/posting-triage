# The site's demo GIF: one live run of `triage run` on four real postings.
# Re-record from the repo root (needs VHS, the venv, and an API key in .env):
#   vhs scripts/demo/demo.tape
# It calls the Claude API (Haiku, about a cent) and the job boards, so results can change
# as postings close. The API key is read from .env and never typed on screen.

Output site/demo.gif

Set Shell "bash"
Set FontSize 18
Set Width 1240
Set Height 380
Set Padding 24
Set TypingSpeed 35ms

Hide
Type "source .venv/bin/activate && export PS1='> ' && clear"
Enter
Show

Type "cat scripts/demo/postings.txt"
Enter
Sleep 2s

Type "triage run $(cat scripts/demo/postings.txt)"
Enter
Wait@120s
Sleep 6s
