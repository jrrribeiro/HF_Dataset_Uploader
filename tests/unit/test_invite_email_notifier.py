import json
from datetime import datetime

from src.config.runtime_config import RuntimeConfig
from src.services.invite_email_notifier import EmailJSInviteEmailNotifier, InviteEmailPayload


class _FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status = status_code

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = exc_type
        _ = exc
        _ = tb

    def getcode(self) -> int:
        return self.status


def test_runtime_config_reads_emailjs_settings(monkeypatch) -> None:
    monkeypatch.setenv("BIRDNET_EMAILJS_ENABLED", "true")
    monkeypatch.setenv("BIRDNET_EMAILJS_SERVICE_ID", "service_123")
    monkeypatch.setenv("BIRDNET_EMAILJS_TEMPLATE_ID", "template_456")
    monkeypatch.setenv("BIRDNET_EMAILJS_TEMPLATE_ID_USERNAME_ONLY", "template_user")
    monkeypatch.setenv("BIRDNET_EMAILJS_TEMPLATE_ID_EMAIL_ONLY", "template_email")
    monkeypatch.setenv("BIRDNET_EMAILJS_TEMPLATE_ID_DUAL", "template_dual")
    monkeypatch.setenv("BIRDNET_EMAILJS_PUBLIC_KEY", "public_789")
    monkeypatch.setenv("BIRDNET_EMAILJS_ENDPOINT", "https://example.org/emailjs")
    monkeypatch.setenv("BIRDNET_EMAILJS_TIMEOUT_SECONDS", "33")

    config = RuntimeConfig.from_env()

    assert config.emailjs_enabled is True
    assert config.emailjs_service_id == "service_123"
    assert config.emailjs_template_id == "template_456"
    assert config.emailjs_template_id_username_only == "template_user"
    assert config.emailjs_template_id_email_only == "template_email"
    assert config.emailjs_template_id_dual == "template_dual"
    assert config.emailjs_public_key == "public_789"
    assert config.emailjs_endpoint == "https://example.org/emailjs"
    assert config.emailjs_timeout_seconds == 33


def test_emailjs_notifier_posts_expected_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.headers)
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(200)

    monkeypatch.setattr("src.services.invite_email_notifier.request.urlopen", fake_urlopen)

    notifier = EmailJSInviteEmailNotifier(
        sender_email="BirdNET Validator",
        service_id="service_123",
        template_id="template_456",
        public_key="public_789",
        template_id_username_only="template_user",
        template_id_email_only="template_email",
        template_id_dual="template_dual",
        endpoint="https://example.org/emailjs",
        timeout_seconds=12,
    )
    payload = InviteEmailPayload(
        invitee_username="alice",
        invitee_email="alice@example.org",
        project_slug="kenya-2024",
        role="validator",
        invited_by="owner",
        expires_at=datetime(2026, 3, 25, 10, 0, 0),
        login_url="https://space.example.org",
    )

    ok, message = notifier.send(payload)

    assert ok is True
    assert "alice@example.org" in message
    assert captured["url"] == "https://example.org/emailjs"
    assert captured["timeout"] == 12
    assert captured["payload"]["service_id"] == "service_123"
    assert captured["payload"]["template_id"] == "template_dual"
    assert captured["payload"]["user_id"] == "public_789"
    assert captured["payload"]["template_params"]["to_email"] == "alice@example.org"
    assert captured["payload"]["template_params"]["invite_link"] == "https://space.example.org"


def test_emailjs_notifier_uses_mode_specific_template(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(200)

    monkeypatch.setattr("src.services.invite_email_notifier.request.urlopen", fake_urlopen)

    notifier = EmailJSInviteEmailNotifier(
        sender_email="BirdNET Validator",
        service_id="service_123",
        template_id="template_default",
        public_key="public_789",
        template_id_email_only="template_email_only",
        template_id_dual="template_dual",
        endpoint="https://example.org/emailjs",
    )

    payload_email_only = InviteEmailPayload(
        invitee_username=None,
        invitee_email="emailonly@example.org",
        project_slug="kenya-2024",
        role="validator",
        invited_by="owner",
        expires_at=datetime(2026, 3, 25, 10, 0, 0),
        login_url="https://space.example.org",
    )
    ok, _ = notifier.send(payload_email_only)
    assert ok is True
    assert captured["payload"]["template_id"] == "template_email_only"
    assert captured["payload"]["template_params"]["invite_mode"] == "email_only"

    payload_dual = InviteEmailPayload(
        invitee_username="alice",
        invitee_email="alice@example.org",
        project_slug="kenya-2024",
        role="validator",
        invited_by="owner",
        expires_at=datetime(2026, 3, 25, 10, 0, 0),
        login_url="https://space.example.org",
    )
    ok, _ = notifier.send(payload_dual)
    assert ok is True
    assert captured["payload"]["template_id"] == "template_dual"
    assert captured["payload"]["template_params"]["invite_mode"] == "dual"
