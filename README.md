---
title: BirdNET-Uploader-App
emoji: "🐦"
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "5.23.1"
python_version: "3.11"
app_file: app.py
pinned: false
---

# BirdNET Uploader

A robust, resumable uploader for audio segments and detection metadata to Hugging Face datasets. Choose your upload path based on data size:

- **Web Path** (~1 GB): Browser-based archive upload with live progress
- **CLI Path** (unlimited): Local Windows portable or Python environment for large datasets

## Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [Configuration](#configuration)
- [Typical Workflows](#typical-workflows)
- [CLI Reference](#cli-reference)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Overview

This repository is a focused tool for reliably uploading large audio collections and optional detection CSVs to Hugging Face datasets. It emphasizes:

- **Two upload paths**: Small archives via web UI (≤1 GB) or unlimited via CLI/Windows portable
- **Resumable sessions**: Checkpoints stored locally allow recovery from interruptions
- **Remote deduplication**: Hash-based checking prevents re-uploading files
- **Live progress**: Real-time feedback during uploads
- **Metadata generation**: Automatic manifest, CSV, and Parquet shard creation

## Quick Start

### Web UI (Browser-Based, ≤1 GB)

1. Open [BirdNET Uploader on Hugging Face Spaces](https://huggingface.co/spaces/YOUR_ORG/birdnet-uploader)
2. Enter your **Hugging Face token** (from [hf.co/settings/tokens](https://huggingface.co/settings/tokens))
3. Specify your dataset **repo ID** (`username/dataset-name`)
4. Upload a `.tar.gz`, `.zip`, or `.tar` archive containing audio files (optionally include a CSV)
5. Watch live progress and get a summary when complete

**Note**: Archive size is limited to ~1 GB due to browser memory constraints. For larger datasets, use the Windows portable or CLI.

### Windows Portable (Unlimited Size)

1. [Download birdnet-uploader-1.0.4-windows.zip](https://huggingface.co/datasets/jrrribeiro/birdnet-uploader-releases/resolve/main/releases/v1.0.4/birdnet-uploader-1.0.4-windows.zip) (~109 MB)
2. Extract the archive
3. Double-click `birdnet-uploader.exe` to launch the web UI
   - Or use CLI commands: `birdnet-uploader login`, `birdnet-uploader upload --help`
   - See [WINDOWS_PORTABLE_SETUP.md](./WINDOWS_PORTABLE_SETUP.md) for detailed instructions
   - Issues? Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)

### Local CLI (Python 3.11+)

```bash
# Install
pip install -r requirements.txt

# Login (stores token securely)
python app.py login

# Upload local folder
python app.py upload \
  --repo-id username/dataset-name \
  --segments /path/to/audio/folder \
  --csv /path/to/detections.csv (optional) \
  --workers 4

# Check upload status
python app.py resume <session-id>
```

## Features

### Archive Upload (Web)
- **Supported formats**: `.tar`, `.tar.gz`, `.zip`
- **Size limit**: ~1 GB (due to browser constraints)
- **Automatic extraction**: Archives are extracted server-side
- **Live progress**: Real-time upload percentage with file counts

### Large Dataset Upload (CLI)
- **Unlimited size**: No practical file size limit
- **Resumable sessions**: Stop and resume uploads without re-uploading
- **Deduplication**: Remote hash checking prevents duplicate uploads
- **Parallel workers**: Upload multiple files concurrently (default: 4)
- **Progress tracking**: JSON checkpoints for recovery

### Dataset Structure
Both paths produce the same Hugging Face dataset structure:
```
dataset-repo/
├── audio/              # Uploaded audio files (organized by species if CSV)
├── index/
│   ├── manifest.json   # Metadata summary
│   ├── detections.csv  # Original detection metadata (if provided)
│   └── shards/         # Parquet shards (10k rows each) for efficient indexing
```

## Configuration

### Environment Variables

```bash
# Web UI port (default: 7860)
BIRDNET_UPLOADER_PORT=8000

# CLI mode (use app.py as CLI instead of web UI)
BIRDNET_UPLOADER_CLI=true

# Session storage (default: ~/.birdnet-uploader/sessions)
BIRDNET_UPLOADER_SESSION_DIR=/custom/path/sessions

# Cache directory (default: ~/.birdnet-uploader/cache)
BIRDNET_UPLOADER_CACHE_DIR=/custom/path/cache

# Hugging Face token (alternative to secure storage)
HF_TOKEN=hf_xxxxxxxxxxxx
```

## Typical Workflows

### Scenario 1: Small Archive Upload (≤1 GB)
1. Create a `.tar.gz` archive of audio files with optional CSV
2. Use web UI at [Hugging Face Spaces](https://huggingface.co/spaces/YOUR_ORG/birdnet-uploader)
3. Paste token, enter dataset ID, upload archive
4. **Done** - files appear in dataset within minutes

### Scenario 2: Large Archive on Windows
1. Create a `.tar.gz` or `.zip` archive (any size)
2. Download and extract Windows portable
3. Double-click `birdnet-uploader.exe` → launches web UI on localhost:7860
4. Same workflow as web UI, but runs locally (no size limits)

### Scenario 3: Local Folder Upload (CLI)
1. Navigate to audio folder root in terminal
2. Run: `python app.py upload --repo-id user/dataset --segments .`
3. Watch progress in real-time
4. Resume if interrupted: `python app.py resume <session-id>`

## CLI Reference

### Login

```bash
python app.py login
```
Stores Hugging Face token securely in system keyring.

### Upload

```bash
python app.py upload \
  --repo-id user/dataset \
  --segments /path/to/audio \
  --csv /path/to/detections.csv \      # Optional
  --workers 4 \                         # Default: 4
  --session-id my-session \             # Optional: for resumable uploads
  --remote-base my_audio_folder \       # Default: "audio"
  --dry-run                             # Show what would be uploaded
  --verbose                             # Detailed logging
```

### Scan

```bash
python app.py scan --segments /path/to/audio
```
Shows file count, total size, and species breakdown.

### Resume

```bash
python app.py resume <session-id>
```
Checks session status and shows last checkpoint.

### Init Repo

```bash
python app.py init-repo \
  --repo-id user/dataset \
  --private                             # Default: private
```
Creates dataset structure on Hugging Face.

## Resumable Uploads

Session checkpoints are saved locally as JSON. If an upload is interrupted:

```bash
# Check session status
python app.py resume abc-session-id-xyz

# Resume from last checkpoint (automatically skips already-uploaded files)
python app.py upload \
  --repo-id user/dataset \
  --segments ./audio \
  --session-id abc-session-id-xyz
```

Checkpoint location: `~/.birdnet-uploader/sessions/upload-YYYYMMDDTHHMMSSZ/checkpoint.json`

## Authentication

### Secure Token Storage
- **First time**: `python app.py login` stores token in system keyring (Windows, macOS, Linux)
- **Environment override**: `HF_TOKEN=hf_xxxx python app.py upload ...`
- **Explicit flag**: `python app.py upload --token hf_xxxx ...`

### Token Permissions
Ensure your token has `write` permissions on the target dataset:
1. Go to [hf.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Create or edit a token
3. Set permissions: `repo > write` (not `read`)
4. Restrict to specific repo if desired

## Troubleshooting

### "Upload exceeds 1 GB limit"
- Switch to Windows portable or CLI for larger datasets
- Compress archive more aggressively

### "CSV upload failed"
- Ensure CSV has proper headers and encoding (UTF-8)
- File size should match audio files metadata (e.g., `audio_file` column)

### "Session has no checkpoint"
- Session ID may be invalid or expired
- Check `~/.birdnet-uploader/sessions/` for available sessions
- Restart upload without `--session-id` to create a new session

### Network timeouts on large files
- Use CLI with more workers: `--workers 8`
- Check internet stability
- Resume from checkpoint if interrupted

## Development

### Build Windows Portable

```bash
# Install build dependencies
pip install pyinstaller

# Build release
python build/release_uploader.py --version 1.0.0

# Output: build/release/birdnet-uploader-1.0.0-windows.zip
```

### Local Testing

```bash
# Web UI
python app.py

# CLI
python app.py --help
python app.py login
python app.py scan --segments ./test_audio
python app.py upload --repo-id my-test/uploader --segments ./test_audio --dry-run
```

## Architecture

### Core Components

- **`src/uploader/web_ui.py`**: Gradio interface for browser uploads
- **`src/uploader/main.py`**: Click CLI for local uploads
- **`src/uploader/batch_uploader.py`**: File upload orchestration with retries
- **`src/uploader/session_manager.py`**: Checkpoint persistence and resumability
- **`src/uploader/deduplicator.py`**: Remote hash checking to avoid re-uploads
- **`src/uploader/scanner.py`**: Local folder scanning and metadata extraction
- **`src/uploader/manifest.py`**: Dataset metadata and Parquet shard generation

### Data Flow

1. **Upload**: Archive extraction or folder scan
2. **Deduplication**: Check remote hashes to skip existing files
3. **Upload**: Push files to HF dataset in parallel
4. **Metadata**: Generate and upload manifest + CSV + Parquet shards
5. **Checkpoint**: Save session state for resumable recovery

## Limitations

- Web UI: ~1 GB per upload (browser constraint)
- CSV: Must have `audio_file` or `file` column for audio file names
- Audio formats: `.wav`, `.mp3`, `.flac`, `.ogg`, `.m4a`
- Archive formats: `.tar`, `.tar.gz`, `.zip`

## License

[MIT License](LICENSE)

1. Download the zip from Hugging Face.
2. Unzip into a clean folder.
3. Run the executable without Python installed.
4. Authenticate with a Hugging Face token.
5. Create a session and confirm resume/recovery works.

### What It Does

- authenticates with a Hugging Face token stored in the OS keyring
- creates or validates dataset repositories
- scans a local audio folder recursively
- computes per-file SHA-256 hashes
- deduplicates against a cached remote index
- uploads files with retries and session checkpoints
- resumes from the last checkpoint after close or crash

### Main Commands


The CLI entrypoint is:

```bash
python -m src.uploader_cli.main --help
```

Commands:

- `login`: validate and store a Hugging Face token
- `init-repo`: create and initialize a dataset repository
- `scan`: scan a local folder and summarize audio files
- `start`: create a local upload session checkpoint
- `resume`: print the saved checkpoint for a session

### Example Workflow

```bash
# Authenticate once
python -m src.uploader_cli.main login

# Create or initialize the dataset repository
python -m src.uploader_cli.main init-repo --repo-id alice/birdnet-2026 --private

# Inspect the local folder before upload
python -m src.uploader_cli.main scan --segments C:\audio\segments

# Create a resumable local session checkpoint
python -m src.uploader_cli.main start --repo-id alice/birdnet-2026 --segments C:\audio\segments


# Resume and inspect the checkpoint later
python -m src.uploader_cli.main resume upload-20260429T120000Z
```

### Upload Engine Building Blocks

The uploader CLI is built from the following modules:

- `src/uploader_cli/auth_service.py`: token validation and keyring storage
- `src/uploader_cli/repo_service.py`: dataset creation and structure initialization
- `src/uploader_cli/scanner.py`: recursive audio discovery and metadata collection
- `src/uploader_cli/hash_utils.py`: streaming SHA-256 helpers
- `src/uploader_cli/deduplicator.py`: remote index cache and skip/upload decisions
- `src/uploader_cli/session_manager.py`: checkpoint and session metadata persistence
- `src/uploader_cli/batch_uploader.py`: retrying upload orchestration
- `src/uploader_cli/error_handler.py`: user-friendly error formatting

### Local Data Layout

The uploader stores local state under the user's profile directory by default:

```text
~/.birdnet-uploader/
  sessions/
    upload-YYYYMMDDTHHMMSSZ/
      metadata.json
      checkpoint.json
  cache/
    dedup/
      <repo-hash>.json
  logs/
```

Environment overrides are supported:

- `BIRDNET_UPLOADER_SESSION_DIR`
- `BIRDNET_UPLOADER_CACHE_DIR`
- `BIRDNET_UPLOADER_LOG_DIR`

### Dataset Layout Expected by the Validator

The uploader is designed to preserve the validator's expected structure:

```text
audio/{project_slug}/...        # uploaded audio files
index/shards/...                # parquet shard files
index/manifest.json             # index manifest
validations/...                 # validation outputs
audit/ingestion-runs/...        # ingestion run history
```

### Uploader Configuration

Runtime constants are centralized in `src/uploader_cli/config.py`:

- `APP_NAME`
- `SCHEMA_VERSION`
- `AUDIO_EXTENSIONS`
- `INDEX_SHARD_SIZE`
- `MAX_BATCH_SIZE`
- `RETRY_MAX_ATTEMPTS`
- `RETRY_INITIAL_BACKOFF_SECONDS`
- `RETRY_MAX_BACKOFF_SECONDS`
- `KEYRING_SERVICE`
- `KEYRING_ACCOUNT`

### Resumability Guarantees

The uploader uses local checkpoints so it can recover from:

- process crashes
- app close
- transient network failures
- partial progress during large uploads

The checkpoint stores session metadata and cumulative counters such as:

- uploaded count
- skipped count
- failed count
- last completed file
- last failed file
- total uploaded bytes

## Quick Start

### Local Development

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the validator app:

```bash
python app.py
```

4. Run the uploader CLI help:

```bash
python -m src.uploader_cli.main --help
```

### First-Time Uploader Setup

1. Log in with a Hugging Face token:

```bash
python -m src.uploader_cli.main login
```

2. Validate your target repository exists or create it:

```bash
python -m src.uploader_cli.main init-repo --repo-id alice/birdnet-2026 --private
```

3. Scan your local dataset folder:

```bash
python -m src.uploader_cli.main scan --segments C:\audio\segments
```

4. Start a resumable session:

```bash
python -m src.uploader_cli.main start --repo-id alice/birdnet-2026 --segments C:\audio\segments
```

## Configuration

### Validator App Environment Variables

- `BIRDNET_DETECTIONS_FILE`
- `BIRDNET_VALIDATIONS_DIR`
- `BIRDNET_PAGE_SIZE`
- `BIRDNET_PROJECTS_FILE`
- `BIRDNET_USER_ACCESS_FILE`
- `BIRDNET_INVITES_FILE`
- `BIRDNET_INVITE_TTL_HOURS`
- `BIRDNET_BOOTSTRAP_DIR`
- `BIRDNET_ENABLE_DEMO_BOOTSTRAP`
- `BIRDNET_EMAILJS_ENABLED`
- `BIRDNET_INVITE_EMAIL_ENABLED`
- `BIRDNET_INVITE_EMAIL_SENDER`
- `BIRDNET_INVITE_EMAIL_LOGIN_URL`
- `BIRDNET_EMAILJS_SERVICE_ID`
- `BIRDNET_EMAILJS_TEMPLATE_ID`
- `BIRDNET_EMAILJS_TEMPLATE_ID_USERNAME_ONLY`
- `BIRDNET_EMAILJS_TEMPLATE_ID_EMAIL_ONLY`
- `BIRDNET_EMAILJS_TEMPLATE_ID_DUAL`
- `BIRDNET_EMAILJS_PUBLIC_KEY`
- `BIRDNET_EMAILJS_ENDPOINT`
- `BIRDNET_EMAILJS_TIMEOUT_SECONDS`

### Uploader CLI Environment Variables

- `BIRDNET_UPLOADER_SESSION_DIR`
- `BIRDNET_UPLOADER_CACHE_DIR`
- `BIRDNET_UPLOADER_LOG_DIR`

## Typical Flows

### Validation Flow

1. Login with a valid user.
2. Select an authorized project.
3. Load queue items and apply filters when needed.
4. Listen to selected audio and submit validation status.
5. Resolve conflicts when concurrent updates occur.
6. Export or inspect project validation report.

### Upload Flow

1. Authenticate once with a Hugging Face token.
2. Create or validate a dataset repository.
3. Scan the local folder recursively.
4. Deduplicate against remote files.
5. Upload with retries and checkpoints.
6. Resume later from the saved session metadata if needed.

## Repository Structure

- `app.py`: validator app entrypoint
- `src/auth`: authentication/session and ACL logic
- `src/domain`: domain models
- `src/repositories`: in-memory and append-only persistence
- `src/services`: queue, validation, and audio fetch services
- `src/ui`: Gradio interface composition and callbacks
- `src/uploader_cli`: local uploader CLI, session persistence, deduplication, and retrying uploads
- `tests`: unit and integration test suites
- `docs`: collaborative workflow and QA checklists

## Project Status

Validator workflow is active and under continuous development, with emphasis on reliability, auditability, and operator productivity.

The uploader CLI is being built as a companion local workflow for large ingest tasks, with a focus on resumability and validator compatibility.

## FAQ

### Is this app intended for production use?

Yes, for validator workflows. It is structured for multi-project access control, audit-friendly writes, and collaborative validation.

### Is the uploader CLI meant to replace the validator app?

No. It is a companion tool for large dataset uploads and repository initialization.

### Does the app preload all audio files?

No. Audio is fetched on demand for the selected detection, helping keep memory and network usage under control.

### Can multiple validators work at the same time?

Yes. The validation flow uses optimistic concurrency checks to detect and handle conflicting updates.

### Can this run on Hugging Face Spaces?

Yes. The validator app is designed for Gradio deployment on Hugging Face Spaces.

### Can the uploader resume after closing the app?

Yes. It persists checkpoints and session metadata locally and can be resumed later.

### Does the uploader support deduplication?

Yes. It checks the remote dataset index, caches the remote file list locally, and skips files that are already present.

## Troubleshooting

### The app does not start locally

1. Confirm Python 3.11+ is active.
2. Reinstall dependencies with `pip install -r requirements.txt`.
3. Run `python app.py` from the repository root.

### Port 7860 is already in use

Stop the existing process using that port, or launch after setting a different `GRADIO_SERVER_PORT` environment variable.

### Login works but no project appears

Your user likely has no project assignment. Verify `BIRDNET_PROJECTS_FILE` and `BIRDNET_USER_ACCESS_FILE`, or add project access through the admin flow.

### Seed warning appears in Validation tab

If you see a seed warning banner:

1. Verify `BIRDNET_DETECTIONS_FILE` points to an existing file.
2. Confirm the file is valid UTF-8 JSON.
3. Confirm each project maps to a list of detections, or each list item includes `project_slug`.
4. If needed, unset `BIRDNET_DETECTIONS_FILE` to fall back to default demo detections.

### Audio does not load for a detection

Check that:

1. `audio_id` exists and is valid for the selected project.
2. The dataset repository is reachable.
3. You have permission to read the project dataset.

### I get conflict messages while validating

This means another validator updated the same detection first. Refresh and reapply your decision on the newest version.

### The uploader says the token cannot be saved

Make sure your OS keyring backend is available. On Windows, the default credential store should work automatically.

### The uploader skips files unexpectedly

It may have found them in the remote dataset index cache. Clear the uploader cache directory if you want to force a fresh remote listing.

### Resume shows an empty checkpoint

Check that you ran the uploader `start` command at least once and that the session directory still exists.

## Recent Updates

- Integrated Validation tab flow in the multi-project app (no placeholder stage).
- Added project-scoped queue badge (`Queue: N`) and improved queue context feedback.
- Added seed-file warning banner with actionable remediation guidance in Validation.
- Standardized all user-facing UI text and feedback messages in English.
- Updated authentication/session timestamps to timezone-aware UTC handling.
- Added a local uploader CLI with login, repository initialization, scan, deduplication, checkpointing, and resumable upload foundations.

## Related Documents

- `BIRDNET_UPLOADER_REDESIGN.md`: uploader UX and architecture notes
- `SPRINT_ROADMAP.md`: implementation roadmap
- `SPRINT1_KICKOFF.md`: sprint kickoff details
