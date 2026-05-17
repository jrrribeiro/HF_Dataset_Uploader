"""CLI entrypoint for the standalone HF upload script."""

from __future__ import annotations

import logging
import sys
import traceback

from uploader.main import cli


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    try:
        logger.info("Starting in CLI mode")
        cli()
    except Exception as exc:
        logger.error(f"FATAL ERROR: {exc}")
        logger.error(traceback.format_exc())
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"Details:\n{traceback.format_exc()}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
