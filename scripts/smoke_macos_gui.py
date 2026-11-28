"""Run the source launcher's opt-in Cocoa check against an isolated service.

Release smoke tests invoke the frozen app's --verify-dashboard command instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import launcher

    sys.argv = [
        sys.argv[0],
        "--verify-dashboard",
        "--service-url",
        args.url,
        "--report",
        str(args.report),
        "--verify-timeout",
        str(args.timeout),
    ]
    return launcher.main()


if __name__ == "__main__":
    raise SystemExit(main())
