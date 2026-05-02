---
title: BirdNET-Validator-App
emoji: "🐦"
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "5.23.1"
python_version: "3.11"
app_file: app.py
pinned: false
---

# BirdNET-Validator-App

BirdNET-Validator-App is a multi-purpose BirdNET workflow repository with two complementary entry points:

1. A Gradio-based web application for human validation of BirdNET detections in multi-project workflows.
2. A local command-line uploader for resumable Hugging Face dataset uploads with checkpoints, deduplication, and a Windows-friendly interactive flow.

The validator app focuses on review, authorization, and auditability. The uploader CLI focuses on reliable dataset ingestion for large audio collections.

## Contents

- [Overview](#overview)
- [Validator App](#validator-app)
- [Local Uploader CLI](#local-uploader-cli)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Typical Flows](#typical-flows)
- [Repository Structure](#repository-structure)
- [Troubleshooting](#troubleshooting)
- [Development Notes](#development-notes)

## Overview

This repository is designed for two high-confidence operations:

- controlled, multi-project human validation of detections
- reliable, resumable upload of large audio datasets to Hugging Face

The validator workflow emphasizes:

- controlled access by user and project
- rapid decision flow for detections
- auditability through append-only events
- conflict-aware updates for concurrent validators

The uploader workflow emphasizes:

- single-flow login → repo → scan → upload
- resumable sessions stored locally
- remote deduplication with a local cache
- progress tracking and checkpoint recovery
- compatibility with the validator app's expected dataset structure

## Validator App

The validator is a Gradio application for human review of BirdNET detections in multi-project workflows.

### Key Usability Features

1. Multi-project login with role-based access
2. Project selection for authorized datasets
3. Detection queue with filters and pagination
4. Audio loading on demand with ephemeral cache
5. Fast validation actions (positive, negative, uncertain, skip)
6. Concurrency-safe writes with optimistic lock feedback
7. Conflict resolution support and validation reporting

### Quick Start (Local)

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the app:

```bash
python app.py
```

Default port is `7860`.

### Runtime Configuration

Optional runtime configuration:

- `BIRDNET_DETECTIONS_FILE`: path to JSON file with detections grouped by project slug.
- `BIRDNET_VALIDATIONS_DIR`: custom directory for append-only validation events and snapshot files.
- `BIRDNET_PAGE_SIZE`: queue page size (default: `25`).
- `BIRDNET_PROJECTS_FILE`: JSON file with project catalog used at app startup.
- `BIRDNET_USER_ACCESS_FILE`: JSON file mapping users to project roles (`admin`/`validator`).
- `BIRDNET_INVITES_FILE`: JSON file storing pending invites.
- `BIRDNET_INVITE_TTL_HOURS`: invite expiration in hours (default: `72`).
- `BIRDNET_BOOTSTRAP_DIR`: base directory for bootstrap state files (`projects.json`, `user_access.json`, `invites.json`).
- `BIRDNET_ENABLE_DEMO_BOOTSTRAP`: set to `true` only for local/demo mode to load built-in sample users/projects.

Invite email settings (EmailJS):

- `BIRDNET_EMAILJS_ENABLED`: set to `true` to send invite emails via EmailJS.
- `BIRDNET_INVITE_EMAIL_ENABLED`: set to `true` to enable invite delivery.
- `BIRDNET_INVITE_EMAIL_SENDER`: sender label shown in the invite email.
- `BIRDNET_INVITE_EMAIL_LOGIN_URL`: login URL included in invitation instructions.
- `BIRDNET_EMAILJS_SERVICE_ID`: EmailJS service ID.
- `BIRDNET_EMAILJS_TEMPLATE_ID`: default/fallback EmailJS template ID.
- `BIRDNET_EMAILJS_TEMPLATE_ID_USERNAME_ONLY`: optional template for username-only mode.
- `BIRDNET_EMAILJS_TEMPLATE_ID_EMAIL_ONLY`: optional template for email-only mode.
- `BIRDNET_EMAILJS_TEMPLATE_ID_DUAL`: optional template for dual mode (username + email).
- `BIRDNET_EMAILJS_PUBLIC_KEY`: EmailJS public key.
- `BIRDNET_EMAILJS_ENDPOINT`: EmailJS API endpoint (default: `https://api.emailjs.com/api/v1.0/email/send`).
- `BIRDNET_EMAILJS_TIMEOUT_SECONDS`: request timeout in seconds (default: `20`).

### Validation Data Shapes

Detection seed file example:

```json
{
  "kenya-2024": [
    {
      "detection_key": "0000000000001001",
      "audio_id": "audio_1001",
      "scientific_name": "Cyanocorax cyanopogon",
      "confidence": 0.91,
      "start_time": 0.0,
      "end_time": 1.0
    }
  ]
}
```

Projects bootstrap file example (`BIRDNET_PROJECTS_FILE`):

```json
[
  {
    "project_slug": "kenya-2024",
    "name": "Kenya Survey 2024",
    "dataset_repo_id": "org/kenya-2024-dataset",
    "active": true
  }
]
```

User access bootstrap file example (`BIRDNET_USER_ACCESS_FILE`):

```json
{
  "admin_user": {
    "kenya-2024": "admin"
  },
  "validator_a": {
    "kenya-2024": "validator"
  }
}
```

### Typical Validation Flow

1. Login with a valid user.
2. Select an authorized project.
3. Load queue items and apply filters when needed.
4. Listen to selected audio and submit validation status.
5. Resolve conflicts when concurrent updates occur.
6. Export or inspect project validation report.

### Deploy on Hugging Face Spaces

1. Create a new Space with:
- SDK: `Gradio`
- Python: `3.11`

2. Push this repository to the Space.

3. Configure Variables/Secrets in the Space settings.

Required for production bootstrap:

- `BIRDNET_PROJECTS_FILE` (example: `docs/spaces/projects.sample.json`)
- `BIRDNET_USER_ACCESS_FILE` (example: `docs/spaces/user_access.sample.json`)

Optional runtime settings:

- `BIRDNET_DETECTIONS_FILE` (seed detections JSON)
- `BIRDNET_VALIDATIONS_DIR` (recommended: `/data/validations`)
- `BIRDNET_BOOTSTRAP_DIR` (recommended: `/data/bootstrap`)
- `BIRDNET_INVITES_FILE` (recommended: `/data/bootstrap/invites.json`)
- `BIRDNET_INVITE_TTL_HOURS` (default `72`)
- `BIRDNET_PAGE_SIZE` (default `25`)
- `BIRDNET_ENABLE_DEMO_BOOTSTRAP` (`false` in production)

Optional invite email settings:

- `BIRDNET_INVITE_EMAIL_ENABLED=true`
- `BIRDNET_INVITE_EMAIL_SENDER`
- `BIRDNET_INVITE_EMAIL_LOGIN_URL`
- `BIRDNET_EMAILJS_ENABLED`
- `BIRDNET_EMAILJS_SERVICE_ID`
- `BIRDNET_EMAILJS_TEMPLATE_ID`
- `BIRDNET_EMAILJS_PUBLIC_KEY`
- `BIRDNET_EMAILJS_ENDPOINT`
- `BIRDNET_EMAILJS_TIMEOUT_SECONDS`

4. For first smoke test only, you may temporarily set:

- `BIRDNET_ENABLE_DEMO_BOOTSTRAP=true`

Then log in with one of the demo users:

- `admin_user`
- `demo_user`
- `validator_demo`

5. After validation, switch to production bootstrap:

- Set `BIRDNET_ENABLE_DEMO_BOOTSTRAP=false`
- Provide real `BIRDNET_PROJECTS_FILE` and `BIRDNET_USER_ACCESS_FILE`

Notes:

- The app entrypoint reads `PORT` automatically in Spaces.
- Keep user/project bootstrap files private if they contain sensitive assignments.
- Use `/data` paths in Spaces to keep projects, invites, ACL, and validations across redeploys.
- Collaborative access is token-per-user: each collaborator logs in with their own Hugging Face token.

## Local Uploader CLI

The repository also includes a local uploader CLI designed for large dataset ingest and resume support.

### Release Pipeline

The repository includes a release pipeline that produces a portable uploader bundle and can publish it to Hugging Face.

One-command Windows pipeline:

```powershell
.\build\release_pipeline.ps1 -Version 0.1.0
```

Build and publish in one step:

```powershell
$env:HF_TOKEN = "hf_xxx"
.\build\release_pipeline.ps1 -Version 0.1.0 -PublishToHf -RepoId jrrribeiro/birdnet-uploader-releases -RepoType dataset
```

Validation-only step (recommended before publish):

```powershell
.\build\validate_release.ps1 -Version 0.1.0
```

Local build steps:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
python build/release_uploader.py --version 0.1.0
```

The build produces:

- a zipped release bundle under `build/release/`
- a `.sha256` checksum file next to the zip

To publish a release bundle to Hugging Face from a local machine:

```bash
set HF_TOKEN=hf_xxx
python build/publish_release_to_hf.py ^
  --repo-id jrrribeiro/birdnet-uploader-releases ^
  --repo-type dataset ^
  --bundle build\release\birdnet-uploader-0.1.0-windows.zip ^
  --checksum build\release\birdnet-uploader-0.1.0-windows.zip.sha256 ^
  --version 0.1.0
```

Recommended Hugging Face release repo layout:

```text
birdnet-uploader-releases/
  releases/
    v0.1.0/
      birdnet-uploader-0.1.0-windows.zip
      birdnet-uploader-0.1.0-windows.zip.sha256
```

Workflow on GitHub Actions:

- run the release workflow manually
- build the Windows executable with PyInstaller
- archive the bundle as a workflow artifact
- optionally upload the bundle and checksum to a Hugging Face repo

Recommended user-facing validation after publishing:

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
