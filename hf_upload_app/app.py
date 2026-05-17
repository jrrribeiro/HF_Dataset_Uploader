import os
import sys
import logging
import traceback

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

try:
    cli_mode = os.getenv("BIRDNET_UPLOADER_CLI", "").lower() in ("1", "true", "yes")
    has_args = len(sys.argv) > 1

    if cli_mode or has_args:
        logger.info("Starting in CLI mode")
        from uploader.main import cli

        cli()
    else:
        logger.info("Starting in Web UI mode")
        from uploader.web_ui import create_uploader_app

        app = create_uploader_app()
        port = int(os.getenv("PORT") or os.getenv("BIRDNET_UPLOADER_PORT") or "7860")
        host = os.getenv("BIRDNET_UPLOADER_HOST") or "0.0.0.0"
        logger.info(f"Launching Gradio app on {host}:{port}")
        print("\n" + "=" * 60)
        print("BirdNET Uploader Web UI")
        print(f"Opening browser at: http://localhost:{port}")
        print("=" * 60 + "\n")
        app.launch(server_name=host, server_port=port, show_error=True)

except Exception as exc:
    logger.error(f"FATAL ERROR: {exc}")
    logger.error(traceback.format_exc())
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"ERROR: {exc}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Details:\n{traceback.format_exc()}", file=sys.stderr)
    sys.exit(1)
