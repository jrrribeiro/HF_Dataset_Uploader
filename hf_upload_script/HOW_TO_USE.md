# HF Upload Script: How To Use

Upload large BirdNET audio segment folders to Hugging Face Datasets with
resume-friendly uploads, sharded folders, compact progress, and a logical
dataset index.

---

## What This Script Does

The default upload mode is designed for datasets with thousands to millions of
small audio files.

It will:

| Step | What happens |
| --- | --- |
| 1. Scan local files | Reads the local `Segments` folder once. |
| 2. Read remote index | Lists files already present in the Hugging Face dataset once. |
| 3. Build upload plan | Decides what should be uploaded and what should be skipped. |
| 4. Stage files | Creates a Hugging Face-ready folder layout using hardlinks by default. |
| 5. Write logical index | Writes `index/files.parquet` mapping original paths to stored paths. |
| 6. Upload | Uses Hugging Face `upload_large_folder` for resumable large uploads. |

The physical dataset may be split into many shard folders, but validation tools
can still treat each species or source folder as one logical group by reading
`index/files.parquet`.

---

## Expected Input

### Audio Folder

Recommended structure:

```text
Segments/
  Accipiter striatus/
    file_001.wav
    file_002.wav
  Actitis macularius/
    file_003.wav
```

Supported audio extensions:

```text
.wav, .mp3, .flac, .ogg, .m4a
```

The first folder level is treated as the logical group, usually the species.

### Optional CSV

You can include a detection table:

```text
DETECTIONS.csv
```

It will be uploaded to:

```text
index/detections.csv
```

---

## Installation

From the script folder:

```powershell
cd C:\Users\jonat\Documents\Python\HF_Dataset_Uploader\hf_upload_script
python -m pip install -r requirements.txt
```

Recommended dependency versions are declared in `requirements.txt`, including:

```text
huggingface_hub>=0.32.0
hf_xet>=1.0.0
```

---

## Authentication

The script can receive your Hugging Face token in three ways.

### Option A: Environment Variable

PowerShell:

```powershell
$env:HF_TOKEN="hf_your_token_here"
```

Linux/macOS:

```bash
export HF_TOKEN="hf_your_token_here"
```

### Option B: Command Option

```powershell
python app.py upload --token hf_your_token_here ...
```

### Option C: Stored Login

```powershell
python app.py login
```

Token priority is:

```text
--token > HF_TOKEN > stored login
```

---

## Quick Start

PowerShell example:

```powershell
python app.py upload `
  --repo-id jrrribeiro/upload_test1 `
  --segments C:\Users\jonat\Downloads\Segments `
  --csv C:\Users\jonat\Downloads\DETECTIONS.csv `
  --workers 8 `
  --private
```

Linux/macOS example:

```bash
python app.py upload \
  --repo-id owner/dataset-name \
  --segments /path/to/Segments \
  --csv /path/to/DETECTIONS.csv \
  --workers 8
```

---

## Always Start With Dry Run

Use `--dry-run` before a real upload:

```powershell
python app.py upload `
  --repo-id jrrribeiro/upload_test1 `
  --segments C:\Users\jonat\Downloads\Segments `
  --csv C:\Users\jonat\Downloads\DETECTIONS.csv `
  --max-files-per-folder 9000 `
  --dry-run
```

Dry run will:

| Action | Network required? |
| --- | --- |
| Scan local audio files | No |
| Build local stored paths | No |
| Show first planned files | No |
| Upload files | No |

---

## Recommended Large Upload Mode

The default mode is:

```text
--upload-mode large-folder
```

This mode uses:

```python
HfApi.upload_large_folder(...)
```

It is the recommended mode for large folders because it is resumable, supports
parallel work, and keeps local upload metadata.

You usually do not need to pass `--upload-mode` explicitly:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments
```

`direct` is accepted as a backwards-compatible alias for `large-folder`.

---

## Repository Creation

By default, the upload command creates the Hugging Face dataset repository if it
does not exist:

```text
--create-repo
```

Choose visibility when creating the dataset:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --private
```

or:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --public
```

If you want the command to fail when the repository does not already exist:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --no-create-repo
```

When the script creates a new repository during the current run, it knows the
dataset is empty. If the remote index listing times out immediately afterward,
it can safely continue with an empty remote index.

---

## Folder Sharding

Hugging Face repositories and later validation tools behave better when a single
folder does not contain too many files.

By default, the script uses:

```text
--max-files-per-folder 9000
```

Example output structure:

```text
audio/
  Accipiter_striatus/
    shard-000000/
      Catim_...__2d22cade4048.wav
      Catim_...__f2f7f9d385d5.wav
    shard-000001/
      Catim_...__d386a0a6a329.wav
index/
  files.parquet
  files.jsonl
  manifest.json
  detections.csv
```

The shard folders are only a storage layout. The logical meaning is preserved in:

```text
index/files.parquet
```

Important columns:

| Column | Meaning |
| --- | --- |
| `original_relative_path` | Original path under your local `Segments` folder. |
| `logical_group` | Original top-level folder, usually species. |
| `stored_path` | Final path inside the Hugging Face dataset. |
| `size` | File size in bytes. |
| `status` | `upload` or `skip` for the current plan. |

---

## Staging Folder

Because `upload_large_folder` uploads a folder exactly as it exists locally, the
script first builds a staging folder.

Default location:

```text
%TEMP%\hf-dataset-uploader\<owner__dataset>\staging
```

