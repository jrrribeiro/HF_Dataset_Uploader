"""Unit tests for AuthService and ACL enforcement."""

import pytest
from datetime import UTC, datetime, timedelta

from src.auth.auth_service import AuthService, Session, UserProjectAccess, UserProfile
from src.domain.models import Role


class TestAuthService:
    """Test AuthService functionality."""

    @pytest.fixture
    def auth_service(self):
        """Create a test AuthService instance."""
        return AuthService(session_ttl_minutes=120)

    @pytest.fixture
    def setup_users(self, auth_service):
        """Setup test users with project access."""
        auth_service.register_user_project_access(
            "admin_user",
            {"kenya-2024": Role.admin, "nairobi-2023": Role.admin},
        )
        auth_service.register_user_project_access(
            "validator1",
            {"kenya-2024": Role.validator, "nairobi-2023": Role.validator},
        )
        auth_service.register_user_project_access(
            "validator2",
            {"kenya-2024": Role.validator},
        )
        auth_service.register_user_project_access(
            "inactive_user",
            {"kenya-2024": Role.validator},
        )
        auth_service.set_user_active("inactive_user", False)

    def test_login_success(self, auth_service, setup_users):
        """Test successful login."""
        session = auth_service.login("admin_user")

        assert session is not None
        assert session.username == "admin_user"
        assert session.role == Role.admin
        assert len(session.authorized_projects) == 2
        assert "kenya-2024" in session.authorized_projects
        assert "nairobi-2023" in session.authorized_projects

    def test_login_nonexistent_user(self, auth_service):
        """Test login with nonexistent user."""
        session = auth_service.login("nonexistent")
        assert session is None

    def test_login_inactive_user(self, auth_service, setup_users):
        """Test login with inactive user."""
        session = auth_service.login("inactive_user")
        assert session is None

    def test_validator_role_assigned_correctly(self, auth_service, setup_users):
        """Test validator role is assigned when user has only validator projects."""
        session = auth_service.login("validator1")

        assert session is not None
        assert session.role == Role.validator

    def test_admin_role_takes_precedence(self, auth_service, setup_users):
        """Test admin role takes precedence over validator."""
        session = auth_service.login("admin_user")

        assert session is not None
        assert session.username == "admin_user"
        assert session.role == Role.admin

    def test_session_expiration(self, auth_service, setup_users):
        """Test that expired sessions are handled."""
        # Create a service with very short TTL
        short_ttl_service = AuthService(session_ttl_minutes=0)
        short_ttl_service.register_user_project_access(
            "test_user",
            {"project-1": Role.validator},
        )
        session = short_ttl_service.login("test_user")

        assert session is not None

        # Manually set expiration to past
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        # Try to retrieve expired session
        retrieved = short_ttl_service.get_session(session.session_id)
        assert retrieved is None

    def test_get_session_updates_activity(self, auth_service, setup_users):
        """Test that retrieving a session updates its last_activity."""
        session = auth_service.login("validator1")
        original_activity = session.last_activity

        # Wait a moment (in real tests, would mock datetime)
        import time
        time.sleep(0.1)

        # Retrieve session
        retrieved = auth_service.get_session(session.session_id)

        assert retrieved is not None
        assert retrieved.last_activity >= original_activity

    def test_logout_invalidates_session(self, auth_service, setup_users):
        """Test that logout removes a session."""
        session = auth_service.login("validator1")
        session_id = session.session_id

        # Verify session exists
        assert auth_service.get_session(session_id) is not None

        # Logout
        auth_service.logout(session_id)

        # Verify session is gone
        assert auth_service.get_session(session_id) is None

    def test_is_user_authorized_for_project(self, auth_service, setup_users):
        """Test project authorization check."""
        assert auth_service.is_user_authorized_for_project("admin_user", "kenya-2024")
        assert auth_service.is_user_authorized_for_project("admin_user", "nairobi-2023")
        assert auth_service.is_user_authorized_for_project("validator1", "kenya-2024")
        assert not auth_service.is_user_authorized_for_project("validator2", "nairobi-2023")

    def test_is_user_authorized_inactive(self, auth_service, setup_users):
        """Test that inactive users are not authorized."""
        assert not auth_service.is_user_authorized_for_project("inactive_user", "kenya-2024")

    def test_get_user_role_for_project(self, auth_service, setup_users):
        """Test retrieving user's role for a specific project."""
        admin_role = auth_service.get_user_role_for_project("admin_user", "kenya-2024")
        assert admin_role == Role.admin

        validator_role = auth_service.get_user_role_for_project(
            "validator1", "kenya-2024"
        )
        assert validator_role == Role.validator

        no_access = auth_service.get_user_role_for_project("validator2", "nairobi-2023")
        assert no_access is None

    def test_list_user_projects(self, auth_service, setup_users):
        """Test listing projects a user has access to."""
        admin_projects = auth_service.list_user_projects("admin_user")
        assert len(admin_projects) == 2
        assert "kenya-2024" in admin_projects
        assert "nairobi-2023" in admin_projects

        validator2_projects = auth_service.list_user_projects("validator2")
        assert len(validator2_projects) == 1
        assert "kenya-2024" in validator2_projects

    def test_list_projects_for_inactive_user(self, auth_service, setup_users):
        """Test that inactive users have no accessible projects."""
        projects = auth_service.list_user_projects("inactive_user")
        assert len(projects) == 0

    def test_cleanup_expired_sessions(self, auth_service, setup_users):
        """Test cleanup of expired sessions."""
        session1 = auth_service.login("admin_user")
        session2 = auth_service.login("validator1")

        # Expire session1
        session1.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        # Cleanup
        auth_service.cleanup_expired_sessions()

        # session1 should be gone
        assert auth_service.get_session(session1.session_id) is None
        # session2 should still be there
        assert auth_service.get_session(session2.session_id) is not None

    def test_set_user_active(self, auth_service, setup_users):
        """Test disabling and enabling users."""
        # User is initially inactive
        assert not auth_service.is_user_authorized_for_project("inactive_user", "kenya-2024")

        # Reactivate
        auth_service.set_user_active("inactive_user", True)
        assert auth_service.is_user_authorized_for_project("inactive_user", "kenya-2024")

        # Deactivate again
        auth_service.set_user_active("inactive_user", False)
        assert not auth_service.is_user_authorized_for_project("inactive_user", "kenya-2024")

    def test_set_user_inactive_revokes_existing_sessions(self, auth_service):
        auth_service.register_user_project_access("active_user", {"project-1": Role.validator})
        session = auth_service.login("active_user")
        assert session is not None

        auth_service.set_user_active("active_user", False)

        assert auth_service.get_session(session.session_id) is None

    def test_login_with_hf_token_stores_user_token_and_email(self, monkeypatch):
        class FakeApi:
            def whoami(self, token: str):
                assert token == "hf_test_token"
                return {"name": "hf_user", "email": "hf_user@example.org"}

        monkeypatch.setattr("src.auth.auth_service.HfApi", lambda: FakeApi())

        service = AuthService()
        session, message = service.login_with_hf_token("hf_test_token")

        assert session is not None
        assert "Welcome" in message
        assert service.get_hf_token_for_user("hf_user") == "hf_test_token"
        assert service.get_known_email_for_user("hf_user") == "hf_user@example.org"

    def test_register_user_project_access_update(self, auth_service):
        """Test updating user's project access."""
        auth_service.register_user_project_access(
            "user1", {"project-1": Role.validator}
        )

        projects = auth_service.list_user_projects("user1")
        assert projects == ["project-1"]

        # Update to add more projects
        auth_service.register_user_project_access(
            "user1",
            {"project-1": Role.validator, "project-2": Role.admin},
        )

        projects = auth_service.list_user_projects("user1")
        assert len(projects) == 2
        assert auth_service.get_user_role_for_project("user1", "project-2") == Role.admin

    def test_upsert_user_project_role_creates_and_updates_user(self, auth_service):
        auth_service.upsert_user_project_role("new_user", "project-1", Role.validator)
        assert auth_service.get_user_role_for_project("new_user", "project-1") == Role.validator

        auth_service.upsert_user_project_role("new_user", "project-1", Role.admin)
        assert auth_service.get_user_role_for_project("new_user", "project-1") == Role.admin

    def test_remove_user_project_role(self, auth_service):
        auth_service.register_user_project_access("temp_user", {"project-1": Role.validator})

        removed = auth_service.remove_user_project_role("temp_user", "project-1")
        assert removed is True
        assert auth_service.get_user_role_for_project("temp_user", "project-1") is None

        removed_again = auth_service.remove_user_project_role("temp_user", "project-1")
        assert removed_again is False

    def test_remove_user_project_role_clears_matching_pending_invite(self, auth_service):
        auth_service.register_user_project_access("temp_user", {"project-1": Role.validator})
        ok, _ = auth_service.create_project_invite(
            project_slug="project-1",
            role=Role.validator,
            invited_by="owner",
                    username="temp_user",
        )
        assert ok is True

        removed = auth_service.remove_user_project_role("temp_user", "project-1")
        assert removed is True
        assert auth_service.list_pending_invites("temp_user") == []

    def test_remove_user_project_role_refreshes_active_session(self, auth_service):
        auth_service.register_user_project_access("temp_user", {"project-1": Role.validator, "project-2": Role.validator})
        session = auth_service.login("temp_user")
        assert session is not None
        assert "project-1" in session.authorized_projects

        removed = auth_service.remove_user_project_role("temp_user", "project-1")
        assert removed is True

        refreshed = auth_service.get_session(session.session_id)
        assert refreshed is not None
        assert "project-1" not in refreshed.authorized_projects
        assert "project-2" in refreshed.authorized_projects

    def test_list_usernames_honors_active_filter(self, auth_service):
        auth_service.register_user_project_access("active_user", {"project-1": Role.validator})
        auth_service.register_user_project_access("inactive_user", {"project-1": Role.validator})
        auth_service.set_user_active("inactive_user", False)

        active_only = auth_service.list_usernames()
        with_inactive = auth_service.list_usernames(include_inactive=True)

        assert "active_user" in active_only
        assert "inactive_user" not in active_only
        assert "inactive_user" in with_inactive

    def test_session_isolation_between_users(self, auth_service, setup_users):
        """Test that sessions are isolated between users."""
        session_admin = auth_service.login("admin_user")
        session_validator = auth_service.login("validator1")

        assert session_admin.session_id != session_validator.session_id
        assert session_admin.username != session_validator.username
        assert session_admin.role != session_validator.role

        # Sessions should remain independent
        auth_service.logout(session_admin.session_id)
        assert auth_service.get_session(session_validator.session_id) is not None

    def test_invite_accept_flow_grants_access(self, auth_service):
        auth_service.register_user_project_access("owner", {"proj-1": Role.admin})

        ok, _ = auth_service.create_project_invite(
            project_slug="proj-1",
                        username="validator_new",
            role=Role.validator,
            invited_by="owner",
        )
        assert ok is True

        pending = auth_service.list_pending_invites("validator_new")
        assert len(pending) == 1
        assert pending[0].project_slug == "proj-1"

        accepted, _ = auth_service.accept_project_invite("validator_new", "proj-1")
        assert accepted is True
        assert auth_service.get_user_role_for_project("validator_new", "proj-1") == Role.validator
        assert auth_service.list_pending_invites("validator_new") == []

    def test_invited_user_can_login_before_accepting(self, auth_service):
        ok, _ = auth_service.create_project_invite(
                        username="pending_user",
            project_slug="proj-1",
            role=Role.validator,
            invited_by="owner",
        )
        assert ok is True

        session = auth_service.login_internal("pending_user")
        assert session is not None
        assert session.username == "pending_user"
        assert session.authorized_projects == []

    def test_email_only_invite_is_visible_and_accepts_for_known_email(self, auth_service):
        ok, _ = auth_service.create_project_invite(
            project_slug="proj-email",
            role=Role.validator,
            invited_by="owner",
            invitee_email="invitee@example.org",
        )
        assert ok is True

        auth_service._user_profiles["invitee_user"] = UserProfile(
            username="invitee_user",
            hf_email="invitee@example.org",
        )

        pending = auth_service.list_pending_invites("invitee_user")
        assert len(pending) == 1
        assert pending[0].project_slug == "proj-email"

        accepted, _ = auth_service.accept_project_invite("invitee_user", "proj-email")
        assert accepted is True
        assert auth_service.get_user_role_for_project("invitee_user", "proj-email") == Role.validator
        assert auth_service.list_pending_invites("invitee_user") == []

    def test_reject_invite_removes_pending(self, auth_service):
        ok, _ = auth_service.create_project_invite(
                        username="pending_user",
            project_slug="proj-1",
            role=Role.validator,
            invited_by="owner",
        )
        assert ok is True

        rejected, _ = auth_service.reject_project_invite("pending_user", "proj-1")
        assert rejected is True
        assert auth_service.list_pending_invites("pending_user") == []

    def test_accept_all_project_invites(self, auth_service):
        ok1, _ = auth_service.create_project_invite(
                        username="pending_user",
            project_slug="proj-1",
            role=Role.validator,
            invited_by="owner",
        )
        ok2, _ = auth_service.create_project_invite(
            project_slug="proj-2",
            role=Role.admin,
                        username="pending_user",
            invited_by="owner",
        )
        assert ok1 and ok2

        accepted, failed, _ = auth_service.accept_all_project_invites("pending_user")
        assert accepted == 2
        assert failed == 0
        assert auth_service.get_user_role_for_project("pending_user", "proj-1") == Role.validator
        assert auth_service.get_user_role_for_project("pending_user", "proj-2") == Role.admin

    def test_revoke_project_invite(self, auth_service):
        ok, _ = auth_service.create_project_invite(
                        username="pending_user",
            project_slug="proj-1",
            role=Role.validator,
            invited_by="owner",
        )
        assert ok is True

        revoked, _ = auth_service.revoke_project_invite("pending_user", "proj-1")
        assert revoked is True
        assert auth_service.list_pending_invites("pending_user") == []

    def test_expired_invite_is_pruned(self):
        service = AuthService(session_ttl_minutes=120, invite_ttl_hours=1)
        ok, _ = service.create_project_invite(
                        username="pending_user",
            project_slug="proj-1",
            role=Role.validator,
            invited_by="owner",
        )
        assert ok is True

        invite = service.list_pending_invites("pending_user")[0]
        invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        assert service.list_pending_invites("pending_user") == []

    def test_remove_project_from_all_users_updates_acl_and_session(self, auth_service):
        auth_service.register_user_project_access(
            "admin_user",
            {"proj-a": Role.admin, "proj-b": Role.admin},
        )
        auth_service.register_user_project_access(
            "validator_user",
            {"proj-a": Role.validator},
        )
        admin_session = auth_service.login("admin_user")
        validator_session = auth_service.login("validator_user")

        removed = auth_service.remove_project_from_all_users("proj-a")

        assert removed == 2
        assert auth_service.get_user_role_for_project("admin_user", "proj-a") is None
        assert auth_service.get_user_role_for_project("validator_user", "proj-a") is None
        assert auth_service.get_user_role_for_project("admin_user", "proj-b") == Role.admin
        assert admin_session is not None and "proj-a" not in admin_session.authorized_projects
        assert validator_session is not None and "proj-a" not in validator_session.authorized_projects

    def test_revoke_all_invites_for_project(self, auth_service):
        auth_service.create_project_invite(project_slug="proj-a", role=Role.validator, invited_by="owner", username="u1")
        auth_service.create_project_invite(project_slug="proj-a", role=Role.validator, invited_by="owner", username="u2")
        auth_service.create_project_invite(project_slug="proj-b", role=Role.validator, invited_by="owner", username="u3")

        revoked = auth_service.revoke_all_invites_for_project("proj-a")

        assert revoked == 2
        assert auth_service.list_pending_invites("u1") == []
        assert auth_service.list_pending_invites("u2") == []
        assert len(auth_service.list_pending_invites("u3")) == 1


