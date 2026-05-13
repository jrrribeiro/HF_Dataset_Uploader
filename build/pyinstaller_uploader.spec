# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

import safehttpx
import groovy


block_cipher = None
project_root = Path.cwd()
safehttpx_package = Path(safehttpx.__file__).parent
groovy_package = Path(groovy.__file__).parent

gradio_datas, gradio_binaries, gradio_hiddenimports = collect_all("gradio")
gradio_client_datas, gradio_client_binaries, gradio_client_hiddenimports = collect_all("gradio_client")
huggingface_datas, huggingface_binaries, huggingface_hiddenimports = collect_all("huggingface_hub")
safehttpx_datas, safehttpx_binaries, safehttpx_hiddenimports = collect_all("safehttpx")


a = Analysis(
    [str(project_root / "app.py")],
    pathex=[str(project_root)],
    datas=gradio_datas + gradio_client_datas + huggingface_datas + safehttpx_datas + [(str(project_root / "src"), "src"), (str(safehttpx_package), "safehttpx"), (str(groovy_package), "groovy")],
    binaries=gradio_binaries + gradio_client_binaries + huggingface_binaries + safehttpx_binaries,
    hiddenimports=[
        "src",
        "src.uploader",
        "click",
        "gradio",
        "gradio.events",
        "gradio.blocks",
        "gradio.interface",
        "huggingface_hub",
        "huggingface_hub.hf_api",
        *gradio_hiddenimports,
        *gradio_client_hiddenimports,
        *huggingface_hiddenimports,
        *safehttpx_hiddenimports,
        "keyring",
        "pydantic",
        "pandas",
        "pyarrow",
        "fastapi",
        "starlette",
        "uvicorn",
        "httpx",
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
