"""Gradio admin panel for managing projects and user assignments."""

from typing import List, Tuple

import gradio as gr

from src.auth.auth_service import AuthService, Session
from src.domain.models import Project, Role
from src.services.invite_email_notifier import InviteEmailNotifier, InviteEmailPayload


class AdminPanelManager:
    """Management backend for the admin panel."""

    def __init__(
        self,
        auth_service: AuthService,
        invite_notifier: InviteEmailNotifier,
        invite_login_url: str = "",
    ):
        """Initialize admin panel manager.

        Args:
            auth_service: AuthService instance
            invite_notifier: InviteEmailNotifier for sending invites
            invite_login_url: URL to login page for invite emails
        """
        self.auth_service = auth_service
        self._projects: dict[str, Project] = {}  # project_slug -> Project
        self.invite_notifier = invite_notifier
        self.invite_login_url = (invite_login_url or "").strip()

    def _can_admin_project(self, actor_username: str, project_slug: str) -> bool:
        return self.auth_service.get_user_role_for_project(actor_username, project_slug) == Role.admin

    def register_project(self, project: Project) -> bool:
        """Register a new project (idempotent).

        Args:
            project: Project to register

        Returns:
            True if new, False if already existed
        """
        if project.project_slug in self._projects:
            return False

        self._projects[project.project_slug] = project
        return True

    def list_projects(self) -> List[dict]:
        """List all projects as dictionaries for Gradio display.

        Returns:
            List of project dicts with slug, name, repo_id, active status
        """
        return [
            {
                "project_id": p.project_id,
                "project_slug": p.project_slug,
                "name": p.name,
                "dataset_repo_id": p.dataset_repo_id,
                "visibility": p.visibility,
                "owner_username": p.owner_username,
                "dataset_token": p.dataset_token,
                "dataset_token_set": bool((p.dataset_token or "").strip()),
                "active": p.active,
            }
            for p in self._projects.values()
        ]

    def get_project(self, project_slug: str) -> Project | None:
        """Get project by slug.

        Args:
            project_slug: Project slug

        Returns:
            Project if found, None otherwise
        """
        return self._projects.get(project_slug)

    def list_users_for_project(self, project_slug: str) -> List[dict]:
        """List all users assigned to a project.

        Args:
            project_slug: Project slug

        Returns:
            List of dicts with username and role
        """
        result = []
        for username in self.auth_service.list_usernames(include_inactive=True):
            role = self.auth_service.get_user_role_for_project(username, project_slug)
            if role is not None:
                result.append({"username": username, "role": role.value})

        return result

    def assign_user_to_project(
        self, actor_username: str, username: str, project_slug: str, role: str
    ) -> Tuple[bool, str]:
        """Assign a user to a project with a role.

        Args:
            username: Username
            project_slug: Project slug
            role: "admin" or "validator"

        Returns:
            Tuple of (success, message)
        """
        if project_slug not in self._projects:
            return False, f"Project '{project_slug}' not found"

        if not self._can_admin_project(actor_username, project_slug):
            return False, "Access denied: admin role required for this project"

        if role not in ["admin", "validator"]:
            return False, f"Invalid role: {role}"

        project = self._projects[project_slug]
        owner = (project.owner_username or "").strip()
        if project.visibility == "private":
            if not owner:
                return False, "Private project is misconfigured: owner is required"
            if username != owner:
                return False, "Private projects only allow the owner"

        self.auth_service.upsert_user_project_role(username, project_slug, Role(role))

        return True, f"✅ Assigned {username} to {project_slug} as {role}"

    def invite_user_to_project(
        self,
        actor_username: str,
        invited_by: str,
        username: str | None = None,
        invitee_email: str | None = None,
        project_slug: str | None = None,
        role: str = "validator",
    ) -> Tuple[bool, str]:
        """Invite a user to a project. Supports 3 scenarios:
        
        1. Username only: internal app invite (no email)
        2. Email only: external email-based invite
        3. Both: dual invite (internal + email)
        
        Args:
            actor_username: User performing the action (must be admin)
            invited_by: Username of the inviter
            username: (Optional) HF username of invitee
            invitee_email: (Optional) Email of invitee
            project_slug: Project slug
            role: Role to assign ("admin" or "validator")
            
        Returns:
            Tuple of (success, message)
        """
        if not project_slug or project_slug not in self._projects:
            return False, f"Project '{project_slug}' not found"

        if not self._can_admin_project(actor_username, project_slug):
            return False, "Access denied: admin role required for this project"

        if role not in ["admin", "validator"]:
            return False, f"Invalid role: {role}"

        # Validate that at least username or email is provided
        username = (username or "").strip() or None
        invitee_email = (invitee_email or "").strip() or None
        if not username and not invitee_email:
            return False, "Please provide either a username or an email address"

        project = self._projects[project_slug]
        if project.visibility == "private":
            return False, "Private projects do not accept collaborators"

        # Create the invite
        ok, message = self.auth_service.create_project_invite(
            project_slug=project_slug,
            role=Role(role),
            invited_by=invited_by,
            username=username,
            invitee_email=invitee_email,
        )
        if not ok:
            return ok, message

        # Get the created invite to send email if needed
        invite_key = username or f"email:{invitee_email}"
        invite = self.auth_service._pending_invites.get(invite_key, {}).get(project_slug)
        if invite is None:
            return True, message

        # Send email if email address is provided
        if invitee_email:
            email_ok, email_status = self.invite_notifier.send(
                InviteEmailPayload(
                    invitee_username=username,
                    invitee_email=invitee_email,
                    project_slug=project_slug,
                    role=role,
                    invited_by=invited_by,
                    expires_at=invite.expires_at,
                    login_url=self.invite_login_url,
                )
            )
            if email_ok:
                return True, f"{message} | {email_status}"
            return True, f"{message} | ⚠️ {email_status}"

        return True, message

    def list_pending_invites(self, project_slug: str | None = None) -> List[dict]:
        invites = self.auth_service.list_all_pending_invites()
        rows: list[dict] = []
        for invite in invites:
            if project_slug and invite.project_slug != project_slug:
                continue
            rows.append(
                {
                    "username": invite.username,
                    "project_slug": invite.project_slug,
                    "role": invite.role.value,
                    "invited_by": invite.invited_by,
                    "expires_at": invite.expires_at.isoformat(),
                }
            )
        return rows

    def revoke_invite(self, username: str, project_slug: str) -> Tuple[bool, str]:
        return self.auth_service.revoke_project_invite(username=username, project_slug=project_slug)

    def delete_project(self, actor_username: str, project_slug: str) -> Tuple[bool, str]:
        """Delete a project and remove all linked assignments/invites."""
        slug = (project_slug or "").strip()
        if not slug:
            return False, "Project slug is required"
        if slug not in self._projects:
            return False, f"Project '{slug}' not found"

        if not self._can_admin_project(actor_username, slug):
            return False, "Access denied: admin role required for this project"

        project = self._projects[slug]
        if project.visibility == "private":
            owner = (project.owner_username or "").strip()
            if not owner:
                return False, "Private project is misconfigured: owner is required"
            if actor_username != owner:
                return False, "Only the private project owner can delete this project"

        del self._projects[slug]
        removed_assignments = self.auth_service.remove_project_from_all_users(slug)
        revoked_invites = self.auth_service.revoke_all_invites_for_project(slug)
        return (
            True,
            f"✅ Project '{slug}' deleted (removed assignments: {removed_assignments}, revoked invites: {revoked_invites})",
        )

    def remove_user_from_project(self, actor_username: str, username: str, project_slug: str) -> Tuple[bool, str]:
        """Remove a user's access to a project.

        Args:
            username: Username
            project_slug: Project slug

        Returns:
            Tuple of (success, message)
        """
        if username not in self.auth_service.list_usernames(include_inactive=True):
            return False, f"User '{username}' not found"

        if not self._can_admin_project(actor_username, project_slug):
            return False, "Access denied: admin role required for this project"

        project = self._projects.get(project_slug)
        if project is None:
            return False, f"Project '{project_slug}' not found"
        if project.visibility == "private":
            owner = (project.owner_username or "").strip()
            if not owner:
                return False, "Private project is misconfigured: owner is required"
            if username != owner:
                return False, "Private projects only allow the owner"

        role = self.auth_service.get_user_role_for_project(username, project_slug)
        if role is None:
            return False, f"User '{username}' is not assigned to project '{project_slug}'"

        _ = self.auth_service.remove_user_project_role(username, project_slug)
        return True, f"✅ Removed {username} from {project_slug}"

    def toggleproject_active(self, project_slug: str, active: bool) -> Tuple[bool, str]:
        """Enable or disable a project.

        Args:
            project_slug: Project slug
            active: Whether to activate or deactivate

        Returns:
            Tuple of (success, message)
        """
        if project_slug not in self._projects:
            return False, f"Project '{project_slug}' not found"

        self._projects[project_slug].active = active
        status = "activated" if active else "deactivated"
        return True, f"✅ Project {project_slug} {status}"


