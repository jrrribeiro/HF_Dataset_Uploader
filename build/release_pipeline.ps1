param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$RepoId = "",

    [ValidateSet("dataset", "model", "space")]
    [string]$RepoType = "dataset",

    [switch]$PublishToHf
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "C:/Users/jonat/AppData/Local/Python/pythoncore-3.14-64/python.exe"
$BuildScript = Join-Path $PSScriptRoot "release_uploader.py"
$PublishScript = Join-Path $PSScriptRoot "publish_release_to_hf.py"
$ValidateScript = Join-Path $PSScriptRoot "validate_release.ps1"

if (-not (Test-Path $Python)) {
    throw "Python executable not found at $Python"
}

Write-Host "[0/3] Ensuring build dependencies"
& $Python -m pip install pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not install PyInstaller"
}

Write-Host "[1/3] Building release bundle for version $Version"
& $Python $BuildScript --version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Release build failed"
}

Write-Host "[2/3] Running isolated smoke validation"
& $ValidateScript -Version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Release validation failed"
}

$ReleaseDir = Join-Path $PSScriptRoot "release"
$Bundle = Get-ChildItem -Path $ReleaseDir -Filter "*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$Checksum = Get-ChildItem -Path $ReleaseDir -Filter "*.sha256" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $Bundle) {
    throw "Release bundle was not created"
}

if (-not $Checksum) {
    throw "Checksum file was not created"
}

Write-Host "[2/3] Release bundle ready: $($Bundle.FullName)"
Write-Host "[2/3] Checksum ready: $($Checksum.FullName)"

if ($PublishToHf) {
    if ([string]::IsNullOrWhiteSpace($RepoId)) {
        throw "RepoId is required when -PublishToHf is set"
    }

    if ([string]::IsNullOrWhiteSpace($env:HF_TOKEN)) {
        throw "HF_TOKEN environment variable is required when publishing to Hugging Face"
    }

    Write-Host "[3/3] Publishing release artifacts to Hugging Face repo $RepoId"
    & $Python $PublishScript `
        --repo-id $RepoId `
        --repo-type $RepoType `
        --bundle $Bundle.FullName `
        --checksum $Checksum.FullName `
        --version $Version
    if ($LASTEXITCODE -ne 0) {
        throw "Publish step failed"
    }
} else {
    Write-Host "[3/3] Publish step skipped. Use -PublishToHf -RepoId <repo> to upload to Hugging Face."
}
