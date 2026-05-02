import os

from src.ui.app_factory import create_app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT") or os.getenv("BIRDNET_VALIDATOR_PORT") or "7860")
    host = os.getenv("BIRDNET_VALIDATOR_HOST") or "0.0.0.0"
    app.launch(server_name=host, server_port=port)
