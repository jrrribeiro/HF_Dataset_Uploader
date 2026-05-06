from __future__ import annotations

from .exceptions import (
	AuthenticationError,
	RepositoryError,
	SessionError,
	UploaderCliError,
	UploadError,
	ValidationError,
)


ERROR_HINTS: dict[type[UploaderCliError], str] = {
	AuthenticationError: "Run 'birdnet-uploader login' and verify your Hugging Face token.",
	RepositoryError: "Check repository id format (owner/name) and write permissions on Hugging Face.",
	SessionError: "Verify session id and local checkpoint files under .birdnet-uploader/sessions.",
	ValidationError: "Fix invalid paths or inputs and retry the command.",
	UploadError: "Check your network and run the command again to resume from checkpoint.",
}


def build_error_message(error: Exception) -> str:
	if isinstance(error, UploaderCliError):
		hint = error.suggestion or ERROR_HINTS.get(type(error), "")
		if hint:
			return f"{error} Hint: {hint}"
		return str(error)

	return f"Unexpected error: {error}"
