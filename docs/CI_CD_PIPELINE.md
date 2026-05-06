# BirdNET Uploader CI/CD Pipeline

This document explains the CI/CD workflows and build process for BirdNET Uploader.

## Workflows Overview

### 1. `build-and-test.yml` - Main CI/CD Pipeline

Runs automatically on every push to `main` and on pull requests.

**Jobs:**

1. **test-multi-os**: Run tests on Linux, Windows, and macOS with Python 3.10, 3.11, 3.12
   - Runs both unit and integration tests
   - Ensures code works across platforms

2. **build-windows-exe**: Build Windows executable
   - Builds PyInstaller bundle on Windows
   - Verifies executable with `--help`
   - Runs smoke test (dry-run upload)
   - Uploads artifact (7-day retention)

3. **token-security-check**: Verify token security
   - Runs all token security tests
   - Checks for hardcoded tokens in source
   - Ensures `.env` files aren't tracked

4. **docs-check**: Verify documentation exists
   - Checks TOKEN_SECURITY.md and TOKEN_USAGE_EXAMPLES.md exist

**Triggers:**
- Push to `main` branch
- Pull requests to `main`

**Artifacts:**
- Windows executable available for 7 days under "Actions" > run details

### 2. `release-uploader.yml` - Manual Release

Triggered manually via GitHub Actions UI to publish official releases.

**Inputs:**
- `version` (required): Release version (e.g., 0.1.0)
- `hf_repo_id` (optional): Hugging Face repo to publish to
- `hf_repo_type` (optional): "dataset" or "model" (default: dataset)
- `publish_to_hf` (optional): Upload artifacts to Hugging Face

**Jobs:**
1. Build release bundle
2. Upload GitHub artifact
3. Optional: Publish to Hugging Face if `publish_to_hf=true`

**To create a release:**

1. Go to **Actions** > **Release BirdNET Uploader**
2. Click **Run workflow**
3. Fill in inputs:
   - Version: `0.2.0`
   - HF Repo ID: `username/birdnet-uploader-releases` (if publishing)
   - Check "Upload release bundle to Hugging Face" (if publishing)
4. Click **Run workflow**

### 3. `ci.yml` - Legacy Test Workflow (Ubuntu only)

Basic test workflow that runs on Ubuntu. Can be deprecated in favor of `build-and-test.yml`.

## Local Development

### Running Tests

```bash
# Run all tests
pytest -q

# Run specific test file
pytest tests/unit/test_token_security.py -v

# Run with coverage
pytest --cov=src tests/
```

### Building Release Locally

```bash
# Install build dependencies
pip install pyinstaller

# Method 1: Basic build
python build/release_uploader.py --version 0.2.0

# Method 2: Build + smoke test
python build/build_and_publish.py --version 0.2.0 --smoke-test

# Method 3: Build + smoke test + publish to HF (requires HF_TOKEN)
export HF_TOKEN="hf_your_token"
python build/build_and_publish.py \
  --version 0.2.0 \
  --smoke-test \
  --publish \
  --hf-repo user/birdnet-uploader-releases
```

### Build Options

```bash
# Clean previous builds before building
python build/build_and_publish.py --version 0.2.0 --clean

# Run smoke test only
python build/build_and_publish.py --version 0.2.0 --smoke-test

# Publish to Hugging Face
python build/build_and_publish.py \
  --version 0.2.0 \
  --hf-repo user/releases \
  --publish
```

## PyInstaller Configuration

The build process uses `build/pyinstaller_uploader.spec` to configure the executable:

- **One-folder build**: All dependencies in `dist/birdnet-uploader/` folder
- **Windows only**: Configured for Windows (can be extended to Unix)
- **Icon**: Specify with `icon=` parameter if needed
- **Version info**: Populated from version argument

To customize build:

1. Edit `build/pyinstaller_uploader.spec`
2. Run `python -m PyInstaller --noconfirm build/pyinstaller_uploader.spec`

## Smoke Test Details

The smoke test (`scripts/smoke_test_upload.ps1` and integrated into workflows):

1. Creates dummy audio segments directory
2. Calls `birdnet-uploader upload` with `--dry-run`
3. Verifies no actual upload occurs
4. Tests token handling and argument parsing

