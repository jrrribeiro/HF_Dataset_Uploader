# Rate Limiter Guide for Large Datasets

## Overview

The upload script now includes an intelligent **rate limiter** that respects the Hugging Face API quota of **1000 requests per 5 minutes**. This allows you to upload very large datasets (150k+ files) automatically without hitting rate limits.

## How It Works

**Sliding Window Rate Limiting:**
- Tracks requests over the last 5 minutes
- When reaching ~950 requests (safety buffer), pauses automatically
- Resumes when old requests drop out of the window
- Completely transparent — happens in the background

Example timeline for 150k small files:
```
Minute 0-5:    Upload files 1-1000       (1000 requests)
Minute 5-10:   Wait 5 sec, then files 1001-2000 (1000 requests)
Minute 10-15:  Wait 5 sec, then files 2001-3000 (1000 requests)
...
Minute 750-760: Upload final files
Total time: ~12.5 hours (continuous, no manual waits)
```

## Enabling Rate Limiter

Rate limiter is **enabled by default**. Use it with:

```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --csv "C:\path\to\detections.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --resume
```

To disable (not recommended):
```powershell
python ... --rate-limit-aware False
```

## Disabling Verify-Remote for Speed

**Important:** If resuming with `--resume`, do NOT use `--verify-remote` by default — it doubles the requests!

✅ **Good (safe for 150k files):**
```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --csv "C:\path\to\detections.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --resume
```
Estimated time: ~12 hours (150k requests at 1000/5min)

❌ **Slow (not recommended for 150k files):**
```powershell
python ... --resume --verify-remote
```
Estimated time: ~24 hours (300k requests)

## Handling Interruptions

If the script crashes or network fails mid-upload:

1. **Wait a moment** (to ensure checkpoint is flushed)
2. **Re-run the exact same command:**
```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\path\to\segments" `
  --csv "C:\path\to\detections.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --resume
```

The script will:
- Load the checkpoint (files already uploaded)
- Skip all completed files
- Continue from where it left off
- **No re-uploading, no wasted time**

## Checkpoint Storage

Checkpoints are stored in `.checkpoints/`:
```
.checkpoints/
  jrrribeiro__PPBIO_Audio_Library.json        # List of uploaded files + SHA-256 hashes
  progress.csv                                 # Per-file logs
  jrrribeiro__PPBIO_Audio_Library.summary.json # Final stats
```

Customize location:
```powershell
python ... --checkpoint-dir "C:\my\custom\path"
```

## Rate Limiter Configuration

Override defaults if needed:

| Option | Default | Description |
|--------|---------|-------------|
| `--rate-limit-aware` | True | Enable/disable rate limiter |
| `--rate-limit-max-requests` | 950 | Max requests before pause (safety buffer below 1000) |
| `--rate-limit-window` | 300 | Window duration in seconds (300 = 5min) |

Example (more conservative):
```powershell
python ... `
  --rate-limit-max-requests 800 `
  --rate-limit-window 300
```

## Request Counting

The script counts these as API requests:
- **File upload** (each file) = 1 request
- **List repo files** (resume mode, once) = 1 request
- **Verify remote** (if --verify-remote per file) = 1 request
- **CSV upload** = 1 request

For 150k small files with `--resume` (no verify-remote):
- ~150,000 file uploads
- ~1 list_repo_files
- ~1 CSV upload
- **Total: ~150,002 requests ≈ 150 windows ≈ 750 minutes ≈ 12.5 hours**

## Monitoring Progress

Progress is shown in real-time:
```
Uploading: |████████░░░░░░░░░░| 25% [2.5 GB / 10 GB] ETA 9h 15m
[RateLimit] 948 / 950 requests in current window (3 min left)
```

Key metrics in logs:
- Bytes uploaded
- Current rate limiter window status
- Estimated time remaining

## Best Practices for 150k Files

1. **Start fresh or resume:**
   ```powershell
   # First run
   python ... --resume
   ```

2. **Keep machine awake** (disable sleep/screensaver)

3. **Stable network** (hardwired Ethernet if possible)

4. **One worker** (default):
   ```powershell
   python ... --max-workers 1
   ```

5. **Monitor first hour** to ensure everything is working, then let it run

6. **Use `--checkpoint-dir` on a reliable disk** (not network drive)

## Troubleshooting

**Q: Script paused and shows "Waiting Xs before next request"**  
A: Normal! This is the rate limiter preventing 429 errors. Let it continue.

**Q: Got 429 anyway?**  
A: Rare, but possible if:
- Another client is using the same token
- HF already counted background requests in your quota
- Solution: Wait 10 min, then resume with `--rate-limit-max-requests 800`

**Q: Can I speed this up?**  
A: Only if HF allows higher limits (PRO account). Otherwise, the 1000 req/5min is the hard limit.

**Q: How do I monitor progress without staying in the terminal?**  
A: Script logs to `.checkpoints/progress.csv` — check that anytime.

## Example Commands

### First run (full upload):
```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Segments" `
  --csv "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Analyzer\00_ALL_DETECTIONS.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --resume
```
ETA: ~12 hours (150k files)

### Resume after interruption:
```powershell
# Same command as above
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Segments" `
  --csv "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Analyzer\00_ALL_DETECTIONS.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --resume
```
Continues from where it left off — only uploads new/missing files.

### Conservative (slower, more stable):
```powershell
python .\hf_bulk_upload_tool\upload_dataset.py `
  --repo-id "jrrribeiro/PPBIO_Audio_Library" `
  --segments "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Segments" `
  --csv "C:\Users\jonat\OneDrive - MSFT\Doutorado PPGEtno\BirdNET Analyzer\00_ALL_DETECTIONS.csv" `
  --hf-token "<YOUR_HF_TOKEN>" --private `
  --resume `
  --rate-limit-max-requests 800
```
ETA: ~15 hours (more safety margin)

---

**Ready to start?** Run the first command above and let it work for 12+ hours. The rate limiter will handle everything automatically!
