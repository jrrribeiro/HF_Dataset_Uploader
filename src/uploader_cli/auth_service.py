from __future__ import annotations

from typing import Any

import keyring
from huggingface_hub import HfApi

from .config import KEYRING_ACCOUNT, KEYRING_SERVICE
from .exceptions import AuthenticationError


class AuthService:
    """Authenticate and securely store Hugging Face tokens."""

    KEYRING_SERVICE = KEYRING_SERVICE
    KEYRING_ACCOUNT = KEYRING_ACCOUNT

    def authenticate(self, token: str) -> dict[str, Any]:
        token = token.strip()
        if not token:
            raise AuthenticationError("Token is required")

        try:
            api = HfApi(token=token)
            whoami = api.whoami()
        except Exception as exc:  # pragma: no cover - external API behavior
            raise AuthenticationError(f"Token validation failed: {exc}") from exc

        try:
            keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_ACCOUNT, token)
        except Exception as exc:  # pragma: no cover - backend-specific behavior
            raise AuthenticationError(f"Token validated, but could not be saved securely: {exc}") from exc

        return {
            "username": whoami.get("name") or "unknown",
            "email": whoami.get("email", ""),
            "user_id": whoami.get("id") or whoami.get("user_id", ""),
        }

    def get_token(self) -> str | None:
        try:
            return keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_ACCOUNT)
        except Exception as exc:  # pragma: no cover - backend-specific behavior
            raise AuthenticationError(f"Could not read stored token: {exc}") from exc

    def require_token(self) -> str:
        token = self.get_token()
        if not token:
            raise AuthenticationError("No stored token found. Run 'birdnet-uploader login' first.")
        return token

    def clear_token(self) -> None:
        try:
            keyring.delete_password(self.KEYRING_SERVICE, self.KEYRING_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            return
        except Exception as exc:  # pragma: no cover - backend-specific behavior
            raise AuthenticationError(f"Could not clear stored token: {exc}") from exc
        else:
            return
