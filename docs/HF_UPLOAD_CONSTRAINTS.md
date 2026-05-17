# HF Upload Constraints & Mitigation Strategies

## Critical Constraints

### 1. **Commits per Hour Limit (128/hora)** ✅ MITIGATED
- **Limit**: Max 128 commits per hour per account/repo
- **Impact**: 150k files ≈ 12.5 hours at 128 commits/hour if using per-file commits
- **Current Mitigation**: `RateLimiter` class + `upload_large_folder()` batching
- **Status**: Handled via sliding window rate limiter (1000 req/5min quota)

### 2. **10k Files per Directory Hard Limit** ✅ MITIGATED
- **Limit**: HF enforces max 10k files per directory
- **Impact**: `Elaenia albiceps` exceeded 10k, blocking upload
- **Current Mitigation**: `sharding_utils.py` automatically shards large species
- **Status**: Auto-sharding to `species__shard_00`, `__shard_01`, etc.

---

## Remaining Critical Constraints (NOT YET MITIGATED)

### 3. **HTTP Timeouts During Large Transfers** ⚠️ RISK
- **Limit**: Default HTTP connection timeout ~20-30 seconds per request
- **Impact**: `upload_large_folder()` may abort mid-upload if network is slow
- **File Size Range**: With 146,563 files (~55.6GB), average ≈ 380KB/file
- **Risk**: Slow network or large files could trigger 504 Gateway Timeout
- **Mitigation Options**:
  - Increase `HF_HUB_ETAG_TIMEOUT` and `HF_HUB_DOWNLOAD_TIMEOUT` (already set to 20s & 120s)
  - Implement exponential backoff for individual failed files
  - Split into smaller batches if upload stalls

**Current Settings** (in `upload_dataset.py`):
```python
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "20")        # HEAD/metadata requests
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")   # Actual uploads
```

### 4. **Repository Locking During Garbage Collection** ⚠️ RISK
- **When**: HF may trigger GC/optimization after certain commit counts
- **Duration**: Unknown (minutes to hours potentially)
- **Impact**: API calls return 429 Too Many Requests or repo becomes temporarily read-only
- **Frequency**: Unknown schedule, likely triggered by repo size/commit count
- **Mitigation Options**:
  - Implement backoff detection (watch for 429 + high wait-time headers)
  - Resume capability (already implemented via checkpoints)
  - Monitor repo status before resuming

### 5. **Account-Level Rate Limits Beyond Commits** ⚠️ RISK
- **Type**: Global per-account API call limits (not just commits)
- **Limit**: Unknown exact value, but ~10k+ API calls/day should be safe
- **Current Usage**: `upload_large_folder()` batches files, reducing API calls
- **Risk**: If fallback to per-file upload triggered, could exceed limits

**Estimated API calls**:
- Per-file upload: 150k files × 2-3 calls each = 300k-450k API calls (RISKY)
- Batch upload: ~100-200 API calls total (SAFE)

### 6. **Network Interruption / Resume Limitations** ⚠️ RISK
- **Issue**: If connection drops mid-upload, `upload_large_folder()` may not resume cleanly
- **Current State**: Script supports `--resume` but it compares LOCAL vs REMOTE
- **Gap**: If a file was partially uploaded (corrupted), resume logic may skip it
- **Mitigation Options**:
  - ETag comparison on resume (already has `--verify-etag` flag)
  - File integrity checking (hash verification)
  - Checkpoint system tracks uploaded files

### 7. **Token Expiration During Long Uploads** ⚠️ RISK
- **Duration**: Long-lived tokens expire after 30 days by default
- **Upload Duration**: 150k files at rate-limited pace = ~1-2 weeks minimum
- **Impact**: Upload fails if token expires mid-process
- **Mitigation Options**:
  - Use indefinite tokens (if available in HF account settings)
  - Monitor token expiry and warn user
  - Request fresh token before resuming long uploads

### 8. **Concurrent Upload Conflicts** ⚠️ RISK
- **Issue**: If multiple processes upload to same repo simultaneously
- **Impact**: Race conditions, corrupted commits, 429 errors
- **Current State**: Single-threaded by design (only `max_workers` for fallback)
- **Mitigation**: Document that only ONE upload process per repo allowed

### 9. **Large File Size Limits** ⚠️ MINOR RISK
- **Limit**: HF has no explicit per-file size limit for datasets
- **Practical Limit**: Files >1GB may timeout (network dependent)
- **Current Files**: Average 380KB, max likely <50MB (safe)
- **Risk**: Minimal, but worth verifying pre-upload

