import pytest

from src.uploader_cli.auth_service import AuthService
from src.uploader_cli.exceptions import AuthenticationError


def test_authenticate_success_stores_token(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[tuple[str, str], str] = {}

    class FakeApi:
        def whoami(self) -> dict[str, str]:
            return {"name": "alice", "email": "alice@example.com", "user_id": "u123"}

    monkeypatch.setattr("src.uploader_cli.auth_service.HfApi", lambda token: FakeApi())
    monkeypatch.setattr(
        "src.uploader_cli.auth_service.keyring.set_password",
        lambda service, account, token: store.__setitem__((service, account), token),
    )

    service = AuthService()
    user = service.authenticate(" hf_test_token ")

    assert user["username"] == "alice"
    assert user["email"] == "alice@example.com"
    assert user["user_id"] == "u123"
    assert store[(service.KEYRING_SERVICE, service.KEYRING_ACCOUNT)] == "hf_test_token"


def test_authenticate_rejects_blank_token() -> None:
    with pytest.raises(AuthenticationError, match="Token is required"):
        AuthService().authenticate("   ")


def test_authenticate_invalid_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeApi:
        def whoami(self) -> dict[str, str]:
            raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr("src.uploader_cli.auth_service.HfApi", lambda token: FakeApi())

    with pytest.raises(AuthenticationError, match="Token validation failed"):
        AuthService().authenticate("hf_invalid")


def test_require_token_returns_stored_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.uploader_cli.auth_service.keyring.get_password",
        lambda service, account: "hf_saved_token",
    )

    assert AuthService().require_token() == "hf_saved_token"


def test_require_token_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.uploader_cli.auth_service.keyring.get_password",
        lambda service, account: None,
    )

    with pytest.raises(AuthenticationError, match="No stored token found"):
        AuthService().require_token()


def test_clear_token_ignores_missing_password(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePasswordDeleteError(Exception):
        pass

    class FakeErrors:
        PasswordDeleteError = FakePasswordDeleteError

    def raise_delete_error(service: str, account: str) -> None:
        raise FakePasswordDeleteError("not found")

    monkeypatch.setattr("src.uploader_cli.auth_service.keyring.errors", FakeErrors)
    monkeypatch.setattr(
        "src.uploader_cli.auth_service.keyring.delete_password",
        raise_delete_error,
    )

    AuthService().clear_token()
