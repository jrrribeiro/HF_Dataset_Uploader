from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List

from uploader.auth_service import AuthService
from uploader.native_backend import perform_upload


class NativeUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HF Dataset Uploader - Native")
        self.geometry("640x400")

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Hugging Face Token:").grid(row=0, column=0, sticky=tk.W)
        self.token_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.token_var, width=60, show="*").grid(row=0, column=1, sticky=tk.W)

        ttk.Label(frm, text="Dataset (owner/name):").grid(row=1, column=0, sticky=tk.W)
        self.repo_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.repo_var, width=60).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(frm, text="Remote base path:").grid(row=2, column=0, sticky=tk.W)
        self.remote_var = tk.StringVar(value="audio")
        ttk.Entry(frm, textvariable=self.remote_var, width=30).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(frm, text="Workers:").grid(row=3, column=0, sticky=tk.W)
        self.workers_var = tk.IntVar(value=4)
        ttk.Spinbox(frm, from_=1, to=32, textvariable=self.workers_var, width=6).grid(row=3, column=1, sticky=tk.W)

        ttk.Label(frm, text="Audio files / archives:").grid(row=4, column=0, sticky=tk.W)
        self.files_list: List[str] = []
        self.files_box = tk.Listbox(frm, height=6, width=60)
        self.files_box.grid(row=4, column=1, sticky=tk.W)
        ttk.Button(frm, text="Add Files", command=self.add_files).grid(row=4, column=2)

        ttk.Label(frm, text="Optional CSV:").grid(row=5, column=0, sticky=tk.W)
        self.csv_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.csv_var, width=60).grid(row=5, column=1, sticky=tk.W)
        ttk.Button(frm, text="Select CSV", command=self.select_csv).grid(row=5, column=2)

        self.start_btn = ttk.Button(frm, text="Start Upload", command=self.start_upload)
        self.start_btn.grid(row=6, column=1, pady=8)

        ttk.Label(frm, text="Status:").grid(row=7, column=0, sticky=tk.W)
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(frm, textvariable=self.status_var).grid(row=7, column=1, sticky=tk.W)

        self._prefill_token_if_available()

    def _prefill_token_if_available(self):
        try:
            token = AuthService().get_token()
        except Exception:
            token = None
        if token:
            self.token_var.set(token)

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Select audio files or archives", filetypes=[("Audio and archives", "*.wav *.mp3 *.flac *.ogg *.m4a *.zip *.tar *.gz")])
        for p in paths:
            self.files_list.append(p)
            self.files_box.insert(tk.END, p)

    def select_csv(self):
        p = filedialog.askopenfilename(title="Select CSV file", filetypes=[("CSV", "*.csv")])
        if p:
            self.csv_var.set(p)

    def set_status(self, percent: float, message: str):
        self.status_var.set(f"{message} ({percent*100:.0f}%)")

    def start_upload(self):
        token = self.token_var.get().strip()
        if not token:
            try:
                token = (AuthService().get_token() or "").strip()
            except Exception:
                token = ""
        repo = self.repo_var.get().strip()
        remote = self.remote_var.get().strip() or "audio"
        workers = int(self.workers_var.get() or 4)
        files = list(self.files_list)
        csvp = self.csv_var.get().strip() or None

        if not token or not repo:
            messagebox.showerror("Missing fields", "Token and repo id are required")
            return

        def progress_cb(p, msg):
            self.after(0, lambda: self.set_status(p, msg))

        def runner():
            try:
                self.after(0, lambda: self.start_btn.config(state=tk.DISABLED))
                res = perform_upload(token, repo, files, csvp, remote, workers, progress_callback=progress_cb)
                self.after(0, lambda: messagebox.showinfo("Upload finished", f"Result: {res}"))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Upload error", str(exc)))
            finally:
                self.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

        threading.Thread(target=runner, daemon=True).start()


def main():
    app = NativeUI()
    app.mainloop()


if __name__ == "__main__":
    main()