You can choose a custom location:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --staging-dir D:\hf_staging\dataset-name
```

### Hardlink vs Copy

Default:

```text
--staging-mode hardlink
```

Hardlinks avoid duplicating audio bytes on disk when possible. If hardlinks are
not available, the script falls back to copy.

Force copy:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --staging-mode copy
```

---

## Delta Uploads

On each run, the script:

1. scans local files once;
2. lists remote dataset files once;
3. compares planned `stored_path` values;
4. uploads only missing files.

Example after everything is already uploaded:

```text
Found 90 audio files (34083968 bytes) under C:\Users\jonat\Downloads\Segments
Plan 0/90 files to upload, 90 already present, 0 bytes pending
Nothing to upload.
Scanning local audio files      90/90
Loading remote repository index 98/98
```

Example after a partial upload:

```text
Plan 72/90 files to upload, 18 already present, 27267176 bytes pending
```

---

## Progress And Logs

The script avoids one log line per file.

You should normally see compact progress:

```text
Scanning local audio files      90/90
Loading remote repository index 98/98
Building upload staging folder  72/72

Starting Hugging Face large-folder upload...
```

During the Hugging Face upload, the Hub client prints periodic aggregate reports:

```text
Files: hashed 96/96 | pre-uploaded 76/91 | committed 0/96
Workers: hashing: 0 | get upload mode: 0 | pre-uploading: 4
```

Use verbose mode only for debugging:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --verbose
```

---

## Common Commands

### Show Help

```powershell
python app.py --help
python app.py upload --help
```

### Check What Would Be Uploaded

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --dry-run
```

### Upload With CSV

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --csv C:\path\to\DETECTIONS.csv `
  --workers 8
```

### Use Smaller Shards For Testing

This is useful to confirm folder splitting:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --max-files-per-folder 10 `
  --dry-run
```

### Use A Faster Local Disk For Staging

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --staging-dir D:\hf_staging\dataset-name `
  --workers 16
```

---

## Command Reference

| Option | Default | Description |
| --- | --- | --- |
| `--repo-id` | Required | Hugging Face dataset repo in `owner/name` format. |
| `--segments` | Required | Local folder containing audio segments. |
| `--csv` | None | Optional detection CSV uploaded to `index/detections.csv`. |
| `--token` | None | Hugging Face token. Usually prefer `HF_TOKEN`. |
| `--remote-base` | `audio` | Base folder inside the dataset for staged audio. |
| `--workers` | Hub default | Parallel workers for `upload_large_folder`. |
| `--create-repo / --no-create-repo` | `--create-repo` | Create the dataset repo if needed. |
| `--private / --public` | `--private` | Visibility when creating the dataset repo. |
| `--upload-mode` | `large-folder` | Main mode. `legacy` keeps the old flow. |
| `--staging-dir` | Temp folder | Local staging location. |
| `--max-files-per-folder` | `9000` | Max files per staged shard folder. |
| `--staging-mode` | `hardlink` | Use `hardlink` or `copy`. |
| `--first-upload` | Off | Treat the dataset as empty if remote listing times out. |
| `--dry-run` | Off | Show plan without upload. |
| `--verbose` | Off | Show detailed Hugging Face logs and file progress. |

---

## Repository Output

After upload, the dataset should contain something like:

```text
audio/
  <logical_group>/
    shard-000000/
    shard-000001/
index/
  detections.csv
  files.parquet
  files.jsonl
  manifest.json
  staging_summary.json
  upload_plan.json
```

For validation systems, prefer reading:

```text
index/files.parquet
```

instead of inferring everything from physical folders.

---

## Troubleshooting

### `upload_large_folder` Is Missing

Upgrade dependencies:

```powershell
python -m pip install -U huggingface_hub hf_xet
```

### Upload Is Slow

Try:

```powershell
$env:HF_XET_HIGH_PERFORMANCE="1"
python app.py upload --repo-id owner/dataset-name --segments C:\path\to\Segments --workers 16
```

Also use a fast local SSD for `--staging-dir`.

### Too Many Files In One Folder

Lower the shard size:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --max-files-per-folder 5000
```

### Hardlinks Are Not Working

Use copy mode:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --staging-mode copy
```

### Network Timeout

Re-run the same command. The large-folder mode keeps upload metadata and should
resume work instead of starting from zero.

If the timeout happens while loading the remote repository index and the script
created the repository in this same run, it will continue automatically.

If the repository already existed but you know this is the first upload and it is
empty, use:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --first-upload
```

Do not use `--first-upload` for datasets that may already contain files you want
to skip, because the script will assume nothing is present remotely if listing
times out.

### I Want The Old Behavior

Use:

```powershell
python app.py upload `
  --repo-id owner/dataset-name `
  --segments C:\path\to\Segments `
  --upload-mode legacy
```

Use this mainly for debugging or compatibility. For large datasets, prefer the
default `large-folder` mode.

---

## Recommended Test Flow

1. Run dry-run:

```powershell
python app.py upload `
  --repo-id owner/test-dataset `
  --segments C:\Users\jonat\Downloads\Segments `
  --csv C:\Users\jonat\Downloads\DETECTIONS.csv `
  --dry-run
```

2. Run real upload:

```powershell
python app.py upload `
  --repo-id owner/test-dataset `
  --segments C:\Users\jonat\Downloads\Segments `
  --csv C:\Users\jonat\Downloads\DETECTIONS.csv `
  --workers 8
```

3. Run the same command again.

Expected result:

```text
Plan 0/<total> files to upload, <total> already present, 0 bytes pending
Nothing to upload.
```

4. Add new files locally and run again.

Expected result:

```text
Plan <new>/<total> files to upload, <existing> already present
```
