param(
    [string]$HfUsername,
    [string]$HfToken,
    [string]$RepoName,
    [string]$RepoId,
    [Parameter(Mandatory = $true)]
    [string]$Segments,
    [string]$Csv,
    [switch]$Private,
    [switch]$Public,
    [switch]$DryRun,
    [switch]$Resume,
    [switch]$VerifyRemote,
    [switch]$VerifyEtag,
    [string]$ProgressLog,
    [switch]$ResumeOnly,
    [string]$CheckpointDir,
    [int]$CreateRepoAttempts = 3,
    [int]$UploadAttempts = 3,
    [double]$RetryBackoff = 5
)

$ErrorActionPreference = 'Stop'

$env:HF_HUB_ETAG_TIMEOUT = $env:HF_HUB_ETAG_TIMEOUT ?? '20'
$env:HF_HUB_DOWNLOAD_TIMEOUT = $env:HF_HUB_DOWNLOAD_TIMEOUT ?? '120'
$env:HF_XET_HIGH_PERFORMANCE = $env:HF_XET_HIGH_PERFORMANCE ?? '1'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path (Split-Path -Parent $scriptDir) '.venv\Scripts\python.exe'
$scriptPath = Join-Path $scriptDir 'upload_dataset.py'

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at: $pythonExe"
}

$argsList = @($scriptPath, '--segments', $Segments)

if ($HfUsername) { $argsList += @('--hf-username', $HfUsername) }
if ($HfToken) { $argsList += @('--hf-token', $HfToken) }
if ($RepoName) { $argsList += @('--repo-name', $RepoName) }
if ($RepoId) { $argsList += @('--repo-id', $RepoId) }
if ($Csv) { $argsList += @('--csv', $Csv) }
if ($Private) { $argsList += '--private' }
if ($Public) { $argsList += '--public' }
if ($DryRun) { $argsList += '--dry-run' }
if ($Resume) { $argsList += '--resume' }
if ($VerifyRemote) { $argsList += '--verify-remote' }
if ($CheckpointDir) { $argsList += @('--checkpoint-dir', $CheckpointDir) }
if ($VerifyEtag) { $argsList += '--verify-etag' }
if ($ProgressLog) { $argsList += @('--progress-log', $ProgressLog) }
if ($ResumeOnly) { $argsList += '--resume-only' }

$argsList += @('--create-repo-attempts', $CreateRepoAttempts.ToString())
$argsList += @('--upload-attempts', $UploadAttempts.ToString())
$argsList += @('--retry-backoff', $RetryBackoff.ToString([System.Globalization.CultureInfo]::InvariantCulture))

& $pythonExe $argsList