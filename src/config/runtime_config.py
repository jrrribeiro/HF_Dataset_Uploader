from dataclasses import dataclass
import os
import tempfile
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    detection_seed_path: str | None
    validation_base_dir: str
    bootstrap_base_dir: str
    page_size: int
    projects_file_path: str | None
    user_access_file_path: str | None
    invites_file_path: str | None
    invite_ttl_hours: int
    enable_demo_bootstrap: bool
    invite_email_enabled: bool
    invite_email_sender: str
    invite_email_login_url: str
    emailjs_enabled: bool = False
    emailjs_service_id: str | None = None
    emailjs_template_id: str | None = None
    emailjs_template_id_username_only: str | None = None
    emailjs_template_id_email_only: str | None = None
    emailjs_template_id_dual: str | None = None
    emailjs_public_key: str | None = None
    emailjs_endpoint: str = "https://api.emailjs.com/api/v1.0/email/send"
    emailjs_timeout_seconds: int = 20

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        detection_seed_path = (os.getenv("BIRDNET_DETECTIONS_FILE") or "").strip() or None

        data_root = Path("/data") if Path("/data").exists() else (Path(tempfile.gettempdir()) / "birdnet-validator-data")

        bootstrap_base_dir = (
            os.getenv("BIRDNET_BOOTSTRAP_DIR")
            or str(data_root / "bootstrap")
        )

        validation_base_dir = (
            os.getenv("BIRDNET_VALIDATIONS_DIR")
            or str(data_root / "validations")
        )

        raw_page_size = (os.getenv("BIRDNET_PAGE_SIZE") or "").strip()
        page_size = 25
        if raw_page_size:
            try:
                parsed = int(raw_page_size)
                if parsed > 0:
                    page_size = parsed
            except ValueError:
                page_size = 25

        projects_file_path = (os.getenv("BIRDNET_PROJECTS_FILE") or "").strip() or None
        user_access_file_path = (os.getenv("BIRDNET_USER_ACCESS_FILE") or "").strip() or None
        invites_file_path = (os.getenv("BIRDNET_INVITES_FILE") or "").strip() or None
        raw_invite_ttl_hours = (os.getenv("BIRDNET_INVITE_TTL_HOURS") or "").strip()
        invite_ttl_hours = 72
        if raw_invite_ttl_hours:
            try:
                parsed = int(raw_invite_ttl_hours)
                if parsed > 0:
                    invite_ttl_hours = parsed
            except ValueError:
                invite_ttl_hours = 72

        raw_enable_demo_bootstrap = (os.getenv("BIRDNET_ENABLE_DEMO_BOOTSTRAP") or "").strip().lower()
        enable_demo_bootstrap = raw_enable_demo_bootstrap in {"1", "true", "yes", "on"}

        raw_invite_email_enabled = (os.getenv("BIRDNET_INVITE_EMAIL_ENABLED") or "").strip().lower()
        invite_email_enabled = raw_invite_email_enabled in {"1", "true", "yes", "on"}
        invite_email_sender = (os.getenv("BIRDNET_INVITE_EMAIL_SENDER") or "").strip()
        invite_email_login_url = (os.getenv("BIRDNET_INVITE_EMAIL_LOGIN_URL") or "").strip() or ""

        raw_emailjs_enabled = (os.getenv("BIRDNET_EMAILJS_ENABLED") or "").strip().lower()
        emailjs_enabled = raw_emailjs_enabled in {"1", "true", "yes", "on"}
        emailjs_service_id = (os.getenv("BIRDNET_EMAILJS_SERVICE_ID") or "").strip() or None
        emailjs_template_id = (os.getenv("BIRDNET_EMAILJS_TEMPLATE_ID") or "").strip() or None
        emailjs_template_id_username_only = (os.getenv("BIRDNET_EMAILJS_TEMPLATE_ID_USERNAME_ONLY") or "").strip() or None
        emailjs_template_id_email_only = (os.getenv("BIRDNET_EMAILJS_TEMPLATE_ID_EMAIL_ONLY") or "").strip() or None
        emailjs_template_id_dual = (os.getenv("BIRDNET_EMAILJS_TEMPLATE_ID_DUAL") or "").strip() or None
        emailjs_public_key = (os.getenv("BIRDNET_EMAILJS_PUBLIC_KEY") or os.getenv("EMAILJS_PUBLIC_KEY") or "").strip() or None
        emailjs_endpoint = (os.getenv("BIRDNET_EMAILJS_ENDPOINT") or "https://api.emailjs.com/api/v1.0/email/send").strip() or "https://api.emailjs.com/api/v1.0/email/send"
        raw_emailjs_timeout = (os.getenv("BIRDNET_EMAILJS_TIMEOUT_SECONDS") or "").strip()
        emailjs_timeout_seconds = 20
        if raw_emailjs_timeout:
            try:
                parsed = int(raw_emailjs_timeout)
                if parsed > 0:
                    emailjs_timeout_seconds = parsed
            except ValueError:
                emailjs_timeout_seconds = 20

        return cls(
            detection_seed_path=detection_seed_path,
            validation_base_dir=validation_base_dir,
            bootstrap_base_dir=bootstrap_base_dir,
            page_size=page_size,
            projects_file_path=projects_file_path,
            user_access_file_path=user_access_file_path,
            invites_file_path=invites_file_path,
            invite_ttl_hours=invite_ttl_hours,
            enable_demo_bootstrap=enable_demo_bootstrap,
            invite_email_enabled=invite_email_enabled,
            invite_email_sender=invite_email_sender,
            invite_email_login_url=invite_email_login_url,
            emailjs_enabled=emailjs_enabled,
            emailjs_service_id=emailjs_service_id,
            emailjs_template_id=emailjs_template_id,
            emailjs_template_id_username_only=emailjs_template_id_username_only,
            emailjs_template_id_email_only=emailjs_template_id_email_only,
            emailjs_template_id_dual=emailjs_template_id_dual,
            emailjs_public_key=emailjs_public_key,
            emailjs_endpoint=emailjs_endpoint,
            emailjs_timeout_seconds=emailjs_timeout_seconds,
        )