### 10. **Storage Quota Per Account** ⚠️ MINOR RISK
- **Limit**: Free accounts have soft limits (exact value unknown)
- **Current Dataset**: 55.6GB total
- **Risk**: Minimal for paid HF accounts, possible for free tier
- **Mitigation**: Check account storage before starting upload

### 11. **LFS (Large File Storage) Costs** ℹ️ INFORMATIONAL
- **Applies To**: Files >100MB (likely not applicable here)
- **Cost**: $5/month per 1GB LFS bandwidth
- **Risk**: Minimal with 380KB average files

### 12. **Repo Size Limits** ⚠️ MINOR RISK
- **Practical Limit**: HF datasets can be very large (multi-TB known)
- **Current**: 55.6GB well within limits
- **Risk**: Minimal

---

## Recommended Mitigations (Priority Order)

### Priority 1: Implement Now
1. ✅ **Sharding for large species** - DONE
2. ✅ **Rate limiting** - DONE
3. ⚠️ **ETag-based resume verification** - PARTIALLY DONE (flag exists, verify usage)
4. ⚠️ **Network timeout handling** - IMPROVE exponential backoff for failed individual files

### Priority 2: Implement Before Production
1. **Token expiration warning** - Check token age before upload starts
2. **File integrity checking** - Optional hash verification on resume
3. **Graceful shutdown** - Handle Ctrl+C cleanly, save checkpoint
4. **Network retry strategy** - Custom retry with longer waits for timeouts

### Priority 3: Monitor During Upload
1. **Log HF API response headers** - Watch for `Retry-After` hints
2. **Alert on 429 errors** - Detect if GC/locking is happening
3. **Validate checkpoint consistency** - Periodically verify already-uploaded files

---

## Estimated Upload Timeline

### Conservative Scenario (Rate-Limited)
```
Total Files: 150,000
Average File Size: 380KB
Batch Size: 1,000 files per upload_large_folder() call
Commits Generated: ~1 commit per 1,000 files = 150 commits
Rate Limit: 128 commits/hour

Timeline:
  150 commits ÷ 128 commits/hour = 1.17 hours minimum (rate-limit dominated)
  + Network overhead (10-20% of total time)
  = ~2-3 hours total minimum
```

### Realistic Scenario (With Network Variance)
```
Assumptions:
  - Some files timeout and retry (add 30 min)
  - Network interruptions (add 1-2 hours for recovery)
  - GC pauses (add 30 min - 2 hours)
  - Resume/verification between sessions (add 30 min per resume)

Estimated Timeline: 4-8 hours actual upload time
Wallclock Time: 1-2 days (depending on interruptions + resume cycles)
```

### Worst Case (Multiple Failures)
```
Multiple network drops + GC pauses + token issues = 3-5 days
Mitigation: Strong checkpoint system + graceful resume
```

---

## Current Implementation Status

| Feature | Status | Details |
|---------|--------|---------|
| Rate limiting (128 commits/hour) | ✅ Done | RateLimiter class + sliding window |
| Sharding (10k files/dir) | ✅ Done | Auto-shard with TransparentSpeciesReader |
| Resume capability | ✅ Done | Checkpoint-based with ETag option |
| Exponential backoff | ✅ Done | Per-file upload fallback |
| Timeout handling | ⚠️ Partial | Env vars set, but could add more granular retry |
| Token expiration check | ❌ Todo | Add warning if token expiring soon |
| Concurrent upload detection | ❌ Todo | Document or implement lock file |
| Network retry strategy | ⚠️ Partial | Basic retry, could improve for timeouts |
| Hash-based verification | ❌ Todo | Optional additional safety check |

---

## Recommended Next Steps

### Before Running Production Upload:
1. **Set up monitoring**
   - Log all API responses with status codes
   - Track retry counts and wait times
   - Alert on 429 errors (GC detected)

2. **Test resume cycle**
   - Start upload
   - Interrupt mid-process (Ctrl+C)
   - Resume and verify consistency

3. **Validate sharding**
   - Run with `--dry-run` to see shard distribution
   - Verify all shards created before actual upload

4. **Check token lifetime**
   - Ensure token won't expire during 1-2 week upload window

### During Upload:
1. Monitor logs for patterns:
   - Increasing wait times = approaching rate limit
   - 504 errors = network timeouts (add more aggressive retry)
   - 429 with Retry-After > 1000s = GC happening (expect delays)

2. Handle graceful resumption:
   - If interrupted, checkpoint auto-saves
   - Resume with `--resume` flag
   - Verify no duplicate uploads

### After Upload:
1. Spot-check random species in HF repo
2. Verify shard counts match expected
3. Test validation tool reads all shards correctly
