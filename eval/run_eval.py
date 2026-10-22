"""Score the baseline (and later the direct prompt and the pipeline). See posting_triage/run_eval.py."""

import sys

from posting_triage.run_eval import main

if __name__ == "__main__":
    sys.exit(main())