def create_admin_panel(admin_manager: AdminPanelManager, current_session: Session) -> gr.Blocks:
    """Create Gradio admin panel UI.

    Args:
        admin_manager: AdminPanelManager instance
        current_session: Current user's session

    Returns:
        Gradio Blocks with admin panel tabs
    """
    if current_session.role != Role.admin:
        with gr.Blocks() as restricted:
            gr.Markdown("❌ **Access Denied**\n\nOnly administrators can access this panel.")
        return restricted

    with gr.Blocks(title="BirdNET Admin Panel") as admin_block:
        gr.Markdown("# Admin Panel")
        gr.Markdown(f"Logged in as: **{current_session.username}** (Admin)")

        with gr.Tabs():
            # Projects Tab
            with gr.Tab("Projects"):
                gr.Markdown("## Manage Projects")

                with gr.Row():
                    with gr.Column(scale=2):
                        project_slug_input = gr.Textbox(
                            label="Project Slug",
                            placeholder="e.g., kenya-2024",
                            lines=1,
                        )
                        project_name_input = gr.Textbox(
                            label="Project Name",
                            placeholder="e.g., Kenya Survey 2024",
                            lines=1,
                        )

                    with gr.Column(scale=1):
                        repo_id_input = gr.Textbox(
                            label="HF Dataset Repo ID",
                            placeholder="e.g., org/dataset-name",
                            lines=1,
                        )

                project_message = gr.Markdown()

                # Projects list
                with gr.Row():
                    refresh_projects_button = gr.Button("Refresh Projects List")
                    projects_table = gr.Dataframe(
                        value=admin_manager.list_projects(),
                        headers=["project_slug", "name", "dataset_repo_id", "active"],
                        interactive=False,
                    )

                refresh_projects_button.click(
                    fn=lambda: admin_manager.list_projects(),
                    outputs=[projects_table],
                )

            # Users Tab
            with gr.Tab("Users"):
                gr.Markdown("## Manage User Access")

                with gr.Row():
                    username_input = gr.Textbox(
                        label="Username",
                        placeholder="e.g., validator_001",
                        lines=1,
                    )

                    project_select = gr.Dropdown(
                        choices=[p["project_slug"] for p in admin_manager.list_projects()],
                        label="Project",
                    )

                    role_select = gr.Dropdown(
                        choices=["admin", "validator"],
                        value="validator",
                        label="Role",
                    )

                user_message = gr.Markdown()

                assign_button = gr.Button("Assign User", variant="primary")
                remove_button = gr.Button("Remove User", variant="stop")

                def assign_user(username: str, project_slug: str, role: str) -> str:
                    success, msg = admin_manager.assign_user_to_project(
                        current_session.username,
                        username,
                        project_slug,
                        role,
                    )
                    return msg

                def remove_user(username: str, project_slug: str) -> str:
                    success, msg = admin_manager.remove_user_from_project(
                        current_session.username,
                        username,
                        project_slug,
                    )
                    return msg

                assign_button.click(
                    fn=assign_user,
                    inputs=[username_input, project_select, role_select],
                    outputs=[user_message],
                )

                remove_button.click(
                    fn=remove_user,
                    inputs=[username_input, project_select],
                    outputs=[user_message],
                )

                # Users per project view
                with gr.Row():
                    project_filter = gr.Dropdown(
                        choices=[p["project_slug"] for p in admin_manager.list_projects()],
                        label="View Users for Project",
                    )

                    users_table = gr.Dataframe(
                        value=[],
                        headers=["username", "role"],
                        interactive=False,
                    )

                def update_users_table(project_slug: str):
                    return admin_manager.list_users_for_project(project_slug)

                project_filter.change(
                    fn=update_users_table,
                    inputs=[project_filter],
                    outputs=[users_table],
                )

    return admin_block
