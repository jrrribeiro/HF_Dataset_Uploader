# Build Guide: Creating a Portable EXE for HF Bulk Uploader

## Prerequisites

1. **Python 3.10+** installed and added to PATH
2. **Virtual Environment activated** (highly recommended)

## Step 1: Install Dependencies

```powershell
# Install base requirements (if not already done)
pip install -r requirements.txt

# Install GUI-specific requirements
pip install -r hf_bulk_upload_tool\requirements_gui.txt

# Install PyInstaller for building the EXE
pip install pyinstaller==6.1.0
```

## Step 2: Test the GUI (Optional but Recommended)

Before building the EXE, test that the GUI runs correctly:

```powershell
cd hf_bulk_upload_tool
python main_gui.py
```

This will open the GUI window. Make sure all controls work and that you can see the log output.

## Step 3: Build the EXE

### Option A: Simple One-File Build (Recommended for Distribution)

```powershell
cd hf_bulk_upload_tool

pyinstaller --onefile --noconsole `
  --name "HF_Dataset_Uploader" `
  --icon=path\to\icon.ico `
  --collect-all customtkinter `
  --collect-all huggingface_hub `
  main_gui.py
```

**Parameters explained:**
- `--onefile`: Creates a single `.exe` file (larger but easier to distribute)
- `--noconsole`: Hides the black command prompt window
- `--name "HF_Dataset_Uploader"`: Sets the output EXE name
- `--icon`: (Optional) Path to a `.ico` file for the EXE icon
- `--collect-all customtkinter`: Ensures CustomTkinter is bundled
- `--collect-all huggingface_hub`: Ensures HF Hub lib is bundled
- `main_gui.py`: The entry point script

### Option B: Multi-File Build (Faster Development)

If you want faster builds during development:

```powershell
pyinstaller --onedir --noconsole `
  --name "HF_Dataset_Uploader" `
  --collect-all customtkinter `
  --collect-all huggingface_hub `
  main_gui.py
```

This creates a folder with the EXE and all dependencies (easier to debug, but more files to distribute).

## Step 4: Locate Your EXE

After the build completes, you'll find:
- **One-file build**: `dist/HF_Dataset_Uploader.exe`
- **Multi-file build**: `dist/HF_Dataset_Uploader/HF_Dataset_Uploader.exe`

## Step 5: Test the EXE

1. Double-click the EXE to run it
2. Fill in the fields and test with `--dry-run` equivalent (if adding that option)
3. Check that all functionality works

## Troubleshooting

### "Module not found" errors
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Use `--collect-all <module>` for each missing module
- Example: `--collect-all requests --collect-all tqdm`

### GUI doesn't display
- Make sure CustomTkinter is installed: `pip install customtkinter`
- Check for Python version conflicts (needs Python 3.10+)

### Large EXE file size
- One-file builds are large (~200-300 MB) because they include all dependencies
- Use the `--multi-file` version for smaller individual files (but more of them)

### Windows SmartScreen warning
- This is a false positive; users should click "More info" → "Run anyway"
- To prevent this, you'd need a code-signing certificate (paid)

### Antivirus flags
- PyInstaller-generated EXEs can trigger false positives
- Consider using `--clean` to remove build artifacts between builds
- Upload the final EXE to VirusTotal for verification

## Advanced: Creating an Installer with NSIS

For professional distribution, consider creating an installer:

1. Install NSIS: https://nsis.sourceforge.io/
2. Use a tool like `auto-py-to-exe` or create a custom `.nsi` script
3. This allows users to install to `Program Files` and create Start Menu shortcuts

## GitHub Actions for Automated Builds (Optional)

You can set up GitHub Actions to automatically build the EXE for every release:

See `.github/workflows/build.yml` (if created)

---

## Summary Commands

**Quick build (all-in-one):**
```powershell
cd hf_bulk_upload_tool
pyinstaller --onefile --noconsole `
  --name "HF_Dataset_Uploader" `
  --collect-all customtkinter `
  --collect-all huggingface_hub `
  main_gui.py
```

**Then run:**
```powershell
.\dist\HF_Dataset_Uploader.exe
```

That's it! Your portable GUI uploader is ready to distribute.
