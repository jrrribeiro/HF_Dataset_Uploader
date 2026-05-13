# BirdNET HF Bulk Upload Tool

This folder contains a standalone script for uploading a large BirdNET segment tree to Hugging Face Datasets without touching the Uploader App codebase.

## What it does

- Creates the dataset repository if it does not exist
- Uploads a large local folder directly to the dataset while preserving the internal species subfolder structure
- Optionally uploads one CSV file to a separate path in the repo
- Uses the Hugging Face Hub client directly, with conservative retry behavior and large-upload friendly defaults

## Files

- `upload_dataset.py` - command line uploader
- `requirements.txt` - minimal dependency list for this folder

## Install

From the root of `BirdNET-Uploader-App`:

```powershell
python -m pip install -r .\hf_bulk_upload_tool\requirements.txt
```

## Run

### Windows launcher

If you prefer a single PowerShell entry point, use:

```powershell
.\hf_bulk_upload_tool\run_upload.ps1 -HfUsername jrrribeiro -RepoName meu-dataset -Segments "C:\caminho\para\pasta\de\segmentos" -Private
```

Add `-Csv "C:\caminho\opcional\detections.csv"` when you want to upload the metadata CSV too.

### Using repo id directly

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id jrrribeiro/meu-dataset `
  --segments "C:\caminho\para\pasta\de\segmentos" `
  --csv "C:\caminho\opcional\detections.csv" `
  --private
```

### Using username and dataset name separately

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --hf-username jrrribeiro `
  --repo-name meu-dataset `
  --segments "C:\caminho\para\pasta\de\segmentos" `
  --csv "C:\caminho\opcional\detections.csv" `
  --private
```

### Dry run

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id jrrribeiro/meu-dataset `
  --segments "C:\caminho\para\pasta\de\segmentos" `
  --dry-run
```

## Recommended layout in the dataset

The script uploads the segments folder under `audio/` by default, preserving the folder tree inside it. If your local folder is organized by species, that same structure will appear in the dataset.

Optional CSV files are uploaded to `index/detections.csv` by default.

## Notes for large uploads

- Start with `--private` and one small test folder if you want to verify permissions first
- Keep the machine awake during the upload
- Avoid renaming or moving files while the upload is running
- If your network is unstable, re-run the same command; the script retries the main network operations

## Environment defaults used by the script

- `HF_HUB_ETAG_TIMEOUT=20`
- `HF_HUB_DOWNLOAD_TIMEOUT=120`
- `HF_XET_HIGH_PERFORMANCE=1`

You can override them before launching the script if needed.