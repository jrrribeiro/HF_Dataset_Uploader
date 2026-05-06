# BirdNET Uploader Usage Guide

This guide covers how to download, install, and use the BirdNET Uploader CLI for uploading audio datasets to Hugging Face.

## Installation

### Option 1: Windows Standalone (Recommended)

1. Download the latest release from [Releases](https://huggingface.co/spaces/jrrribeiro/BirdNET-Uploader-App/discussions)
2. Extract the ZIP file to a folder
3. No Python installation required!
4. Run: `birdnet-uploader.exe --help`

### Option 2: Python + Pip

```bash
pip install birdnet-uploader
birdnet-uploader --help
```

### Option 3: Docker

```bash
docker pull birdnet-uploader:latest
docker run --rm \
  -e HF_TOKEN="hf_your_token" \
  -v C:\segments:C:\data\segments \
  birdnet-uploader:latest \
  upload --repo-id user/dataset --segments C:\data\segments
```

### Option 4: Build from Source

```bash
git clone https://github.com/jrrribeiro/BirdNET-Uploader-App
cd BirdNET-Uploader-App
pip install -r requirements.txt
python -m src.uploader_cli.main --help
```

## Quick Start (5 Minutes)

### Step 1: Authenticate

Store your Hugging Face token securely:

```bash
birdnet-uploader login
# Follow the prompt to enter your token
# Token is stored securely in your OS credential manager
```

### Step 2: Create/Validate Dataset

```bash
birdnet-uploader init-repo --repo-id username/my-dataset --private
# Creates or validates the dataset exists
```

### Step 3: Prepare Audio Files

Organize your audio files in a folder:

```
C:\my-segments\
├── species-A\
│   ├── recording-001.wav
│   ├── recording-002.wav
│   └── ...
├── species-B\
│   ├── recording-003.wav
│   └── ...
└── detections.csv  (optional)
```

### Step 4: Dry Run (Recommended)

Preview what will be uploaded without actually uploading:

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\my-segments \
  --dry-run
```

### Step 5: Upload

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\my-segments \
  --csv detections.csv
```

Done! Audio files are now in `audio/` and CSV is in `index/detections.csv`.

## Common Workflows

### Upload with Progress Tracking

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\my-segments \
  --workers 4
```

The `--workers` option enables parallel uploads (faster on multi-core systems).

### Resume Interrupted Upload

```bash
# Check existing sessions
ls ~/.birdnet-uploader/sessions/

# Resume a specific session
birdnet-uploader resume upload-20260429T120000Z

# Or start fresh
birdnet-uploader upload --repo-id username/my-dataset --segments C:\my-segments
```

### Upload with Custom Token (CI/CD)

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\my-segments \
  --token hf_your_token
```

### Batch Upload Multiple Folders

```powershell
$folders = @("C:\data\2024", "C:\data\2025")
foreach ($folder in $folders) {
  birdnet-uploader upload `
    --repo-id username/my-dataset `
    --segments $folder
}
```

### Upload Only CSV (Index Only)

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\dummy-empty \
  --csv detections.csv \
  --dry-run
```

## Token Management

### Method 1: Stored Token (Recommended for Local Use)

```bash
# Store token securely (OS Credential Manager)
birdnet-uploader login

# Use stored token automatically
birdnet-uploader upload --repo-id username/my-dataset --segments C:\segments
```

### Method 2: Environment Variable (Docker/CI)

```bash
# Linux/macOS
export HF_TOKEN="hf_..."
birdnet-uploader upload ...

# Windows PowerShell
$env:HF_TOKEN = "hf_..."
birdnet-uploader.exe upload ...

# Windows CMD
set HF_TOKEN=hf_...
birdnet-uploader.exe upload ...
```

### Method 3: CLI Option (One-Off)

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\segments \
  --token hf_...
```

## Advanced Usage

### Parallel Uploads

Speed up uploads on multi-core systems:

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\segments \
  --workers 8
```

Recommended values:
- 4-8 workers for residential/office internet
- 16-32 workers for datacenter/gigabit internet

### Custom Dataset Path

Upload to a subdirectory in the dataset:

```bash
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\segments \
  --remote-base audio/my-collection
```

Files uploaded to: `audio/my-collection/...` instead of `audio/...`

### Session Management

```bash
# List all sessions
ls ~/.birdnet-uploader/sessions/

# View session checkpoint
birdnet-uploader resume upload-20260429T120000Z

# Remove old session (careful!)
rm -r ~/.birdnet-uploader/sessions/upload-20260101T000000Z
```

### Clear Deduplication Cache

If you need to re-upload files that were marked as already uploaded:

```bash
# Remove cache (forces re-upload check)
rm -r ~/.birdnet-uploader/cache/

# Then retry upload
birdnet-uploader upload --repo-id username/my-dataset --segments C:\segments
```

## Troubleshooting

### "No stored token found"

**Problem**: You haven't logged in yet.

**Solution**:
```bash
birdnet-uploader login
# Enter your Hugging Face token when prompted
```

### "Token validation failed"

**Problem**: Token is invalid or expired.

**Solution**:
1. Go to https://huggingface.co/settings/tokens
2. Create a new token
3. Run `birdnet-uploader login` and enter the new token
4. Or use `--token hf_new_token` directly

### "Dataset not found"

**Problem**: Dataset doesn't exist or you don't have access.

**Solution**:
```bash
# Create the dataset
birdnet-uploader init-repo --repo-id username/my-dataset

# Or verify access
curl -H "Authorization: Bearer hf_..." \
  https://huggingface.co/api/datasets/username/my-dataset
```

### "Upload stuck or slow"

**Problem**: Network issues or single-threaded upload.

**Solution**:
```bash
# Use parallel workers
birdnet-uploader upload \
  --repo-id username/my-dataset \
  --segments C:\segments \
  --workers 4
```

### "DLL not found" (Windows executable)

**Problem**: Missing runtime dependencies in bundled version.

**Solution**:
1. Download latest release (should include all DLLs)
2. Or run from Python: `python -m src.uploader_cli.main upload ...`
3. Or report issue on GitHub

### Out of Disk Space

**Problem**: Destination dataset is full.

**Solution**:
1. Check dataset size: `huggingface_hub`
2. Delete old uploads if not needed
3. Create a new dataset: `birdnet-uploader init-repo --repo-id username/my-dataset-2`

## Dataset Structure

After upload, your Hugging Face dataset will look like:

```text
my-dataset/
├── audio/
│   ├── species-A/
│   │   ├── recording-001.wav
│   │   ├── recording-002.wav
│   │   └── ...
│   └── species-B/
│       ├── recording-003.wav
│       └── ...
├── index/
│   ├── manifest.json          # Index metadata
│   ├── detections.csv         # Your CSV (if provided)
│   └── shards/
│       ├── detections_0.parquet
│       └── detections_1.parquet
└── README.md
```

## Performance Tips

1. **Use SSD for local segments**: Faster scanning and hashing
2. **Enable parallel uploads**: `--workers 4` or higher
3. **Stable network**: Wired internet > WiFi
4. **Large batches**: Consider `--batch-size 100` for many files
5. **Monitor system resources**: CPU and memory usage during upload

## Security

- **Never hardcode tokens**: Use `birdnet-uploader login` or `HF_TOKEN` env var
- **Rotate tokens**: Generate new token every 3-6 months at https://huggingface.co/settings/tokens
- **Limit token scope**: Use fine-grained tokens with minimal permissions
- **Don't share tokens**: Each user should have their own token
- **Use dataset privacy**: Set `--private` when creating repos with sensitive data

## Getting Help

- Check [TOKEN_SECURITY.md](docs/TOKEN_SECURITY.md) for token security best practices
- Check [TOKEN_USAGE_EXAMPLES.md](docs/TOKEN_USAGE_EXAMPLES.md) for Docker/CI/CD examples
- Check [CI_CD_PIPELINE.md](docs/CI_CD_PIPELINE.md) for build and release info
- Report issues: Create a GitHub issue with error logs and reproduction steps

## FAQ

**Q: Can I cancel an upload?**
A: Yes, press Ctrl+C. The session checkpoint saves progress, so you can resume later with the same command.

**Q: How large can the audio collection be?**
A: Hugging Face datasets support large collections (100GB+). Upload speed depends on your internet.

**Q: Can multiple users upload to the same dataset?**
A: Yes, but they need write access. Use separate tokens for each user to track uploads separately.

**Q: Does it support audio formats other than WAV?**
A: Yes: WAV, MP3, FLAC, OGG, M4A. Extend `AUDIO_EXTENSIONS` in `src/uploader_cli/config.py` if needed.

**Q: Can I upload without audio files (CSV only)?**
A: Yes, but you need to provide a dummy `--segments` directory (can be empty).

**Q: How do I verify upload integrity?**
A: The uploader computes SHA-256 hashes and deduplicates against remote index. Files are verified on upload.
