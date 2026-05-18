#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
Write-Output "Building HF Upload App EXE locally..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pyinstaller hf_upload_app.spec --noconfirm

# Find the first directory under dist and zip it
$dist = Join-Path $PWD 'dist'
if (Test-Path $dist) {
    $dir = Get-ChildItem -Path $dist -Directory | Select-Object -First 1
    if ($dir) {
        $zipName = "..\hf_upload_app-local-`($(Get-Date -Format yyyyMMdd-HHmmss))`-windows.zip"
        Compress-Archive -Path (Join-Path $dist $dir.Name) -DestinationPath $zipName -Force
        Write-Output "Created: $zipName"
    } else {
        Write-Error "No dist directory found after build."
        exit 2
    }
} else {
    Write-Error "dist folder does not exist. PyInstaller may have failed."
    exit 1
}
