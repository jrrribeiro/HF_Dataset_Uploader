from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Button, Static


class BirdNetUploaderTui(App[None]):
	"""Minimal shell used during sprint scaffolding."""

	TITLE = "BirdNET Uploader"

	def compose(self) -> ComposeResult:
		yield Container(
			Static("BirdNET Uploader\nLogin -> Repo -> Upload", id="title"),
			Button("Exit", id="exit"),
			id="main",
		)

	def on_button_pressed(self, event: Button.Pressed) -> None:
		if event.button.id == "exit":
			self.exit()
