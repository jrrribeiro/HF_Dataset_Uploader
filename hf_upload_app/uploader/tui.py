from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Button, Static


class HfDatasetUploaderTui(App[None]):
    """Minimal shell used during sprint scaffolding."""

    TITLE = "HF Dataset Uploader"

    def compose(self) -> ComposeResult:
        yield Container(
            Static("HF Dataset Uploader\nLogin -> Repo -> Upload", id="title"),
            Button("Exit", id="exit"),
            id="main",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exit":
            self.exit()
