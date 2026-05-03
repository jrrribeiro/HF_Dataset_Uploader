Param(
    [string]$RepoId = "owner/dataset",
    [string]$Segments = "C:\data\segments",
    [string]$Token = $env:HF_TOKEN,
    [string]$SessionDir = $env:BIRDNET_UPLOADER_SESSION_DIR
)

if (-not $Token) {
    Write-Error "HF_TOKEN environment variable must be set or pass --Token"
    exit 2
}

Write-Host "Running smoke test upload against $RepoId using segments at $Segments"
if ($SessionDir) {
    Write-Host "Session checkpoints will persist under $SessionDir"
}

# Dry run first
& .\birdnet-uploader.exe upload --repo-id $RepoId --segments $Segments --token $Token --dry-run

if ($LASTEXITCODE -ne 0) {
    Write-Error "Dry run failed"
    exit $LASTEXITCODE
}

Write-Host "Dry run OK. To perform a real small upload, run without --dry-run and mount a small folder."
