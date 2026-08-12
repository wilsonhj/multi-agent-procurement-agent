"""`python -m procurement_agent.audit` - the H.5 chain-verification CLI.

A module entry point rather than a console script: this is an operator tool run
from cron or a release check, not something a user installs, and adding it to
`[project.scripts]` would put it on the PATH of every environment that depends
on this package for its envelope alone.
"""

from __future__ import annotations

import sys

from .verify import main

if __name__ == "__main__":
    sys.exit(main())
