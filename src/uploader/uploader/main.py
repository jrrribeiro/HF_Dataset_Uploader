from __future__ import annotations

import json
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import click

from src.uploader.auth_service import AuthService
from src.uploader.error_handler import build_error_message
from src.uploader.repo_service import RepositoryService
from src.uploader.scanner import LocalScanner
from src.uploader.session_manager import SessionManager


def handle_cli_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
	@wraps(fn)
	def wrapper(*args: Any, **kwargs: Any) -> Any:
		try:
			return fn(*args, **kwargs)
		except click.ClickException:
			raise
		except Exception as exc:
			raise click.ClickException(build_error_message(exc)) from exc

	return wrapper


@click.group(help="BirdNET local uploader CLI")
def cli() -> None:
	pass


@cli.command("login")
@click.option("--token", prompt=True, hide_input=True, help="Hugging Face token")
@handle_cli_errors
def login_cmd(token: str) -> None:
	service = AuthService()
	user = service.authenticate(token)
	click.echo(f"OK: authenticated as {user['username']}")


@cli.command("init-repo")
@click.option("--repo-id", required=True, help="Dataset repo id in owner/name format")
@click.option("--private/--public", "private_repo", default=True, show_default=True)
@handle_cli_errors
def init_repo_cmd(repo_id: str, private_repo: bool) -> None:
	token = AuthService().require_token()

	created = RepositoryService(token).create_dataset(repo_id, private=private_repo)
	click.echo(f"OK: dataset ready at {created}")


@cli.command("scan")
@click.option("--segments", "segments_dir", required=True, type=click.Path(exists=True, file_okay=False))
@handle_cli_errors
def scan_cmd(segments_dir: str) -> None:
	summary = LocalScanner().scan_folder(segments_dir)
	click.echo(
		json.dumps(
			{
				"total_files": summary["total_files"],
				"total_size": summary["total_size"],
				"species_count": len(summary["by_species"]),
			},
			ensure_ascii=True,
			indent=2,
		)
	)


@cli.command("start")
@click.option("--repo-id", required=True)
@click.option("--segments", "segments_dir", required=True, type=click.Path(exists=True, file_okay=False))
@handle_cli_errors
def start_cmd(repo_id: str, segments_dir: str) -> None:
	scanner = LocalScanner()
	summary = scanner.scan_folder(segments_dir)
	session = SessionManager()
	payload = {
		"repo_id": repo_id,
		"segments_dir": str(Path(segments_dir).resolve()),
		"total_files": summary["total_files"],
		"total_size": summary["total_size"],
		"uploaded": 0,
		"failed": 0,
		"status": "ready",
	}
	session.save_checkpoint(payload)
	click.echo(f"OK: session created: {session.session_id}")
	click.echo(f"Checkpoint: {session.checkpoint_path}")


@cli.command("resume")
@click.argument("session_id")
@handle_cli_errors
def resume_cmd(session_id: str) -> None:
	session = SessionManager(session_id=session_id)
	payload = session.load_checkpoint()
	if not payload:
		raise click.ClickException(f"Session has no checkpoint: {session_id}")
	click.echo(json.dumps(payload, ensure_ascii=True, indent=2))


if __name__ == "__main__":
	cli()
