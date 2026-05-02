param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$ReleaseDir = ".\build\release"
)

$ErrorActionPreference = "Stop"

function Get-PlatformLabel {
    if ($IsWindows) { return "windows" }
    if ($IsLinux) { return "linux" }
    return "unknown"
}

$Bundle = Get-ChildItem -Path $ReleaseDir -Filter "birdnet-uploader-$Version-*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Bundle) {
    throw "Bundle for version $Version not found under $ReleaseDir"
}

$BundlePath = $Bundle.FullName
$BundleName = $Bundle.Name
$ChecksumPath = "$BundlePath.sha256"

if (-not (Test-Path $BundlePath)) {
    throw "Bundle not found: $BundlePath"
}

if (-not (Test-Path $ChecksumPath)) {
    throw "Checksum file not found: $ChecksumPath"
}

Write-Host "[1/5] Validating checksum file"
$ChecksumLine = (Get-Content $ChecksumPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($ChecksumLine)) {
    throw "Checksum file is empty: $ChecksumPath"
}

$ExpectedHash = ($ChecksumLine -split "\s+")[0].ToLower()
$ComputedHash = (Get-FileHash -Path $BundlePath -Algorithm SHA256).Hash.ToLower()

if ($ExpectedHash -ne $ComputedHash) {
    throw "Checksum mismatch for $BundleName"
}

Write-Host "[2/5] Extracting bundle into an isolated temp folder"
$TempRoot = Join-Path $env:TEMP ("birdnet-uploader-smoke-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot | Out-Null
Expand-Archive -Path $BundlePath -DestinationPath $TempRoot -Force

$Exe = Get-ChildItem -Path $TempRoot -Filter "birdnet-uploader.exe" -Recurse | Select-Object -First 1
if (-not $Exe) {
    throw "Executable not found in extracted bundle"
}
$ExePath = $Exe.FullName
$ExeDir = $Exe.Directory.FullName

if (-not (Test-Path (Join-Path $ExeDir "_internal"))) {
    throw "Missing _internal runtime folder next to executable: $ExeDir"
}

Write-Host "[3/5] Smoke test: executable help"
Push-Location $ExeDir
& $ExePath --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    throw "Executable help command failed"
}

Write-Host "[4/5] Smoke test: command help"
& $ExePath scan --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    throw "Scan help command failed"
}
Pop-Location

Write-Host "[5/5] Success"
Write-Host "Bundle validated: $BundlePath"
Write-Host "Extracted test folder: $TempRoot"
