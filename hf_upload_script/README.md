# hf_upload_script

Standalone project for CLI-based operations.

## Objective
*   Execute the upload workflow via command-line interface.
*   Maintain clear separation of logic from the GUI-based application (`hf_upload_app`).

## Installation
```bash
python -m pip install -r requirements.txt
```

## Usage
```bash
python app.py --help
```

For a complete usage guide with examples, see [HOW_TO_USE.md](HOW_TO_USE.md).

### Recommended large upload mode
The default `upload` mode is optimized for large Hugging Face Dataset uploads:

```bash
python app.py upload ^
  --repo-id owner/dataset-name ^
  --segments C:\path\to\Segments ^
  --csv C:\path\to\DETECTIONS.csv ^
  --workers 8
```

This mode:
* scans local audio files once;
* lists remote repository files once;
* creates a delta upload plan;
* stages files into sharded folders under `audio/<logical_group>/shard-000000/`;
* writes `index/files.parquet` as the logical dataset index;
* uploads with Hugging Face `upload_large_folder`.

Use `--max-files-per-folder` to keep validation-friendly folders below Hub limits
and `--staging-mode copy` when hardlinks are not available.

## Repository Structure
*   `app.py`: CLI entrypoint.
*   `uploader/`: Upload modules and support logic.
*   `requirements.txt`: Project dependencies.
*   `Temp/`: Local temporary files.

## Notes
*   This module operates independently from `hf_upload_app`.
*   Use `Temp/` for temporary outputs, local tests, and intermediate artifacts.