**Why smoke test?** Ensures the packaged executable:
- Runs without DLL/dependency errors
- Accepts correct CLI arguments
- Handles token parameters securely
- Doesn't perform actual uploads

## Token Security in CI

### Environment Variable (`HF_TOKEN`)

```yaml
# In GitHub Actions
env:
  HF_TOKEN: ${{ secrets.HF_TOKEN }}

# In docker-compose
environment:
  - HF_TOKEN=${HF_TOKEN}
```

### GitHub Secrets

Tokens are stored securely in GitHub:
1. Settings > Secrets and variables > Actions
2. New secret: `HF_TOKEN` = `hf_...`
3. Used via `${{ secrets.HF_TOKEN }}` in workflows

### No Hardcoded Tokens

The CI pipeline includes a security check that:
- Scans source for hardcoded tokens
- Ensures `.env` files aren't tracked
- Prevents accidental token exposure

## Release Artifacts Structure

```
releases/
├── v0.2.0/
│   ├── birdnet-uploader-0.2.0-windows.zip      (19 MB)
│   └── birdnet-uploader-0.2.0-windows.zip.sha256 (128 bytes)
└── v0.1.0/
    ├── birdnet-uploader-0.1.0-windows.zip
    └── birdnet-uploader-0.1.0-windows.zip.sha256
```

**To verify integrity:**
```bash
# Linux/macOS
sha256sum -c birdnet-uploader-0.2.0-windows.zip.sha256

# Windows PowerShell
(Get-FileHash -Algorithm SHA256 .\birdnet-uploader-0.2.0-windows.zip).Hash -eq (Get-Content .\birdnet-uploader-0.2.0-windows.zip.sha256).Split()[0]
```

## Troubleshooting

### Build fails on Windows

```bash
# Ensure PyInstaller is installed
pip install pyinstaller

# Clean previous builds
python build/build_and_publish.py --version 0.2.0 --clean

# Retry build
python build/build_and_publish.py --version 0.2.0
```

### Smoke test fails with "DLL not found"

```bash
# Likely missing runtime dependency
# Reinstall dependencies and rebuild
pip install -r requirements.txt --force-reinstall
python build/build_and_publish.py --version 0.2.0 --clean
```

### Token security check fails

```bash
# Found hardcoded token?
grep -r "hf_[A-Za-z0-9]\{20,\}" src/ --include="*.py"

# Remove hardcoded token and regenerate
# Also rotate your token at https://huggingface.co/settings/tokens
```

### Publish to HF fails

```bash
# Verify token
export HF_TOKEN="hf_your_token"

# Test token access
curl -H "Authorization: Bearer $HF_TOKEN" https://huggingface.co/api/user

# Check repo exists and you have write access
# Retry publish
python build/build_and_publish.py \
  --version 0.2.0 \
  --publish \
  --hf-repo user/repo
```

## GitHub Actions Secrets Setup

For the release workflow to publish to Hugging Face:

1. **Create HF token** at https://huggingface.co/settings/tokens
   - Type: "Fine-grained"
   - Permissions: `repo.content.write`
   - Limit to your release repository

2. **Add to GitHub Secrets**:
   - Go to **Settings > Secrets and variables > Actions**
   - New secret: `HF_TOKEN` = `hf_...`

3. **Use in workflow**:
   ```yaml
   env:
     HF_TOKEN: ${{ secrets.HF_TOKEN }}
   ```

## Next Steps

- [ ] Set up GitHub token in repository secrets
- [ ] Create first official release (v0.2.0)
- [ ] Monitor build logs for any issues
- [ ] Update release notes with token security improvements
- [ ] Announce release with TOKEN_SECURITY.md and TOKEN_USAGE_EXAMPLES.md documentation

## Files Reference

| File | Purpose |
|------|---------|
| `.github/workflows/build-and-test.yml` | Main CI/CD matrix testing |
| `.github/workflows/release-uploader.yml` | Manual release workflow |
| `.github/workflows/ci.yml` | Legacy basic tests (can deprecate) |
| `build/release_uploader.py` | PyInstaller bundle generation |
| `build/build_and_publish.py` | Local build + test + publish orchestration |
| `build/publish_release_to_hf.py` | Publish artifacts to Hugging Face |
| `build/pyinstaller_uploader.spec` | PyInstaller configuration |
| `scripts/smoke_test_upload.ps1` | Manual smoke test script |
