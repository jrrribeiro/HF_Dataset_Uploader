class UploaderCliError(Exception):
	"""Base exception for uploader CLI."""

	def __init__(self, message: str, *, suggestion: str = ""):
		super().__init__(message)
		self.suggestion = suggestion


class AuthenticationError(UploaderCliError):
	"""Raised when Hugging Face authentication fails."""


class RepositoryError(UploaderCliError):
	"""Raised for dataset repository failures."""


class SessionError(UploaderCliError):
	"""Raised when session state cannot be read or written."""


class ValidationError(UploaderCliError):
	"""Raised when user input or local resources are invalid."""


class UploadError(UploaderCliError):
	"""Raised when upload operations fail after retries."""
