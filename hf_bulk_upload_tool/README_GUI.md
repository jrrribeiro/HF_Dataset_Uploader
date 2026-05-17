# HF Dataset Uploader GUI – Protocol & Implementation Guide

## Overview

This directory contains a refactored version of `upload_dataset.py` designed for packaging as a portable, user-friendly GUI application using **CustomTkinter** and **PyInstaller**.

The project follows a **"Wrapper" architecture**:
- **Motor (Logic Layer)**: `upload_logic.py` — Pure upload logic, no UI dependencies
- **Cabin (UI Layer)**: `main_gui.py` — CustomTkinter GUI that calls the motor via callbacks
- **Build System**: PyInstaller configuration and build guide

---

## Architecture

### 1. **upload_logic.py** (Refactored Core)

**Key Changes from `upload_dataset.py`:**
- ✅ Removed `argparse` dependency (no CLI parsing in this version)
- ✅ Extracted `main()` into `run_upload_logic(config, logger_callback)`
- ✅ Replaced all `print()` calls with `logger(message)` callback
- ✅ Config is a Python dict instead of argparse Namespace
- ✅ 100% backward compatible with the original logic

**Function Signature:**
```python
def run_upload_logic(config: dict, logger: Callable[[str], None]) -> int:
    """
    Execute the upload process.
    
    Args:
        config: Dictionary with keys like 'repo_id', 'hf_token', 'segments', etc.
        logger: Callable that accepts strings for logging (e.g., textbox.insert)
    
    Returns:
        0 on success, raises Exception on failure
    """
```

**Config Keys (All Optional Except Marked):**
```python
config = {
    "hf_token": "...",              # ✅ Required
    "repo_id": "username/repo",     # ✅ Required (format: "owner/name")
    "segments": "/path/to/audio",   # ✅ Required (directory with files)
    "csv": "/path/to/file.csv",     # Optional
    "segments_path_in_repo": "audio",  # Default: "audio"
    "csv_path_in_repo": "index/detections.csv",  # Default
    "private": True,                # Default: True
    "resume": True,                 # Default: False
    "verify_remote": False,         # Default: False
    "verify_etag": False,           # Default: False
    "dry_run": False,               # Default: False
    "rate_limit_aware": True,       # Default: True
    "rate_limit_max_requests": 950, # Default: 950
    "rate_limit_window": 300,       # Default: 300 (5 min)
    "create_repo_attempts": 3,      # Default: 3
    "upload_attempts": 5,           # Default: 3
    "retry_backoff": 10.0,          # Default: 5.0
    "max_workers": 2,               # Default: 1
    "checkpoint_dir": "/path",      # Default: .checkpoints
    "commit_message": "Upload BirdNET segments",  # Default
}
```

### 2. **main_gui.py** (CustomTkinter GUI)

**UI Sections:**

1. **📋 Upload Configuration**
   - Repository ID input (username/dataset-name)
   - HF Token input (password field, hidden)
   - Segments folder picker (browse button)
   - CSV file picker (optional, browse button)

2. **⚙️ Options**
   - Private Repository (checkbox)
   - Resume mode (checkbox)
   - Verify remote files (checkbox)
   - Rate limiting (checkbox)
   - Worker threads (spinbox, 1-8)

3. **📝 Upload Progress**
   - Large textbox for real-time log output
   - Auto-scrolls to latest message
   - Read-only to prevent user edits

4. **🚀 Buttons**
   - Start Upload (green, initiates upload in background thread)
   - Stop (disabled until upload starts)
   - Clear Log (clears textbox)
   - Status label (Ready/Uploading/Complete/Failed)

**Threading Model:**
- Main thread: UI event loop (never blocks)
- Upload thread: Runs `run_upload_logic()` in background
- Log queue: Thread-safe message passing (Queue.Queue)

```python
# Upload runs in background; logs appear in real-time
Thread 1 (Main UI):
  → user clicks "Start"
  → spawns Thread 2
  → continues processing UI events
  ↓
Thread 2 (Upload):
  → calls run_upload_logic()
  → logs messages → queue → picked up by Thread 1 every 100ms
```

---

## How to Use (Development)

### 1. **Install Dependencies**

```powershell
# Base requirements
pip install -r ../requirements.txt

# GUI additions
pip install -r requirements_gui.txt
```

### 2. **Test the GUI**

```powershell
python main_gui.py
```

This opens the GUI window. Fill in test values and click "Start Upload" to test the flow.

