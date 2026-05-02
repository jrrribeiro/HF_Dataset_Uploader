# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


block_cipher = None
project_root = Path.cwd()


a = Analysis(
    [str(project_root / "src" / "uploader_cli" / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "click",
        "huggingface_hub",
        "keyring",
        "rich",
        "textual",
        "pydantic",
        "pandas",
        "pyarrow",
        "src.uploader_cli",
        "src.uploader_cli.auth_service",
        "src.uploader_cli.batch_uploader",
        "src.uploader_cli.config",
        "src.uploader_cli.deduplicator",
        "src.uploader_cli.error_handler",
        "src.uploader_cli.exceptions",
        "src.uploader_cli.hash_utils",
        "src.uploader_cli.repo_service",
        "src.uploader_cli.scanner",
        "src.uploader_cli.session_manager",
        "src.uploader_cli.tui",
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
