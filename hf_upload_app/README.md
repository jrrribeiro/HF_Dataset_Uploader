# hf_upload_app

Standalone project for GUI-based operations and executable packaging.

## Objective
*   Execute the graphical user interface.
*   Package the application as a standalone, portable executable.

## Installation
```bash
python -m pip install -r requirements.txt
```

## Running Locally
```bash
python app.py
```

## Packaging Executable (PyInstaller)
```bash
python -m pip install pyinstaller
pyinstaller hf_upload_app.spec --noconfirm
```

## Repository Structure
*   `app.py`: GUI/CLI entrypoint.
*   `uploader/`: Upload modules and interface logic.
*   `hf_upload_app.spec`: PyInstaller configuration.
*   `launcher.bat`: Local launcher for Windows.
*   `requirements.txt`: Project dependencies.
*   `Temp/`: Local temporary files.

## Notes
*   This module operates independently from `hf_upload_script`.
*   Use `Temp/` for logs, caches, and temporary artifacts.
