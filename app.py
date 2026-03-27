import os

from gradio_client import utils as gradio_client_utils

from src.ui.upload_app_factory import build_upload_app


def _patch_gradio_schema_bool_handling() -> None:
    original_get_type = gradio_client_utils.get_type

    def safe_get_type(schema):
        if isinstance(schema, bool):
            return "Any" if schema else "None"
        return original_get_type(schema)

    gradio_client_utils.get_type = safe_get_type


if __name__ == "__main__":
    _patch_gradio_schema_bool_handling()
    app = build_upload_app()
    port = int(os.getenv("BIRDNET_UPLOADER_PORT", "7862"))
    app.launch(server_name="0.0.0.0", server_port=port, show_api=False)
