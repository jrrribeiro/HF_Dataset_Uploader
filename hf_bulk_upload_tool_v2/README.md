# BirdNET HF Bulk Upload Tool v2

This version is a clean HF-first uploader for large BirdNET segment folders.

## What it does

- Creates the dataset repo if needed
- Uploads the segment tree with `HfApi.upload_large_folder(...)`
- Uploads an optional detections CSV to `index/detections.csv`
- Uses the same local species subfolder tree as the source folder

## Files

- `upload_dataset_v2.py` - standalone uploader
- `run_upload.ps1` - Windows launcher

## Run

### PowerShell launcher

```powershell
.\hf_bulk_upload_tool_v2\run_upload.ps1 `
  -RepoId "jrrribeiro/PPBIO_Audio_Library" `
  -Segments "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Segments" `
  -Csv "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Analyzer\00_ALL_DETECTIONS.csv" `
  -Private
```

Add `-HfToken` if you prefer passing the token explicitly. Otherwise set `HF_TOKEN` in the environment or let the script prompt.

### Python directly

```powershell
python .\hf_bulk_upload_tool_v2\upload_dataset_v2.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Segments" `
  --csv "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Analyzer\00_ALL_DETECTIONS.csv" `
  --private
```

## Notes

- This version uses the HF optimized large-folder API first.
- If you need a subset upload, use `--allow-patterns` or `--ignore-patterns`.