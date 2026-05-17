# hf_upload_script

Standalone project for CLI-based operations.

## Objective
*   Execute the upload workflow via command-line interface.
*   Maintain clear separation of logic from the GUI-based application (`hf_upload_app`).

## Installation
```bash
python -m pip install -r requirements.txt
```

## Usage
```bash
python app.py --help
```

## Repository Structure
*   `app.py`: CLI entrypoint.
*   `uploader/`: Upload modules and support logic.
*   `requirements.txt`: Project dependencies.
*   `Temp/`: Local temporary files.

## Notes
*   This module operates independently from `hf_upload_app`.
*   Use `Temp/` for temporary outputs, local tests, and intermediate artifacts.
