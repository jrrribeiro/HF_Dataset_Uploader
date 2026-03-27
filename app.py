import os

from src.ui.upload_app_factory import build_upload_app


if __name__ == "__main__":
    app = build_upload_app()
    port = int(os.getenv("PORT") or os.getenv("BIRDNET_UPLOADER_PORT", "7860"))
    app.launch(server_name="0.0.0.0", server_port=port, show_api=False)
