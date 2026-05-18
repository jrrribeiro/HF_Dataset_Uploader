#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
Write-Output "Building HF Upload App EXE locally..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pyinstaller hf_upload_app.spec --noconfirm

# Package the executable or, if PyInstaller produced a folder build, zip that folder.
$dist = Join-Path $PWD 'dist'
if (Test-Path $dist) {
    $exe = Join-Path $dist 'HF_Dataset_Uploader_Native.exe'
    if (Test-Path $exe) {
        $zipName = "..\hf_upload_app-local-`($(Get-Date -Format yyyyMMdd-HHmmss))`-windows.zip"
        Compress-Archive -Path $exe -DestinationPath $zipName -Force
        Write-Output "Created: $zipName"
    } else {
        $dir = Get-ChildItem -Path $dist -Directory | Select-Object -First 1
        if ($dir) {
            $zipName = "..\hf_upload_app-local-`($(Get-Date -Format yyyyMMdd-HHmmss))`-windows.zip"
            Compress-Archive -Path (Join-Path $dist $dir.Name) -DestinationPath $zipName -Force
            Write-Output "Created: $zipName"
        } else {
            Write-Error "No executable or dist directory found after build."
            exit 2
        }
    }
} else {
    Write-Error "dist folder does not exist. PyInstaller may have failed."
    exit 1
}
