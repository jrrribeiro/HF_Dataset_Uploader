#!/usr/bin/env python3
"""
Test imports one by one to find the problematic module
"""

import sys
import traceback

print("=" * 60)
print("BirdNET Uploader - Import Test")
print("=" * 60)
print()

modules_to_test = [
    ("gradio", "gradio as gr"),
    ("huggingface_hub", "HfApi from huggingface_hub"),
    ("click", "click"),
    ("keyring", "keyring"),
    ("pathlib", "Path from pathlib"),
    ("tempfile", "tempfile"),
    ("shutil", "shutil"),
    ("tarfile", "tarfile"),
    ("zipfile", "zipfile"),
    ("pandas", "pandas"),
    ("pyarrow", "pyarrow"),
]

print("Testing standard library and external imports...\n")

all_ok = True
for module, desc in modules_to_test:
    try:
        __import__(module)
        print(f"✅ {module:20s} - {desc}")
    except ImportError as e:
        print(f"❌ {module:20s} - {desc}")
        print(f"   Error: {e}")
        all_ok = False
    except Exception as e:
        print(f"⚠️  {module:20s} - {desc}")
        print(f"   Error: {e}")
        all_ok = False

print()
print("=" * 60)
print("Testing src modules...\n")

src_modules = [
    "src.uploader.config",
    "src.uploader.auth_service",
    "src.uploader.scanner",
    "src.uploader.deduplicator",
    "src.uploader.batch_uploader",
    "src.uploader.manifest",
    "src.uploader.session_manager",
    "src.uploader.web_ui",
    "src.uploader.main",
]

for module in src_modules:
    try:
        __import__(module)
        print(f"✅ {module}")
    except ImportError as e:
        print(f"❌ {module}")
        print(f"   Error: {e}")
        all_ok = False
    except Exception as e:
        print(f"⚠️  {module}")
        print(f"   Error: {e}")
        traceback.print_exc()
        all_ok = False

print()
print("=" * 60)
if all_ok:
    print("✅ All imports successful!")
    print()
    print("Attempting to create app...")
    try:
        from src.uploader.web_ui import create_uploader_app
        app = create_uploader_app()
        print("✅ App created successfully!")
        print()
        print("App details:")
        print(f"  Type: {type(app)}")
        print(f"  App: {app}")
    except Exception as e:
        print(f"❌ Failed to create app: {e}")
        traceback.print_exc()
else:
    print("❌ Some imports failed!")
    sys.exit(1)

print()
print("=" * 60)
