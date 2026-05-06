# Token Security Guide

This guide explains how to securely manage Hugging Face tokens in BirdNET Uploader.

## Token Resolution Order

The uploader resolves tokens in this order (highest to lowest priority):

1. **`--token` CLI option** – Use `--token hf_...` in the command
2. **`HF_TOKEN` environment variable** – Set `HF_TOKEN=hf_...` before running the CLI
3. **Keyring secure storage** – Use `birdnet-uploader login` to store the token securely

## Usage Methods

### Method 1: CLI Option (Least Secure for Scripting)

```bash
birdnet-uploader upload \
  --repo-id user/dataset \
  --segments ./segments \
  --token hf_aBcDeF123456
```

**Warning**: Token appears in shell history. Use only for interactive use or in CI/CD secrets.

### Method 2: Environment Variable (Recommended for Docker/CI)

**Local machine:**
```bash
export HF_TOKEN=hf_aBcDeF123456
birdnet-uploader upload --repo-id user/dataset --segments ./segments
```

**Docker:**
```bash
docker run --rm \
  -e HF_TOKEN="hf_aBcDeF123456" \
  -v C:/segments:C:/data/segments \
  -v C:/uploads:C:/data/sessions \
  birdnet-uploader:latest \
  upload --repo-id user/dataset --segments C:/data/segments
```

**GitHub Actions:**
```yaml
- name: Upload to Hugging Face
  env:
    HF_TOKEN: ${{ secrets.HF_TOKEN }}
  run: |
    birdnet-uploader upload \
      --repo-id user/dataset \
      --segments ./segments
```

**Docker Compose:**
```yaml
services:
  uploader:
    image: birdnet-uploader:latest
    environment:
      - HF_TOKEN=${HF_TOKEN}
    volumes:
      - ./segments:/data/segments
      - ./sessions:/data/sessions
```

### Method 3: Keyring Secure Storage (Recommended for Interactive Use)

Store token securely using your OS credential manager:

```bash
# Store token in keyring (Credential Manager on Windows, Keychain on macOS, Secret Service on Linux)
birdnet-uploader login
# Prompted for token, stored securely

# Use without --token option (reads from keyring)
birdnet-uploader upload --repo-id user/dataset --segments ./segments
```

**Verify stored token:**
```bash
# On Windows PowerShell
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
# Token is stored in Credential Manager under "birdnet-uploader" / "hf_token"
```

**Clear stored token:**
```bash
# Using a logout command (if implemented) or manually via Credential Manager:
# Windows: Control Panel > Credential Manager > Windows Credentials > birdnet-uploader
```

## Security Best Practices

### ✅ Do This

- ✅ Use `HF_TOKEN` environment variable in Docker/CI environments
- ✅ Use keyring storage (`birdnet-uploader login`) for local interactive use
- ✅ Store tokens in CI/CD secret managers (GitHub Secrets, GitLab CI Variables, etc.)
- ✅ Use Docker secrets for orchestrated environments (Kubernetes, Docker Swarm)
- ✅ Rotate tokens periodically (every 3-6 months)
- ✅ Use read-only tokens when possible (limited to specific datasets)

### ❌ Don't Do This

- ❌ Hardcode tokens in scripts or configuration files
- ❌ Commit tokens to version control (even in `.env` files)
- ❌ Pass tokens as CLI arguments in shared environments (appears in process lists)
- ❌ Log or print tokens (the CLI never displays tokens in output)
- ❌ Share tokens via email or unencrypted communication
- ❌ Use the same token across multiple services/projects

## Container-Specific Guidance

### Windows Container Example

```dockerfile
# Dockerfile (do NOT include token)
FROM birdnet-uploader:latest

WORKDIR C:\uploads
```

**Run with token:**
```powershell
docker run --rm `
  -e HF_TOKEN="hf_aBcDeF123456" `
  -v "C:\segments:C:\data\segments" `
  -v "C:\sessions:C:\data\sessions" `
  birdnet-uploader:latest `
  upload --repo-id user/dataset --segments C:\data\segments
```

### Docker Compose with Secrets

```yaml
version: '3.8'
services:
  uploader:
    image: birdnet-uploader:latest
    environment:
      - HF_TOKEN=/run/secrets/hf_token
    secrets:
      - hf_token
    volumes:
      - ./segments:/data/segments
      - ./sessions:/data/sessions

secrets:
  hf_token:
    external: true
```

Create and run:
```bash
echo "hf_aBcDeF123456" | docker secret create hf_token -
docker-compose up
```

## Token Permissions

When creating your Hugging Face token:

1. Go to [Hugging Face Settings > Access Tokens](https://huggingface.co/settings/tokens)
2. Create a **"Fine-grained"** token with minimal required permissions:
   - **Permissions**: `repo.content.write`, `repo.content.read`
   - **Repositories**: Specify only the dataset repo you're uploading to
   - **Expiration**: Set to 3-6 months

This limits the blast radius if the token is compromised.

## Troubleshooting

### "No stored token found" error

```bash
# Solution 1: Use HF_TOKEN environment variable
export HF_TOKEN=hf_aBcDeF123456

# Solution 2: Use CLI --token option
birdnet-uploader upload --repo-id user/dataset --segments ./segments --token hf_aBcDeF123456

# Solution 3: Store token via login
birdnet-uploader login
# Enter token when prompted
```

### Token validation failed

1. Verify token format starts with `hf_`
2. Check token hasn't expired (renew at https://huggingface.co/settings/tokens)
3. Verify token has `repo.content.write` permission on target dataset
4. Test token with: `curl -H "Authorization: Bearer hf_aBcDeF123456" https://huggingface.co/api/user`

### Token leaks in logs

The CLI is designed never to log or display tokens. If you see a token in logs:

1. **Never commit the leaked token** – regenerate immediately
2. **Rotate the token** at https://huggingface.co/settings/tokens
3. **Report to Hugging Face** if suspicious activity detected

## Environment Variable Reference

| Variable | Purpose | Default | Example |
|----------|---------|---------|---------|
| `HF_TOKEN` | Authentication token | (not set) | `hf_aBcDeF123456` |
| `BIRDNET_UPLOADER_DATA_DIR` | Session/cache root (container) | `~/.birdnet-uploader` | `C:\data` |
| `BIRDNET_UPLOADER_SESSION_DIR` | Override session directory | `$DATA_DIR/sessions` | `/tmp/sessions` |
| `BIRDNET_UPLOADER_CACHE_DIR` | Override cache directory | `$DATA_DIR/cache` | `/tmp/cache` |

## FAQ

**Q: Is the token stored after using `--token` CLI option?**
A: No. The `--token` option is used only for that command. Use `birdnet-uploader login` to store permanently.

**Q: Can I use different tokens for different datasets?**
A: Currently, only one token is stored in keyring. For multiple datasets, use `HF_TOKEN` env var or `--token` option per command.

**Q: What happens if I expose HF_TOKEN in docker run history?**
A: It's visible in `docker history` and shell history. Use Docker secrets or `.env` files with `docker-compose` for better isolation.

**Q: How do I rotate tokens without stopping the container?**
A: Set a new `HF_TOKEN` env var and restart the container, or pass `--token` directly to each command.

**Q: Are tokens encrypted in keyring storage?**
A: Yes. Keyring uses OS-level credential storage:
- **Windows**: Credential Manager (DPAPI encrypted)
- **macOS**: Keychain (encrypted)
- **Linux**: Secret Service or pass (encrypted, if backend supports it)
