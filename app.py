import os
import sys

from src.uploader.web_ui import create_uploader_app
from src.uploader.main import cli


if __name__ == "__main__":
    # If command-line arguments are provided (other than just the script name),
    # or if the BIRDNET_UPLOADER_CLI environment variable is set,
    # run the CLI instead of the web UI
    cli_mode = os.getenv("BIRDNET_UPLOADER_CLI", "").lower() in ("1", "true", "yes")
    has_args = len(sys.argv) > 1
    
    if cli_mode or has_args:
        # Run CLI
        cli()
    else:
        # Run web UI
        app = create_uploader_app()
        port = int(os.getenv("PORT") or os.getenv("BIRDNET_UPLOADER_PORT") or "7860")
        host = os.getenv("BIRDNET_UPLOADER_HOST") or "0.0.0.0"
        app.launch(server_name=host, server_port=port)