class TestUserProjectAccess:
    """Test UserProjectAccess model."""

    def test_user_project_access_creation(self):
        """Test creating user project access."""
        access = UserProjectAccess(
            username="test_user",
            project_slugs={"proj-1": Role.admin, "proj-2": Role.validator},
        )

        assert access.username == "test_user"
        assert len(access.project_slugs) == 2
        assert access.is_active is True

    def test_user_project_access_deactivation(self):
        """Test deactivating user."""
        access = UserProjectAccess(
            username="test_user",
            project_slugs={"proj-1": Role.validator},
        )

        assert access.is_active is True

        access.is_active = False
        assert access.is_active is False


class TestSessionModel:
    """Test Session model."""

    def test_session_creation(self):
        """Test creating a session."""
        now = datetime.now(UTC)
        session = Session(
            session_id="test-session-123",
            username="test_user",
            role=Role.validator,
            authorized_projects=["proj-1", "proj-2"],
            created_at=now,
            last_activity=now,
            expires_at=now + timedelta(hours=2),
        )

        assert session.session_id == "test-session-123"
        assert session.username == "test_user"
        assert session.role == Role.validator
        assert len(session.authorized_projects) == 2

    def test_session_expiration_check(self):
        """Test session expiration detection."""
        now = datetime.now(UTC)

        # Not expired
        session = Session(
            session_id="test",
            username="user",
            role=Role.validator,
            authorized_projects=[],
            created_at=now,
            last_activity=now,
            expires_at=now + timedelta(hours=1),
        )

        assert not session.is_expired()

        # Expired
        session.expires_at = now - timedelta(seconds=1)
        assert session.is_expired()

    def test_session_activity_update(self):
        """Test updating session activity."""
        now = datetime.now(UTC)
        session = Session(
            session_id="test",
            username="user",
            role=Role.validator,
            authorized_projects=[],
            created_at=now,
            last_activity=now,
            expires_at=now + timedelta(minutes=120),
        )

        original_activity = session.last_activity

        # Update activity with 30-minute TTL
        import time
        time.sleep(0.1)
        session.update_activity(ttl_minutes=30)

        assert session.last_activity >= original_activity
        # The new expiration should be approximately 30 minutes from now
        expected_expires = datetime.now(UTC) + timedelta(minutes=30)
        # Allow 5 seconds of variance due to timing
        assert abs((session.expires_at - expected_expires).total_seconds()) < 5
