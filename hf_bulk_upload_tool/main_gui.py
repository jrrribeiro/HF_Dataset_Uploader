#!/usr/bin/env python3
"""
GUI for Hugging Face Bulk Uploader using CustomTkinter.

This is a portable GUI wrapper around the upload_logic module, designed to be
packaged as a standalone .exe using PyInstaller.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import queue
from pathlib import Path
import sys

# Import the refactored logic using a robust lookup that works both
# in development and when packaged by PyInstaller.
import importlib

def _find_run_upload_logic():
    # Try explicit module names first
    for name in ("hf_bulk_upload_tool.upload_logic", "upload_logic"):
        try:
            m = importlib.import_module(name)
            if hasattr(m, "run_upload_logic"):
                return getattr(m, "run_upload_logic")
        except Exception:
            pass

    # Search already-imported modules for a candidate (useful in PyInstaller)
    for m in list(sys.modules.values()):
        try:
            if hasattr(m, "run_upload_logic"):
                return getattr(m, "run_upload_logic")
        except Exception:
            continue

    # As a last resort, if this file is in a package, try relative import
    pkg = __package__
    if pkg:
        try:
            m = importlib.import_module(pkg + ".upload_logic")
            if hasattr(m, "run_upload_logic"):
                return getattr(m, "run_upload_logic")
        except Exception:
            pass

    return None

run_upload_logic = _find_run_upload_logic()
if run_upload_logic is None:
    raise ImportError("Could not import `run_upload_logic` from hf_bulk_upload_tool or upload_logic; searched known modules and sys.modules")


class UploadConfig:
    """Simple config holder for upload parameters."""
    def __init__(self):
        self.repo_id = ""
        self.hf_token = ""
        self.segments_path = ""
        self.csv_path = ""
        self.private = True
        self.resume = True
        self.verify_remote = False
        self.verify_etag = False
        self.rate_limit_aware = True
        self.max_workers = 1
        self.upload_attempts = 3
        self.retry_backoff = 5.0


class HFUploaderApp(ctk.CTk):
    """Main GUI application for Hugging Face dataset uploads."""
    
    def __init__(self):
        super().__init__()
        
        self.title("Hugging Face Dataset Uploader")
        self.geometry("900x750")
        self.resizable(True, True)
        
        # Configure appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Upload state
        self.uploading = False
        self.upload_thread = None
        self.log_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self._dynamic_line_active = False
        self._dynamic_line_start = None
        
        # Build UI
        self._build_ui()
        
        # Start log queue processor
        self.after(100, self._process_log_queue)
    
    def _build_ui(self):
        """Build the user interface."""
        # Main container with padding
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # ===== CONFIGURATION SECTION =====
        config_label = ctk.CTkLabel(
            main_frame, text="📋 Upload Configuration", 
            font=("Arial", 14, "bold")
        )
        config_label.pack(anchor="w", pady=(0, 10))
        
        config_frame = ctk.CTkFrame(main_frame)
        config_frame.pack(fill="x", pady=(0, 15))
        
        # Row 1: Repo ID
        ctk.CTkLabel(config_frame, text="Repository ID:", font=("Arial", 11)).grid(
            row=0, column=0, sticky="w", padx=5, pady=5
        )
        self.repo_id_entry = ctk.CTkEntry(
            config_frame, placeholder_text="username/dataset-name", width=300
        )
        self.repo_id_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        
        # Row 2: Token
        ctk.CTkLabel(config_frame, text="HF Token:", font=("Arial", 11)).grid(
            row=1, column=0, sticky="w", padx=5, pady=5
        )
        self.token_entry = ctk.CTkEntry(
            config_frame, placeholder_text="hf_...", show="*", width=300
        )
        self.token_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        
        # Row 3: Segments path
        ctk.CTkLabel(config_frame, text="Segments Folder:", font=("Arial", 11)).grid(
            row=2, column=0, sticky="w", padx=5, pady=5
        )
        segments_row = ctk.CTkFrame(config_frame, fg_color="transparent")
        segments_row.grid(row=2, column=1, sticky="ew", padx=5, pady=5)
        
        self.segments_entry = ctk.CTkEntry(segments_row, width=200)
        self.segments_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        ctk.CTkButton(
            segments_row, text="Browse", width=80,
            command=self._browse_segments
        ).pack(side="left")
        
        # Row 4: CSV path
        ctk.CTkLabel(config_frame, text="CSV File (Optional):", font=("Arial", 11)).grid(
            row=3, column=0, sticky="w", padx=5, pady=5
        )
        csv_row = ctk.CTkFrame(config_frame, fg_color="transparent")
        csv_row.grid(row=3, column=1, sticky="ew", padx=5, pady=5)
        
        self.csv_entry = ctk.CTkEntry(csv_row, width=200)
        self.csv_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        ctk.CTkButton(
            csv_row, text="Browse", width=80,
            command=self._browse_csv
        ).pack(side="left")
        
        # Configure grid weights for proper stretching
        config_frame.columnconfigure(1, weight=1)
        
        # ===== OPTIONS SECTION =====
        options_label = ctk.CTkLabel(
            main_frame, text="⚙️ Options", 
            font=("Arial", 14, "bold")
        )
        options_label.pack(anchor="w", pady=(10, 10))
        
        options_frame = ctk.CTkFrame(main_frame)
        options_frame.pack(fill="x", pady=(0, 15))
        
        # Checkboxes
        self.private_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame, text="Private Repository",
            variable=self.private_var, font=("Arial", 10)
        ).pack(anchor="w", padx=5, pady=2)
        
        self.resume_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame, text="Resume (skip already uploaded files)",
            variable=self.resume_var, font=("Arial", 10)
        ).pack(anchor="w", padx=5, pady=2)
        
        self.verify_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options_frame, text="Verify remote files before skipping",
            variable=self.verify_var, font=("Arial", 10)
        ).pack(anchor="w", padx=5, pady=2)
        
        self.rate_limit_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_frame, text="Enable rate limiting (1000 req/5min)",
            variable=self.rate_limit_var, font=("Arial", 10)
        ).pack(anchor="w", padx=5, pady=2)
        
        # Worker threads
        worker_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        worker_frame.pack(anchor="w", padx=5, pady=5)
        
        ctk.CTkLabel(worker_frame, text="Worker threads:", font=("Arial", 10)).pack(side="left", padx=(0, 10))
        self.workers_combobox = ctk.CTkComboBox(
            worker_frame, 
            values=["1", "2", "3", "4", "5", "6", "7", "8"],
            width=60, 
            font=("Arial", 10),
            state="readonly"
        )
        self.workers_combobox.set("2")
        self.workers_combobox.pack(side="left")
        
        # ===== CONSOLE / LOG SECTION =====
        console_label = ctk.CTkLabel(
            main_frame, text="📝 Upload Progress",
            font=("Arial", 14, "bold")
        )
        console_label.pack(anchor="w", pady=(10, 5))
        
        self.log_textbox = ctk.CTkTextbox(
            main_frame, width=800, height=250,
            font=("Courier", 10), wrap="none"
        )
        self.log_textbox.pack(fill="both", expand=True, pady=(0, 15))
        
        # Disable editing of log textbox
        self.log_textbox.configure(state="disabled")
        
        # ===== BUTTON SECTION =====
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(0, 10))
        
        self.start_btn = ctk.CTkButton(
            button_frame, text="🚀 Start Upload",
            command=self._start_upload, width=150, height=40,
            font=("Arial", 12, "bold"), fg_color="#2ecc71"
        )
        self.start_btn.pack(side="left", padx=5)
        
        self.stop_btn = ctk.CTkButton(
            button_frame, text="⏹ Stop",
            command=self._stop_upload, width=150, height=40,
            state="disabled", font=("Arial", 12)
        )
        self.stop_btn.pack(side="left", padx=5)
        
        self.clear_btn = ctk.CTkButton(
            button_frame, text="🗑 Clear Log",
            command=self._clear_log, width=150, height=40,
            font=("Arial", 12)
        )
        self.clear_btn.pack(side="left", padx=5)
        
        # Status label
        self.status_label = ctk.CTkLabel(
            button_frame, text="Ready", font=("Arial", 10), text_color="gray"
        )
        self.status_label.pack(side="right", padx=5)
    
    def _browse_segments(self):
        """Open folder browser for segments."""
        folder = filedialog.askdirectory(title="Select Segments Folder")
        if folder:
            self.segments_entry.delete(0, "end")
            self.segments_entry.insert(0, folder)
    
    def _browse_csv(self):
        """Open file browser for CSV."""
        file = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if file:
            self.csv_entry.delete(0, "end")
            self.csv_entry.insert(0, file)
    
    def _log(self, message: str):
        """Add message to log queue (thread-safe)."""
        self.log_queue.put(message)
    
    def _process_log_queue(self):
        """Process queued log messages and update textbox."""
        drained_messages = []
        try:
            while True:
                drained_messages.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass

        if drained_messages:
            self.log_textbox.configure(state="normal")
            for message in drained_messages:
                dynamic = message.startswith("[Progress]") or message.startswith("[Status]")

                if dynamic:
                    if self._dynamic_line_active and self._dynamic_line_start is not None:
                        try:
                            self.log_textbox.delete(self._dynamic_line_start, "end")
                        except Exception:
                            pass
                    self.log_textbox.insert("end", message)
                    self._dynamic_line_active = True
                    self._dynamic_line_start = self.log_textbox.index("end-1c linestart")
                else:
                    if self._dynamic_line_active:
                        self.log_textbox.insert("end", "\n")
                        self._dynamic_line_active = False
                        self._dynamic_line_start = None
                    self.log_textbox.insert("end", message + "\n")

            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        
        # Schedule next check
        self.after(100, self._process_log_queue)
    
    def _clear_log(self):
        """Clear the log textbox."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self._dynamic_line_active = False
        self._dynamic_line_start = None
    
    def _validate_inputs(self) -> tuple[bool, str]:
        """Validate all input fields."""
        repo_id = self.repo_id_entry.get().strip()
        token = self.token_entry.get().strip()
        segments = self.segments_entry.get().strip()
        
        if not repo_id:
            return False, "Repository ID is required (format: username/repo-name)"
        if not token:
            return False, "Hugging Face token is required"
        if not segments:
            return False, "Segments folder is required"
        if not Path(segments).is_dir():
            return False, f"Segments folder does not exist: {segments}"
        
        csv_path = self.csv_entry.get().strip()
        if csv_path and not Path(csv_path).is_file():
            return False, f"CSV file does not exist: {csv_path}"
        
        return True, "OK"
    
    def _start_upload(self):
        """Start the upload process in a separate thread."""
        if self.uploading:
            messagebox.showwarning("Warning", "Upload already in progress")
            return
        
        valid, msg = self._validate_inputs()
        if not valid:
            messagebox.showerror("Validation Error", msg)
            return
        
        # Build config
        config = {
            "repo_id": self.repo_id_entry.get().strip(),
            "hf_token": self.token_entry.get().strip(),
            "segments": self.segments_entry.get().strip(),
            "csv": self.csv_entry.get().strip() or None,
            "private": self.private_var.get(),
            "resume": self.resume_var.get(),
            "verify_remote": self.verify_var.get(),
            "verify_etag": self.verify_var.get(),
            "rate_limit_aware": self.rate_limit_var.get(),
            "max_workers": int(self.workers_combobox.get()),
            "upload_attempts": 5,
            "retry_backoff": 10.0,
            "stop_event": self.stop_event,
            "suppress_console_progress": True,
        }
        
        # Disable buttons
        self.uploading = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="Uploading...", text_color="orange")
        
        # Clear log
        self._clear_log()
        self._log(f"Starting upload to {config['repo_id']}...")
        self._log("")
        
        # Start upload thread
        # Clear any previous stop event and start the worker
        self.stop_event.clear()
        self.upload_thread = threading.Thread(target=self._run_upload, args=(config,), daemon=True)
        self.upload_thread.start()
    
    def _run_upload(self, config: dict):
        """Run the upload logic in a separate thread."""
        try:
            run_upload_logic(config, self._log)
            self.log_queue.put("✅ Upload completed successfully!")
            self.after(0, self._upload_finished, True)
        except Exception as e:
            msg = str(e)
            if "cancel" in msg.lower():
                self.log_queue.put("⚠️ Upload cancelled by user")
                self.after(0, self._upload_finished, False)
            else:
                self.log_queue.put(f"❌ Upload failed: {msg}")
                self.after(0, self._upload_finished, False)
    
    def _upload_finished(self, success: bool):
        """Called when upload finishes (from main thread)."""
        self.uploading = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        
        if success:
            self.status_label.configure(text="✅ Complete", text_color="green")
            messagebox.showinfo("Success", "Upload completed successfully!")
        else:
            self.status_label.configure(text="❌ Failed", text_color="red")
            messagebox.showerror("Error", "Upload failed. Check the log for details.")
    
    def _stop_upload(self):
        """Stop the upload (note: this is a basic implementation)."""
        if not self.uploading:
            return
        # Signal cancellation to worker
        self.stop_event.set()
        self._log("[Control] Stop requested; attempting to cancel upload...")
        self.status_label.configure(text="Cancelling...", text_color="orange")
        # Disable stop button to avoid repeated clicks
        self.stop_btn.configure(state="disabled")


def main():
    """Entry point for the GUI application."""
    app = HFUploaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
