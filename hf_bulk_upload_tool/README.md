# BirdNET HF Bulk Upload Tool

Standalone, production-ready script for uploading large BirdNET datasets to Hugging Face with built-in rate-limit handling, resume support, and progress tracking.

## Features

✅ **Fast uploads** – Uses `HfApi.upload_large_folder` when available; falls back to parallel per-file upload  
✅ **Rate-limit safe** – 429-aware backoff; per-file throttling (default 0.5s delay) to avoid HF API quota exhaustion  
✅ **Resume-friendly** – Checkpoints track uploaded files + SHA-256 hashes; skip already-uploaded files on retry  
✅ **Progress visibility** – Aggregated progress bar with ETA (not verbose per-file logs)  
✅ **Audit logs** – CSV progress log + JSON summary with upload stats  
✅ **Flexible** – Verify remote files by size/ETag; customize worker count, delays, and retry policy  

## Install

Activate the venv and install dependencies:

```powershell
& .\.venv\Scripts\Activate.ps1
pip install -r .\hf_bulk_upload_tool\requirements.txt
```

## Quick Start

### Dry-run (validate before uploading)

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --csv "C:\path\to\detections.csv" `
  --private --dry-run
```

### Upload (rate-limit safe defaults)

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --csv "C:\path\to\detections.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private
```

### Resume (skip already-uploaded files)

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --csv "C:\path\to\detections.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --resume --verify-remote
```

### Inspect only (no upload)

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --private --resume --resume-only
```

## Dataset Layout

By default, the script uploads:
- `segments/` folder → `audio/` in the dataset (preserves subfolder structure)
- `CSV` file → `index/detections.csv` in the dataset

Example:
```
Local:
  segments/
    Species A/
      file1.wav
      file2.wav
    Species B/
      file3.wav

Dataset:
  audio/Species A/file1.wav
  audio/Species A/file2.wav
  audio/Species B/file3.wav
  index/detections.csv
```

## Large Upload Tuning

### If hitting rate limits (429)

1. **Wait and retry** (~5 min cooldown): the script uses checkpoints, so files already uploaded are skipped
2. **Increase per-file delay**: `--per-file-delay 1.0` (default is 0.5s)
3. **Reduce workers**: `--max-workers 1` (default is 1, but adjust if needed)

Example conservative command:
```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --max-workers 1 --per-file-delay 1.0
```

### For very large datasets (50+ GB)

Increase HF timeouts:

```powershell
$env:HF_HUB_ETAG_TIMEOUT = '60'
$env:HF_HUB_DOWNLOAD_TIMEOUT = '300'
$env:HF_XET_HIGH_PERFORMANCE = '1'
```

Then run the upload.

## Checkpoints & Logging

The script saves:
- `.checkpoints/<repo_id>.json` – list of uploaded files + SHA-256 hashes
- `.checkpoints/progress.csv` – per-file status, elapsed time, errors
- `.checkpoints/<repo_id>.summary.json` – total stats (files, bytes, elapsed time)

Use `--checkpoint-dir <path>` to customize the checkpoint location.

## All Options

```
python .\hf_bulk_upload_tool\upload_dataset.py --help
```

Key arguments:
| Option | Default | Description |
|--------|---------|-------------|
| `--repo-id` | (required) | `username/dataset-name` |
| `--segments` | (required) | Local folder path |
| `--csv` | (none) | Optional CSV file to upload |
| `--hf-token` | (prompt) | HF write token (or use `HF_TOKEN` env var) |
| `--private` | true | Create private dataset (or `--public`) |
| `--max-workers` | 1 | Parallel upload threads (per-file fallback) |
| `--per-file-delay` | 0.5 | Seconds between per-file uploads |
| `--resume` | false | Skip already-uploaded files |
| `--verify-remote` | false | Verify remote file size/ETag on resume |
| `--verify-etag` | false | Prefer ETag over size checks |
| `--resume-only` | false | Inspect repo without uploading |
| `--dry-run` | false | Validate args; no network calls |
| `--checkpoint-dir` | `.checkpoints` | Where to store checkpoints |

## Troubleshooting

**"Failed to get upload mode: 429"**  
HF rate limit hit. Wait 5 min, then re-run (script will skip completed files).

**"No such file or directory" (temp junction)**  
Rare on Windows. Try increasing `--per-file-delay` or reduce `--max-workers`.

**"Failed to create audio junction" (Windows)**  
Ensure temp folder has write permissions. Or use `--max-workers 1 --per-file-delay 0.5`.

**"Authentication failed"**  
Check your HF token is valid and has write permission to the target repo.

## Notes

- **Keep machine awake** during uploads (no sleep mode)
- **Stable network** strongly recommended for 50+ GB uploads
- **Re-run is safe** – checkpoints prevent re-uploading files
- **Start small** – test with a tiny folder first if unsure about permissions

## Environment Variables

Override defaults:
```powershell
$env:HF_HUB_ETAG_TIMEOUT = '60'
$env:HF_HUB_DOWNLOAD_TIMEOUT = '300'
$env:HF_XET_HIGH_PERFORMANCE = '1'
$env:HF_TOKEN = '<your_token>'  # avoid typing --hf-token each time
```