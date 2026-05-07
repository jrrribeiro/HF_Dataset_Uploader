import os
import sys
import logging
import traceback

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from src.uploader.web_ui import create_uploader_app
    from src.uploader.main import cli

    # Determine mode
    cli_mode = os.getenv("BIRDNET_UPLOADER_CLI", "").lower() in ("1", "true", "yes")
    has_args = len(sys.argv) > 1
    
    logger.info(f"Mode detection: cli_mode={cli_mode}, has_args={has_args}, argv={sys.argv}")
    
    if cli_mode or has_args:
        # Run CLI
        logger.info("Starting in CLI mode")
        cli()
    else:
        # Run web UI
        logger.info("Starting in Web UI mode")
        app = create_uploader_app()
        port = int(os.getenv("PORT") or os.getenv("BIRDNET_UPLOADER_PORT") or "7860")
        host = os.getenv("BIRDNET_UPLOADER_HOST") or "0.0.0.0"
        logger.info(f"Launching Gradio app on {host}:{port}")
        print(f"\n{'='*60}")
        print(f"BirdNET Uploader Web UI")
        print(f"Opening browser at: http://localhost:{port}")
        print(f"{'='*60}\n")
        app.launch(server_name=host, server_port=port, show_error=True)
            
except Exception as e:
    logger.error(f"FATAL ERROR: {e}")
    logger.error(traceback.format_exc())
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"ERROR: {e}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Details:\n{traceback.format_exc()}", file=sys.stderr)
    print(f"\nFor debugging, see: ~/.birdnet-uploader/logs/", file=sys.stderr)
    print(f"Or run: python debug.bat", file=sys.stderr)
    input("\nPress Enter to close...")
    sys.exit(1)
