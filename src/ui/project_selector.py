"""Project selector component for switching between authorized projects."""

from typing import List, Tuple

import gradio as gr

from src.auth.auth_service import AuthService, Session


def create_project_selector(
    auth_service: AuthService, current_session: Session
) -> Tuple[gr.Dropdown, gr.Markdown]:
    """Create a project selector dropdown for the current user.

    Args:
        auth_service: AuthService instance
        current_session: Current user's session

    Returns:
        Tuple of (project_dropdown, project_info_display)
    """
    authorized_projects = current_session.authorized_projects

    if not authorized_projects:
        with gr.Group():
            gr.Markdown("⚠️ **No Projects Assigned**\n\nYou don't have access to any projects yet. Contact an administrator.")

        return (
            gr.Dropdown(choices=[], label="Project", interactive=False),
            gr.Markdown(""),
        )

    with gr.Group():
        project_dropdown = gr.Dropdown(
            choices=authorized_projects,
            value=authorized_projects[0],
            label="Select Project",
            interactive=True,
        )

        project_info = gr.Markdown()

        def update_project_info(selected_project: str) -> str:
            """Display info about the selected project.

            Args:
                selected_project: Project slug

            Returns:
                Markdown formatted project info
            """
            role = auth_service.get_user_role_for_project(
                current_session.username, selected_project
            )
            if role:
                return f"📁 **Project:** {selected_project} | **Your Role:** {role.value.upper()}"
            return f"📁 **Project:** {selected_project}"

        # Initial display
        initial_project = authorized_projects[0]
        role = auth_service.get_user_role_for_project(
            current_session.username, initial_project
        )
        initial_info = (
            f"📁 **Project:** {initial_project} | **Your Role:** {role.value.upper()}"
            if role
            else f"📁 **Project:** {initial_project}"
        )
        project_info.value = initial_info

        project_dropdown.change(
            fn=update_project_info,
            inputs=[project_dropdown],
            outputs=[project_info],
        )

    return project_dropdown, project_info
