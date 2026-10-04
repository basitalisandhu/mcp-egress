"""Allow `python -m mcp_egress`."""

import sys

from .cli import main

sys.exit(main())
