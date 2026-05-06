import os

from src.uploader.web_ui import create_uploader_app


if __name__ == "__main__":
    app = create_uploader_app()
    port = int(os.getenv("PORT") or os.getenv("BIRDNET_UPLOADER_PORT") or "7860")
    host = os.getenv("BIRDNET_UPLOADER_HOST") or "0.0.0.0"
    app.launch(server_name=host, server_port=port)
