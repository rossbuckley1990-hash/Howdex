"""Top-level module entry so `python -m howdex ...` works from the source tree.

Equivalent to invoking `howdex.cli:main`. Supports both:
    python -m howdex                         # shows help
    python -m howdex init                    # runs a subcommand
    python -m howdex --path ./x.db remember  # global flags work too

This means you can use Howdex straight after unzipping, WITHOUT installing:

    unzip howdex-0.3.0.zip
    cd howdex
    python -m howdex init
    python -m howdex remember "hello"

No `pip install` required for trying it out.
"""

import sys

from howdex.cli import main


if __name__ == "__main__":
    sys.exit(main())
