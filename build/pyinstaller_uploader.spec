# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


block_cipher = None
project_root = Path.cwd()


a = Analysis(
    [str(project_root / "app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "click",
        "gradio",
        "huggingface_hub",
        "keyring",
        "pydantic",
        "pandas",
        "pyarrow",
        "src.uploader",
        "src.uploader.auth_service",
        "src.uploader.batch_uploader",
        "src.uploader.config",
        "src.uploader.deduplicator",
        "src.uploader.error_handler",
        "src.uploader.exceptions",
        "src.uploader.hash_utils",
        "src.uploader.main",
        "src.uploader.manifest",
        "src.uploader.repo_service",
        "src.uploader.scanner",
        "src.uploader.session_manager",
        "src.uploader.web_ui",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="birdnet-uploader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="birdnet-uploader",
)
