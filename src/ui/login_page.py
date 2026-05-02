"""Gradio login page component for multi-project authorization."""

from typing import Optional, Tuple

import gradio as gr

from src.auth.auth_service import AuthService, Session


def create_login_page(auth_service: AuthService) -> Tuple[gr.Textbox, gr.Textbox, gr.Button, gr.Markdown]:
    """Create a Gradio login page with username input and session tracking.

    Args:
        auth_service: AuthService instance for login validation

    Returns:
        Tuple of (username_input, session_output, login_button, error_message)
    """
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("")
        with gr.Column(scale=6):
            gr.Markdown("# BirdNET Validation Platform")
            gr.Markdown("Login to access multi-project validation workflows")

            username_input = gr.Textbox(
                label="Username",
                placeholder="Enter your username",
                lines=1,
            )
            hf_token_input = gr.Textbox(
                label="Hugging Face Token (recommended)",
                placeholder="hf_xxx...",
                type="password",
                lines=1,
            )

            error_message = gr.Markdown()

            login_button = gr.Button("Login", variant="primary", scale=1)

            session_output = gr.Textbox(
                label="Session ID",
                interactive=False,
                visible=False,
            )
        with gr.Column(scale=1):
            gr.Markdown("")

    def perform_login(username: str, hf_token: str) -> Tuple[str, str]:
        """Attempt login and return session ID or error message.

        Args:
            username: Username to authenticate

        Returns:
            Tuple of (session_id, error_message)
        """
        if hf_token and hf_token.strip():
            session, message = auth_service.login_with_hf_token(hf_token)
            if session is None:
                return "", message
            return session.session_id, message

        if not username or not username.strip():
            return "", "❌ Please enter a username or provide a Hugging Face token"

        username = username.strip()
        session = auth_service.login(username)

        if session is None:
            return "", f"❌ User '{username}' not found or inactive"

        admin_projects = 0
        validator_projects = 0
        for project_slug in session.authorized_projects:
            project_role = auth_service.get_user_role_for_project(username, project_slug)
            if project_role is None:
                continue
            if project_role.value == "admin":
                admin_projects += 1
            else:
                validator_projects += 1

        return (
            session.session_id,
            (
                f"✅ Welcome, {username}! "
                f"Admin in {admin_projects} project(s), validator in {validator_projects} project(s)."
            ),
        )

    login_button.click(
        fn=perform_login,
        inputs=[username_input, hf_token_input],
        outputs=[session_output, error_message],
    )

    return username_input, session_output, login_button, error_message
