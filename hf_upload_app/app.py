import os
import sys
import logging
import traceback

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def main() -> None:
    cli_mode = os.getenv("HF_DATASET_UPLOADER_CLI", "").lower() in ("1", "true", "yes")
    has_args = len(sys.argv) > 1

    try:
        if cli_mode or has_args:
            logger.info("Starting in CLI mode")
            from uploader.main import cli

            cli()
        else:
            logger.info("Starting in Native UI mode")
            from native_ui import main as native_main

            native_main()
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
