from dataclasses import dataclass
from datetime import UTC, datetime

from src.auth.auth_service import AuthService
from src.domain.models import Project, Role
from src.services.invite_email_notifier import InviteEmailNotifier, InviteEmailPayload
from src.ui.admin_panel import AdminPanelManager


@dataclass
class _FakeNotifier(InviteEmailNotifier):
    calls: int = 0

    def send(self, payload: InviteEmailPayload) -> tuple[bool, str]:
        self.calls += 1
        assert payload.invitee_email
        assert payload.project_slug
        return True, "email-ok"


def _make_project(slug: str, visibility: str, owner: str | None) -> Project:
    return Project(
        project_slug=slug,
        name=slug,
        dataset_repo_id=f"org/{slug}",
        visibility=visibility,
        owner_username=owner,
        active=True,
    )


def test_private_project_allows_only_owner_assignment() -> None:
    auth = AuthService()
    auth.register_user_project_access("owner", {"private-proj": Role.admin})
    auth.register_user_project_access("intruder", {})
    notifier = _FakeNotifier()
    manager = AdminPanelManager(auth, invite_notifier=notifier)
    manager.register_project(_make_project("private-proj", "private", "owner"))

    ok, message = manager.assign_user_to_project("owner", "intruder", "private-proj", "validator")

    assert ok is False
    assert "only allow the owner" in message


def test_private_project_without_owner_is_rejected() -> None:
    auth = AuthService()
    auth.register_user_project_access("admin", {"broken-private": Role.admin})
    notifier = _FakeNotifier()
    manager = AdminPanelManager(auth, invite_notifier=notifier)
    manager.register_project(_make_project("broken-private", "private", None))

    ok, message = manager.assign_user_to_project("admin", "admin", "broken-private", "admin")

    assert ok is False
    assert "owner is required" in message


def test_invite_requires_project_admin_actor() -> None:
    auth = AuthService()
    auth.register_user_project_access("owner", {"collab-proj": Role.admin})
    auth.register_user_project_access("viewer", {"collab-proj": Role.validator})
    notifier = _FakeNotifier()
    manager = AdminPanelManager(auth, invite_notifier=notifier)
    manager.register_project(_make_project("collab-proj", "collaborative", "owner"))

    ok, message = manager.invite_user_to_project(
        actor_username="viewer",
        invited_by="viewer",
        username="new_user",
        invitee_email="new_user@example.org",
        project_slug="collab-proj",
        role="validator",
    )

    assert ok is False
    assert "Access denied" in message


def test_collaborative_invite_sends_email_when_address_present() -> None:
    auth = AuthService()
    auth.register_user_project_access("owner", {"collab-proj": Role.admin})
    notifier = _FakeNotifier()
    manager = AdminPanelManager(auth, invite_notifier=notifier)
    manager.register_project(_make_project("collab-proj", "collaborative", "owner"))

    ok, message = manager.invite_user_to_project(
        actor_username="owner",
        invited_by="owner",
        username="new_user",
        invitee_email="new_user@example.org",
        project_slug="collab-proj",
        role="validator",
    )

    assert ok is True
    assert "Dual invite" in message
    assert notifier.calls == 1


def test_collaborative_invite_requires_email_if_unknown_username() -> None:
    auth = AuthService()
    auth.register_user_project_access("owner", {"collab-proj": Role.admin})
    notifier = _FakeNotifier()
    manager = AdminPanelManager(auth, invite_notifier=notifier)
    manager.register_project(_make_project("collab-proj", "collaborative", "owner"))

    ok, message = manager.invite_user_to_project(
        actor_username="owner",
        invited_by="owner",
        username="new_user",
        invitee_email="",
        project_slug="collab-proj",
        role="validator",
    )

    # Username-only invites are now allowed (scenario 1: internal only)
    assert ok is True
    # Should be internal-only mode since no email was provided
    assert "Username Only" in message
    # Notifier should not be called for email-less invites
    assert notifier.calls == 0


def test_collaborative_invite_email_only() -> None:
    """Test scenario 2: email-only invite (no username known)."""
    auth = AuthService()
    auth.register_user_project_access("owner", {"collab-proj": Role.admin})
    notifier = _FakeNotifier()
    manager = AdminPanelManager(auth, invite_notifier=notifier)
    manager.register_project(_make_project("collab-proj", "collaborative", "owner"))

    ok, message = manager.invite_user_to_project(
        actor_username="owner",
        invited_by="owner",
        username=None,
        invitee_email="unknown@example.org",
        project_slug="collab-proj",
        role="validator",
    )

    assert ok is True
    assert "Email Only" in message
    assert notifier.calls == 1


def test_collaborative_invite_requires_username_or_email() -> None:
    """Test that at least username or email is required."""
    auth = AuthService()
    auth.register_user_project_access("owner", {"collab-proj": Role.admin})
    notifier = _FakeNotifier()
    manager = AdminPanelManager(auth, invite_notifier=notifier)
    manager.register_project(_make_project("collab-proj", "collaborative", "owner"))

    ok, message = manager.invite_user_to_project(
        actor_username="owner",
        invited_by="owner",
        username="",
        invitee_email="",
        project_slug="collab-proj",
        role="validator",
    )

    assert ok is False
    assert "provide either" in message.lower()
