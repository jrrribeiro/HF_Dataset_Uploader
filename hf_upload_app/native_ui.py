from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from uploader.auth_service import AuthService
from uploader.native_backend import perform_upload


class NativeUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HF Dataset Uploader")
        self.geometry("920x700")
        self.minsize(860, 620)

        self.cancel_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.worker_running = False
        self.selected_inputs: list[str] = []

        self._build_styles()
        self._build_layout()
        self._prefill_token_if_available()

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

    def _build_layout(self) -> None:
        container = ttk.Frame(self, padding=14)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="HF Dataset Uploader", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(header, text="Native Windows GUI", foreground="#666").grid(row=1, column=0, sticky=tk.W)

        form = ttk.LabelFrame(container, text="Connection", padding=12)
        form.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Hugging Face Token").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.token_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.token_var, show="*", width=72).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Dataset repo (owner/name)").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.repo_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.repo_var, width=72).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Workers").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.workers_var = tk.IntVar(value=4)
        ttk.Spinbox(form, from_=1, to=32, textvariable=self.workers_var, width=8).grid(row=2, column=1, sticky=tk.W, pady=4)

        inputs = ttk.LabelFrame(container, text="Inputs", padding=12)
        inputs.grid(row=2, column=0, sticky="ew")
        inputs.columnconfigure(0, weight=1)
        inputs.columnconfigure(1, weight=0)
        inputs.columnconfigure(2, weight=0)

        self.inputs_list = tk.Listbox(inputs, height=7, selectmode=tk.EXTENDED, activestyle="dotbox")
        self.inputs_list.grid(row=0, column=0, rowspan=4, sticky="nsew")
        inputs_scroll = ttk.Scrollbar(inputs, orient=tk.VERTICAL, command=self.inputs_list.yview)
        inputs_scroll.grid(row=0, column=1, rowspan=4, sticky="ns")
        self.inputs_list.configure(yscrollcommand=inputs_scroll.set)

        ttk.Button(inputs, text="Add Folder", command=self.add_folder).grid(row=0, column=2, sticky="ew", padx=(10, 0), pady=(0, 6))
        ttk.Button(inputs, text="Add Files", command=self.add_files).grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=6)
        ttk.Button(inputs, text="Remove Selected", command=self.remove_selected_inputs).grid(row=2, column=2, sticky="ew", padx=(10, 0), pady=6)
        ttk.Button(inputs, text="Clear Inputs", command=self.clear_inputs).grid(row=3, column=2, sticky="ew", padx=(10, 0), pady=6)

        progress_panel = ttk.Frame(container)
        progress_panel.grid(row=3, column=0, sticky="nsew", pady=(12, 10))
        progress_panel.columnconfigure(0, weight=1)
        progress_panel.rowconfigure(2, weight=1)

        status_row = ttk.Frame(progress_panel)
        status_row.grid(row=0, column=0, sticky="ew")
        status_row.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(status_row, textvariable=self.status_var).grid(row=0, column=0, sticky=tk.W)
        self.percent_var = tk.StringVar(value="0%")
        ttk.Label(status_row, textvariable=self.percent_var).grid(row=0, column=1, sticky=tk.E)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(progress_panel, variable=self.progress_var, maximum=100.0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(6, 10))

        log_frame = ttk.LabelFrame(progress_panel, text="Log", padding=10)
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=16, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        log_actions = ttk.Frame(log_frame)
        log_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(log_actions, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT)
        ttk.Button(log_actions, text="Copy Log", command=self.copy_log).pack(side=tk.LEFT, padx=8)

        actions = ttk.Frame(container)
        actions.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        actions.columnconfigure(0, weight=1)

        self.start_btn = ttk.Button(actions, text="Start Upload", command=self.start_upload)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(actions, text="Stop Upload", command=self.stop_upload, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=8)

    def _prefill_token_if_available(self) -> None:
        try:
            token = AuthService().get_token()
        except Exception:
            token = None
        if token:
            self.token_var.set(token)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line.rstrip() + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def log(self, line: str) -> None:
        self.after(0, lambda: self._append_log(line))

    def clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def copy_log(self) -> None:
        text = self.log_text.get("1.0", tk.END).strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select audio folder")
        if folder:
            self._add_input(folder)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select audio files or archives",
            filetypes=[
                ("Audio files", "*.wav *.mp3 *.flac *.ogg *.m4a"),
                ("Archives", "*.zip *.tar *.gz *.tgz"),
                ("All files", "*.*"),
            ],
        )
        for path in paths:
            self._add_input(path)

    def _add_input(self, path: str) -> None:
        if path in self.selected_inputs:
            return
        self.selected_inputs.append(path)
        self.inputs_list.insert(tk.END, path)

    def remove_selected_inputs(self) -> None:
        selected = list(self.inputs_list.curselection())
        for index in reversed(selected):
            value = self.inputs_list.get(index)
            if value in self.selected_inputs:
                self.selected_inputs.remove(value)
            self.inputs_list.delete(index)

    def clear_inputs(self) -> None:
        self.selected_inputs.clear()
        self.inputs_list.delete(0, tk.END)

    def set_progress(self, percent: float, message: str) -> None:
        clamped = max(0.0, min(100.0, percent * 100.0))
        self.progress_var.set(clamped)
        self.percent_var.set(f"{clamped:.0f}%")
        self.status_var.set(message)

    def _set_running(self, running: bool) -> None:
        self.worker_running = running
        self.start_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)

    def stop_upload(self) -> None:
        if not self.worker_running:
            return
        self.cancel_event.set()
        self.log("Stop requested by user.")
        self.status_var.set("Stopping upload...")

    def start_upload(self) -> None:
        if self.worker_running:
            return

        token = self.token_var.get().strip()
        if not token:
            try:
                token = (AuthService().get_token() or "").strip()
            except Exception:
                token = ""

        repo = self.repo_var.get().strip()
        if not token or not repo:
            messagebox.showerror("Missing fields", "Token and repo id are required")
            return

        if not self.selected_inputs:
            messagebox.showerror("Missing inputs", "Add at least one folder, file, or archive")
            return

        workers = int(self.workers_var.get() or 4)
        self.cancel_event = threading.Event()
        self.clear_log()
        self.progress_var.set(0.0)
        self.percent_var.set("0%")
        self.status_var.set("Starting upload...")
        self._set_running(True)
        self.log(f"Starting upload for {repo}")
        self.log(f"Inputs: {len(self.selected_inputs)} item(s)")

        def progress_cb(percent: float, message: str) -> None:
            self.after(0, lambda: self.set_progress(percent, message))
            self.log(message)

        def log_cb(line: str) -> None:
            self.log(line)

        def runner() -> None:
            try:
                result = perform_upload(
                    token,
                    repo,
                    list(self.selected_inputs),
                    None,
                    workers,
                    progress_callback=progress_cb,
                    log_callback=log_cb,
                    cancel_event=self.cancel_event,
                )
                if self.cancel_event.is_set():
                    self.after(0, lambda: self.status_var.set("Upload cancelled"))
                    self.log("Upload cancelled.")
                else:
                    self.log(f"Upload finished: {result}")
                    self.after(0, lambda: self.set_progress(1.0, "Upload finished"))
                    self.after(0, lambda: messagebox.showinfo("Upload finished", f"Result: {result}"))
            except Exception as exc:
                self.log(f"Error: {exc}")
                self.after(0, lambda: messagebox.showerror("Upload error", str(exc)))
                self.after(0, lambda: self.status_var.set("Upload failed"))
            finally:
                self.after(0, lambda: self._set_running(False))

        self.worker_thread = threading.Thread(target=runner, daemon=True)
        self.worker_thread.start()


def main() -> None:
    app = NativeUI()
    app.mainloop()


if __name__ == "__main__":
    main()
