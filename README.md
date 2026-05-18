# HF Dataset Uploader

A robust pipeline for uploading BirdNET-generated audio segments and detection tables to Hugging Face Datasets.

## 💡 About
HF Dataset Uploader is designed to streamline the ecological data pipeline. It bridges the gap between raw BirdNET detection outputs—often containing statistical uncertainty and noise—and organized, actionable ecological datasets. The project facilitates the systematic upload of:

*   **Audio Segments:** Primary evidence of detection.
*   **Detection Tables (CSV):** Derived metadata.
*   **Auxiliary Manifests:** For auditability and quality control.

This repository enables a scientific workflow where uploads are later consumed in collaborative human-validation systems, ensuring reproducibility and traceability in Passive Acoustic Monitoring (PAM) projects.

## 📦 Project Structure
The repository is split into two independent modules:
*   `hf_upload_script`: Standalone CLI for automation, scripting, and pipeline integration.
*   `hf_upload_app`: Native Tkinter GUI application with support for packaging into a standalone Windows executable. The previous Gradio demo was moved to `hf_upload_app/Temp/gradio_ui/` for development.

## 🚀 Quick Start

### 1. CLI Usage (`hf_upload_script`)
Navigate to `hf_upload_script/`, install dependencies, and run commands:
```bash
python app.py --help
```

### 2. GUI/App Usage (`hf_upload_app`)
Navigate to `hf_upload_app/`, install dependencies, and run the native GUI:
```bash
python app_native.py
```

## 🛠️ Key Features
*   **Standardized Uploads:** Efficiently handle large batches of audio segments.
*   **Resumable Sessions:** Never lose progress; resume interrupted uploads seamlessly.
*   **Deduplication:** Smart remote dataset index checking to avoid redundant uploads.
*   **Flexible Operation:** Use the CLI for automation or the GUI for an assisted, interactive experience.
*   **Executable Ready:** Package the GUI app into a standalone executable for easy distribution.

## ⚙️ Configuration
The tool supports extensive environment-based configuration for authentication, paths, and upload tuning (e.g., `HF_TOKEN`, `BIRDNET_UPLOADER_DATA_DIR`, `BNU_HUB_UPLOAD_TIMEOUT`).

## 📚 Technical Documentation
*   `hf_upload_script/README.md`: Detailed CLI operation.
*   `hf_upload_app/README.md`: GUI operation and executable packaging guide.
*   `docs/`: Detailed scientific scope, operations guides, architecture, and troubleshooting.
