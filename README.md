---
title: BirdNET Uploader App
emoji: "🐦"
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "5.0.0"
python_version: "3.11"
app_file: app.py
pinned: false
---

# BirdNET-Uploader-App

BirdNET-Uploader-App is a Gradio application for structured ingestion of BirdNET detections in multi-project workflows.

It provides an operator-focused upload interface with deterministic key generation, resumable batch processing, index artifact creation, and audit-ready run reporting for Hugging Face Datasets.

## Objective
This app centralizes ingestion for bioacoustics projects by:

- matching BirdNET detection rows with segment files
- creating deterministic detection keys
- uploading data in resumable batches
- generating index shards and manifest metadata
- producing audit-friendly ingestion reports

## Usability

The app supports two execution modes:

1. Dry-run mode
- validates matching quality before upload
- reports matched, unmatched, and ambiguous rows

2. Upload mode
- performs actual upload to Hugging Face Dataset repo
- supports retry/backoff, resume state, and batch control
- updates index and manifest artifacts for downstream consumers

This flow reduces manual errors and gives operators confidence before publishing data.

## Input Requirements

- BirdNET detections CSV with required columns
- Segments root directory containing .wav files
- Target Hugging Face dataset repo in owner/repo format

## Quick Start (Local)

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the app:

```bash
python app.py
```

Default port is 7862. You can change it using environment variable `BIRDNET_UPLOADER_PORT`.

## Typical Workflow

1. Fill `project_slug` and `dataset_repo`.
2. Select detections CSV and segments root folder.
3. Run Dry-run and inspect output JSON.
4. Fix data issues if unmatched/ambiguous rows are high.
5. Run Upload mode when quality is acceptable.
6. Save run report for audit and reproducibility.

## CLI Commands (Optional)

The same ingestion pipeline is available by CLI:

```bash
python -m cli.hf_dataset_cli ingest-segments \
  --project-slug ppbio-rabeca \
  --dataset-repo USER/birdnet-ppbio-rabeca-dataset \
  --detections-csv detections.csv \
  --segments-root "C:\\BirdNET Segments" \
  --dry-run \
  --report-file .ingest-dry-run-report.json
```

```bash
python -m cli.hf_dataset_cli ingest-segments \
  --project-slug ppbio-rabeca \
  --dataset-repo USER/birdnet-ppbio-rabeca-dataset \
  --detections-csv detections.csv \
  --segments-root "C:\\BirdNET Segments" \
  --batch-size 200 \
  --shard-size 10000 \
  --max-retries 3 \
  --retry-backoff-seconds 1.0 \
  --resume-state-file .ingest-segments-state.json \
  --report-file .ingest-run-report.json
```

## Repository Structure

- `app.py`: uploader app entrypoint
- `src/ui/upload_app_factory.py`: Gradio UI and actions
- `cli/hf_dataset_cli.py`: ingestion engine and commands

## Operational Notes

- Use dry-run first for every new project or new data source.
- Keep run reports for traceability.
- Prefer project-level dataset repos for cleaner access control.
- For public deployment, use Hugging Face Spaces with repository sync from GitHub.

## Status

Uploader workflow is implemented and ready for staged validation in real project datasets.