### 3. **Build the EXE**

Follow instructions in **BUILD_GUIDE.md**, or quick version:

```powershell
pyinstaller --onefile --noconsole `
  --name "HF_Dataset_Uploader" `
  --collect-all customtkinter `
  --collect-all huggingface_hub `
  main_gui.py
```

Output: `dist/HF_Dataset_Uploader.exe` (standalone, ~250 MB)

---

## File Structure

```
hf_bulk_upload_tool/
├── upload_dataset.py         ← Original CLI version (unchanged)
├── upload_logic.py           ← NEW: Refactored logic (no CLI)
├── main_gui.py               ← NEW: CustomTkinter GUI
├── requirements_gui.txt      ← NEW: GUI dependencies
├── BUILD_GUIDE.md            ← NEW: Step-by-step build instructions
├── hf_uploader_gui.spec      ← NEW: PyInstaller spec file
└── .checkpoints/             ← Auto-created: stores resume checkpoints
```

---

## Key Design Decisions

### 1. **Why Refactor Logic?**
- Separating UI from logic makes the code reusable and testable
- The original `upload_dataset.py` is untouched; we added a new layer on top
- Future: can plug in different UIs (CLI, web, REST API) without changing logic

### 2. **Why Thread-Safe Logging?**
- If we called `textbox.insert()` directly from the upload thread, the GUI could crash
- Using `queue.Queue` ensures thread safety and smooth updates

### 3. **Why CustomTkinter?**
- **Modern look** compared to vanilla tkinter (dark mode, rounded buttons, etc.)
- **Pure Python** (no compiled dependencies)
- **Lightweight** (~5 MB)
- **Cross-platform** (Windows, macOS, Linux)

### 4. **Resume as Default?**
- `resume=True` by default in the GUI
- Prevents re-uploading files and respects HF rate limits
- Safe: checkpoint system tracks uploaded files locally

---

## Limitations & Future Improvements

### Current Limitations
1. ❌ **No mid-upload cancellation** — user can close app, but upload thread keeps running
2. ❌ **No progress bar** — only text log (could add % completion)
3. ❌ **No drag-and-drop** for file selection
4. ❌ **No dark mode toggle** (always dark)

### Potential Improvements (v2)
- ✅ Real-time progress bar showing % completion
- ✅ Ability to pause/resume upload mid-flight
- ✅ Save favorite configs (profiles)
- ✅ Drag-and-drop for folder/CSV inputs
- ✅ System tray icon with notifications
- ✅ Embedded browser to validate HF token in-app
- ✅ Light mode toggle
- ✅ Auto-update mechanism

---

## Testing Checklist

Before building the EXE, verify:

- [ ] `python main_gui.py` launches without errors
- [ ] All buttons and inputs are clickable
- [ ] File picker dialogs open correctly
- [ ] Token field is masked (shows `*` not plaintext)
- [ ] Log textbox updates in real-time
- [ ] Empty fields show validation errors
- [ ] Non-existent paths are caught and reported
- [ ] Start/Stop button states toggle correctly

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: customtkinter` | `pip install customtkinter` |
| `ModuleNotFoundError: huggingface_hub` | `pip install huggingface-hub` |
| GUI shows blank window | Run with `python -u main_gui.py` to force unbuffered output |
| EXE won't start | Double-click and check Windows event log for errors |
| "Only administrator can run this" | Right-click EXE → Properties → Compatibility → Run as admin |
| Antivirus blocks EXE | Add exception for the file or upload to VirusTotal.com to verify |

---

## Summary

This protocol transforms the CLI upload script into a professional, distributable GUI application:

1. **Logic Layer** (`upload_logic.py`): Pure, testable upload code
2. **UI Layer** (`main_gui.py`): User-friendly CustomTkinter interface  
3. **Build System** (PyInstaller): Creates a standalone `.exe` for non-technical users
4. **Threading**: Ensures UI never freezes during long uploads
5. **Logging**: Real-time progress visible in the GUI

Users can now:
- ✅ Double-click an `.exe` to upload datasets
- ✅ No need to understand Python, CLI, or argparse
- ✅ Safe resume if interrupted
- ✅ Real-time progress feedback

---

## Next Steps

1. **Test locally**: `python main_gui.py`
2. **Build EXE**: Follow BUILD_GUIDE.md
3. **Distribute**: Share the `.exe` with non-technical users
4. **Iterate**: Gather feedback, add improvements from "Future Improvements" section

Happy uploading! 🚀
