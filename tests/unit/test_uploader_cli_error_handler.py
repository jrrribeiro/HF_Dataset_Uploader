from src.uploader_cli.error_handler import build_error_message
from src.uploader_cli.exceptions import AuthenticationError, UploadError


def test_build_error_message_uses_default_hint() -> None:
    message = build_error_message(AuthenticationError("Invalid token"))

    assert "Invalid token" in message
    assert "Hint:" in message
    assert "birdnet-uploader login" in message


def test_build_error_message_uses_exception_suggestion() -> None:
    message = build_error_message(
        UploadError("Upload interrupted", suggestion="Run resume with your last session id.")
    )

    assert "Upload interrupted" in message
    assert "Run resume with your last session id." in message


def test_build_error_message_for_unexpected_exception() -> None:
    message = build_error_message(RuntimeError("boom"))

    assert message == "Unexpected error: boom"
