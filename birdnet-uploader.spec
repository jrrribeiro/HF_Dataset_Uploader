# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files
from pathlib import Path

datas = []
datas += collect_data_files('gradio')
datas += collect_data_files('gradio_client')
datas += collect_data_files('safehttpx')
datas += collect_data_files('groovy')

gradio_root = Path(r'C:\Users\jonat\Documents\Python\BirdNET-Uploader-App\.venv\Lib\site-packages\gradio')
for py_file in gradio_root.rglob('*.py'):
    relative_dir = py_file.parent.relative_to(gradio_root)
    datas.append((str(py_file), str(Path('gradio') / relative_dir)))

a = Analysis(
    ['C:\\Users\\jonat\\Documents\\Python\\BirdNET-Uploader-App\\app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['C:\\Users\\jonat\\Documents\\Python\\BirdNET-Uploader-App\\build\\runtime_hook_gradio_patch.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='birdnet-uploader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
