"""Write the site's gallery from `triage run --json` output. See posting_triage/gallery.py."""

import sys

from posting_triage.gallery import main

if __name__ == "__main__":
    sys.exit(main())
