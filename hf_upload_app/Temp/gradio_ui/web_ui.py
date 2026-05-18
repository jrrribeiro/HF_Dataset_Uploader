"""Gradio demo UI moved to Temp/gradio_ui. This file is not used in the native EXE.

To run locally for development:
    pip install -r requirements.txt
    python Temp/gradio_ui/web_ui.py
"""

from __future__ import annotations

import gradio as gr

# Minimal shim: import original code or expose a small demo

def create_demo():
    with gr.Blocks() as demo:
        gr.Markdown("# HF Dataset Uploader - Gradio Demo (moved to Temp)")
    return demo


if __name__ == "__main__":
    app = create_demo()
    app.launch(server_name="0.0.0.0", server_port=7860, inbrowser=True)
