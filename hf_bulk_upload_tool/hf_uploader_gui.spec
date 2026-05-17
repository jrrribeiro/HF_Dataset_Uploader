# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path

block_cipher = None
script_dir = Path(os.path.dirname(os.path.abspath(SPEC)))
main_gui_path = script_dir / 'main_gui.py'

a = Analysis(
    [str(main_gui_path)],
    pathex=[str(script_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[
        'upload_logic',
        'customtkinter',
        'huggingface_hub',
        'requests',
        'tqdm',
        'sharding_utils',
        'progress_bar_utils',
        'resilience_utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='HF_Dataset_Uploader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
