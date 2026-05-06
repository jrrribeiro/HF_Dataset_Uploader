# Token Usage Examples

This document provides practical examples for using BirdNET Uploader with various token authentication methods.

## Quick Start (Interactive Use with Keyring)

```bash
# Step 1: Store your token securely
birdnet-uploader login
# You'll be prompted for your Hugging Face token
# It's stored securely in your OS credential manager (Credential Manager on Windows, Keychain on macOS, Secret Service on Linux)

# Step 2: Upload without needing to provide token again
birdnet-uploader upload \
  --repo-id user/my-dataset \
  --segments C:\my\audio\segments \
  --csv detections.csv
```

## Docker with Environment Variable

Store token in a `.env` file (keep it secret, don't commit to git):

**.env file:**
```
HF_TOKEN=hf_your_actual_token_here
```

**Run container:**
```bash
docker run --rm \
  --env-file .env \
  -v C:\my\segments:C:\data\segments \
  -v C:\my\sessions:C:\data\sessions \
  birdnet-uploader:latest \
  upload --repo-id user/dataset --segments C:\data\segments
```

## Docker Compose (Recommended for Production)

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  uploader:
    build:
      context: .
      dockerfile: Dockerfile.windows
    environment:
      - HF_TOKEN=${HF_TOKEN}
    volumes:
      - ./segments:C:\data\segments
      - ./sessions:C:\data\sessions
    command: >
      upload
      --repo-id ${REPO_ID}
      --segments C:\data\segments
      --workers 4
```

**Run:**
```bash
export HF_TOKEN="hf_your_actual_token"
export REPO_ID="user/dataset"
docker-compose up
```

## GitHub Actions CI/CD

**`.github/workflows/upload.yml`:**
```yaml
name: Upload to Hugging Face

on:
  push:
    branches: [main]
    paths: ['audio/**']

jobs:
  upload:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install uploader
        run: pip install -e .
      
      - name: Upload audio segments
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
        run: |
          birdnet-uploader upload `
            --repo-id ${{ vars.REPO_ID }} `
            --segments .\audio `
            --csv detections.csv `
            --workers 4
```

**Set up in GitHub:**
1. Go to **Settings > Secrets and variables > Actions**
2. Click **New repository secret**
3. Name: `HF_TOKEN`, Value: `hf_your_token`
4. Click **New repository variable**
5. Name: `REPO_ID`, Value: `username/dataset-name`

## PowerShell Script with Token Verification

```powershell
# verify_and_upload.ps1

param(
    [string]$SegmentsPath = ".\segments",
    [string]$CsvFile = ".\detections.csv",
    [string]$RepoId = "user/dataset"
)

# Verify token is set
if (-not $env:HF_TOKEN) {
    Write-Host "ERROR: HF_TOKEN environment variable not set" -ForegroundColor Red
    exit 1
}

# Verify token format
if (-not $env:HF_TOKEN.StartsWith("hf_")) {
    Write-Host "WARNING: Token doesn't start with 'hf_', verify it's correct" -ForegroundColor Yellow
}

# Verify paths exist
if (-not (Test-Path $SegmentsPath)) {
    Write-Host "ERROR: Segments directory not found: $SegmentsPath" -ForegroundColor Red
    exit 1
}

# Run upload
Write-Host "Starting upload to $RepoId..." -ForegroundColor Green
birdnet-uploader upload `
    --repo-id $RepoId `
    --segments $SegmentsPath `
    --csv $CsvFile `
    --workers 4

if ($LASTEXITCODE -eq 0) {
    Write-Host "Upload completed successfully!" -ForegroundColor Green
} else {
    Write-Host "Upload failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
```

**Run:**
```powershell
$env:HF_TOKEN = "hf_your_token"
.\verify_and_upload.ps1 -SegmentsPath "C:\audio\segments" -RepoId "user/dataset"
```

## Kubernetes Deployment

**secret.yaml:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: hf-token
type: Opaque
stringData:
  token: hf_your_actual_token_here
```

**deployment.yaml:**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: birdnet-upload-job
spec:
  template:
    spec:
      containers:
      - name: uploader
        image: birdnet-uploader:latest
        env:
        - name: HF_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-token
              key: token
        volumeMounts:
        - name: segments
          mountPath: /data/segments
          readOnly: true
        - name: sessions
          mountPath: /data/sessions
        args:
        - upload
        - --repo-id
        - user/dataset
        - --segments
        - /data/segments
        - --workers
        - "4"
      restartPolicy: Never
      volumes:
      - name: segments
        hostPath:
          path: /mnt/audio-segments
      - name: sessions
        emptyDir: {}
```

**Deploy:**
```bash
kubectl create secret generic hf-token --from-literal=token=hf_your_actual_token
kubectl apply -f deployment.yaml
kubectl logs -f job/birdnet-upload-job
```

## Windows Service (Advanced)

**install-service.ps1:**
```powershell
param(
    [string]$SegmentsPath = "C:\audio\segments",
    [string]$RepositoryId = "user/dataset"
)

$ServiceName = "BirdNETUploader"
$ExePath = "C:\Program Files\BirdNET-Uploader\birdnet-uploader.exe"
$LogPath = "C:\logs\birdnet-uploader"

# Create log directory
New-Item -ItemType Directory -Path $LogPath -Force

# Register scheduled task
$TaskAction = New-ScheduledTaskAction -Execute $ExePath -Argument "upload --repo-id $RepositoryId --segments $SegmentsPath --workers 4"
$TaskTrigger = New-ScheduledTaskTrigger -Daily -At 2AM
$TaskSettings = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable

Register-ScheduledTask -TaskName $ServiceName `
    -Action $TaskAction `
    -Trigger $TaskTrigger `
    -Settings $TaskSettings `
    -RunLevel Highest

# Store token securely in Credential Manager
$Token = Read-Host "Enter Hugging Face token" -AsSecureString
$Credential = New-Object System.Management.Automation.PSCredential("hf_token", $Token)

# The birdnet-uploader uses keyring, which respects Windows Credential Manager
```

**Run task manually:**
```powershell
Start-ScheduledTask -TaskName "BirdNETUploader"
```

## CI/CD Matrix Testing

**`.github/workflows/test-upload.yml`:**
```yaml
name: Test Upload (Multiple OS)

on: [push, pull_request]

jobs:
  test-upload:
    strategy:
      matrix:
        os: [windows-latest, ubuntu-latest, macos-latest]
        python-version: ['3.10', '3.11', '3.12']
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: pip install -e .
      
      - name: Run token security tests
        run: pytest tests/unit/test_token_security.py -v
      
      - name: Test token from environment variable
        env:
          HF_TOKEN: ${{ secrets.TEST_HF_TOKEN }}
        run: birdnet-uploader login --token $env:HF_TOKEN || true
```

## Troubleshooting Token Issues

### Issue: "No stored token found"

**Solution 1 - Use environment variable:**
```bash
set HF_TOKEN=hf_your_token
birdnet-uploader upload --repo-id user/dataset --segments ./segments
```

**Solution 2 - Store token:**
```bash
birdnet-uploader login
# Enter token when prompted
```

**Solution 3 - Pass via CLI:**
```bash
birdnet-uploader upload --repo-id user/dataset --segments ./segments --token hf_your_token
```

### Issue: Token expires

Generate a new token at https://huggingface.co/settings/tokens and:

```bash
# Update stored token
birdnet-uploader login
# Enter new token

# Or use environment variable
set HF_TOKEN=hf_new_token
birdnet-uploader upload ...
```

### Issue: Permission denied on dataset

Verify token has correct permissions:

```bash
# Test token
curl -H "Authorization: Bearer hf_your_token" https://huggingface.co/api/user

# Check token permissions at https://huggingface.co/settings/tokens
# Ensure it has: repo.content.write
# Ensure it's limited to your target dataset if possible
```

## Security Checklist

- [ ] Never commit `HF_TOKEN` values to version control
- [ ] Use GitHub Secrets for CI/CD, not plain environment variables
- [ ] Use Docker secrets or volume mounts for orchestrated environments
- [ ] Rotate tokens every 3-6 months
- [ ] Use read-only tokens where possible
- [ ] Limit token scope to specific datasets
- [ ] Use different tokens for different services/projects
- [ ] Monitor token usage in Hugging Face settings
- [ ] Immediately regenerate leaked tokens
