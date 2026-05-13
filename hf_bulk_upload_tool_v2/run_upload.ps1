param(
    [Parameter(Mandatory = $true)]
    [string]$RepoId,
    [Parameter(Mandatory = $true)]
    [string]$Segments,
    [string]$Csv,
    [string]$HfToken,
    [switch]$Private,
    [switch]$Public,
    [switch]$DryRun,
    [int]$MaxWorkers = 4,
    [string]$AllowPatterns,
    [string]$IgnorePatterns
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path (Split-Path -Parent $scriptDir) '.venv\Scripts\python.exe'
$scriptPath = Join-Path $scriptDir 'upload_dataset_v2.py'

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at: $pythonExe"
}

$argsList = @($scriptPath, '--repo-id', $RepoId, '--segments', $Segments)

if ($Csv) { $argsList += @('--csv', $Csv) }
if ($HfToken) { $argsList += @('--hf-token', $HfToken) }
if ($Private) { $argsList += '--private' }
if ($Public) { $argsList += '--public' }
if ($DryRun) { $argsList += '--dry-run' }
if ($MaxWorkers) { $argsList += @('--max-workers', $MaxWorkers.ToString()) }
if ($AllowPatterns) { $argsList += @('--allow-patterns', $AllowPatterns) }
if ($IgnorePatterns) { $argsList += @('--ignore-patterns', $IgnorePatterns) }

& $pythonExe $argsList