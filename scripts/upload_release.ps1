# Upload Windows Portable to Hugging Face
# Usage: .\scripts\upload_release.ps1 -Version 1.0.0 -RepoId "your-org/birdnet-uploader-releases"

param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$RepoId,

    [string]$Token = $env:HF_TOKEN
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleasesDir = Join-Path $ProjectRoot "build" "release"
$ZipFile = Join-Path $ReleasesDir "birdnet-uploader-$Version-windows.zip"
$Sha256File = "$ZipFile.sha256"

Write-Host "🚀 BirdNET Uploader Release Upload" -ForegroundColor Cyan
Write-Host "=====================================`n"

# Validation
if (-not (Test-Path $ZipFile)) {
    throw "Release file not found: $ZipFile"
}

if (-not $Token) {
    Write-Host "⚠️  HF_TOKEN environment variable not set." -ForegroundColor Yellow
    Write-Host "Set it with: `$env:HF_TOKEN = 'hf_xxxxxxxxxxxx'" -ForegroundColor Yellow
    Write-Host "Get your token at: https://huggingface.co/settings/tokens`n" -ForegroundColor Yellow
    exit 1
}

# File info
$ZipSize = (Get-Item $ZipFile).Length / 1GB
Write-Host "📦 Release Information"
Write-Host "  Version: $Version"
Write-Host "  File: $(Split-Path -Leaf $ZipFile)"
Write-Host "  Size: $([math]::Round($ZipSize, 2)) GB"
Write-Host "  Repo: $RepoId`n"

# Install huggingface_hub if needed
Write-Host "📥 Checking dependencies..."
try {
    python -m pip show huggingface_hub > $null 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Not installed"
    }
} catch {
    Write-Host "Installing huggingface_hub..." -ForegroundColor Cyan
    python -m pip install -q huggingface_hub
}

# Upload
Write-Host "🔐 Authenticating with Hugging Face..." -ForegroundColor Cyan
$PythonScript = @"
import os
import sys
from huggingface_hub import HfApi
from pathlib import Path
import hashlib

def upload_release():
    token = r'$Token'
    repo_id = r'$RepoId'
    version = r'$Version'
    zip_path = Path(r'$ZipFile')
    
    # Verify file exists
    if not zip_path.exists():
        print(f"❌ File not found: {zip_path}")
        sys.exit(1)
    
    # Initialize API
    api = HfApi(token=token)
    
    # Compute checksum
    print("🔢 Computing SHA256 checksum...")
    sha256_hash = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    checksum = sha256_hash.hexdigest()
    print(f"   SHA256: {checksum}")
    
    # Remote paths
    remote_base = f"releases/v{version}"
    remote_zip = f"{remote_base}/{zip_path.name}"
    remote_sha256 = f"{remote_base}/{zip_path.name}.sha256"
    
    try:
        # Upload ZIP
        print(f"\n📤 Uploading ZIP to {repo_id}/{remote_zip}...")
        api.upload_file(
            path_or_fileobj=str(zip_path),
            path_in_repo=remote_zip,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Release {version} - Windows portable executable",
        )
        print("   ✅ ZIP uploaded successfully")
        
        # Upload SHA256
        print(f"\n📤 Uploading checksum to {repo_id}/{remote_sha256}...")
        checksum_content = f"{checksum}  {zip_path.name}\n"
        api.upload_file(
            path_or_fileobj=checksum_content.encode(),
            path_in_repo=remote_sha256,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Release {version} - Checksum",
        )
        print("   ✅ Checksum uploaded successfully")
        
        # Print results
        print(f"\n✨ Release uploaded successfully!\n")
        print(f"📥 Download URLs:")
        print(f"   ZIP: https://huggingface.co/datasets/{repo_id}/resolve/main/{remote_zip}")
        print(f"   SHA256: https://huggingface.co/datasets/{repo_id}/resolve/main/{remote_sha256}")
        print(f"\n💡 Update web UI link with:")
        print(f"   https://huggingface.co/datasets/{repo_id}/resolve/main/{remote_zip}")
        
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        sys.exit(1)

upload_release()
"@

# Execute upload
python -c $PythonScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Upload failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ Done! Release is now available for download." -ForegroundColor Green
