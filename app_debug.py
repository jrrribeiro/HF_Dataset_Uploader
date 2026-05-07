#!/usr/bin/env python3
"""
Debug wrapper for BirdNET Uploader
Captures stdout/stderr and logs errors to a file
Useful for debugging why the executable closes without visible output
"""

import os
import sys
import traceback
import logging
from datetime import datetime
from pathlib import Path

# Setup logging to file
log_dir = Path.home() / ".birdnet-uploader" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

logger.info("=" * 60)
logger.info("BirdNET Uploader Debug Session Started")
logger.info("=" * 60)
logger.info(f"Python version: {sys.version}")
logger.info(f"Executable: {sys.executable}")
logger.info(f"CWD: {os.getcwd()}")
logger.info(f"Args: {sys.argv}")
logger.info(f"Log file: {log_file}")

try:
    # Add current directory to path
    sys.path.insert(0, os.getcwd())
    
    logger.info("Importing modules...")
    from src.uploader.web_ui import create_uploader_app
    from src.uploader.main import cli
    
    logger.info("Modules imported successfully")
    
    # Determine mode
    cli_mode = os.getenv("BIRDNET_UPLOADER_CLI", "").lower() in ("1", "true", "yes")
    has_args = len(sys.argv) > 1
    
    logger.info(f"CLI mode: {cli_mode}, Has args: {has_args}")
    
    if cli_mode or has_args:
        logger.info("Running in CLI mode")
        cli()
    else:
        logger.info("Running in Web UI mode")
        app = create_uploader_app()
        port = int(os.getenv("PORT") or os.getenv("BIRDNET_UPLOADER_PORT") or "7860")
        host = os.getenv("BIRDNET_UPLOADER_HOST") or "0.0.0.0"
        
        logger.info(f"Launching Gradio app on {host}:{port}")
        app.launch(server_name=host, server_port=port, show_error=True)
        
except Exception as e:
    logger.error("=" * 60)
    logger.error(f"FATAL ERROR: {e}")
    logger.error("=" * 60)
    logger.error(traceback.format_exc())
    
    # Print to console as well
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"FATAL ERROR: {e}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(traceback.format_exc(), file=sys.stderr)
    print(f"\nError details logged to: {log_file}", file=sys.stderr)
    
    sys.exit(1)

logger.info("=" * 60)
logger.info("BirdNET Uploader Session Ended")
logger.info("=" * 60)
