# Hostagem do Windows Portable no Hugging Face

## Visão Geral

O Windows portable (`birdnet-uploader-windows.zip`) deve ser:
1. **Construído** localmente com PyInstaller ✅ (Concluído)
2. **Hospedado** em um repositório Hugging Face (Dataset ou Space)
3. **Baixável** via link direto na página web

## Arquitetura de Hospedagem

```
┌─────────────────────────────────────────────────┐
│  Hugging Face Spaces (App Web)                  │
│  https://huggingface.co/spaces/your-org/...    │
│                                                 │
│  ┌──────────────────────────────────┐          │
│  │ BirdNET Uploader Interface       │          │
│  │ • Web UI (Gradio)                │          │
│  │ • ✅ Download Windows Portable   │          │
│  │ • Link para Dataset              │          │
│  └──────────────────────────────────┘          │
└─────────────────────────────────────────────────┘
                      ↓ (link)
┌─────────────────────────────────────────────────┐
│  Hugging Face Dataset (Release Repository)      │
│  https://huggingface.co/datasets/your-org/...   │
│                                                 │
│  releases/v1.0.0/                              │
│  ├── birdnet-uploader-1.0.0-windows.zip       │
│  └── birdnet-uploader-1.0.0-windows.zip.sha256│
└─────────────────────────────────────────────────┘
```

## Opção 1: Usar um Dataset Hugging Face (Recomendado)

### Passo 1: Criar um Dataset no HF

1. Acesse https://huggingface.co/new-dataset
2. Preencha:
   - **Repository name**: `birdnet-uploader-releases`
   - **License**: `mit`
   - **Private**: Deixe público para permitir downloads diretos

### Passo 2: Fazer Upload do Windows Portable

```bash
# Configurar token HF (em primeira vez)
huggingface-cli login
# Ou definir variável de ambiente
$env:HF_TOKEN = "hf_xxxxxxxxxxxx"

# Upload via script Python
python scripts/upload_release_to_hf.py `
  --repo-id your-org/birdnet-uploader-releases `
  --version 1.0.0
```

### Passo 3: Adicionar Link no Web UI

Edite [src/uploader/web_ui.py](./src/uploader/web_ui.py) para adicionar o link de download:

```python
with gr.Group("Download"):
    gr.Markdown("""
    ## 💾 Download Windows Portable
    
    Para uploads maiores (>1 GB) sem limite de tamanho, baixe o executável portátil:
    
    **[🔗 Download birdnet-uploader-1.0.0-windows.zip](https://huggingface.co/datasets/your-org/birdnet-uploader-releases/resolve/main/releases/v1.0.0/birdnet-uploader-1.0.0-windows.zip)**
    
    **Checksum SHA256:**
    ```
    [SHA256 aqui]
    ```
    """)
```

## Opção 2: Hospedar Diretamente em um Space

Se quiser hospedar o arquivo no próprio Space:

### Passo 1: Configurar Space com "Large File" Storage

1. Vá para o Settings do seu Space
2. Em "Persistent Data", ative "Ephemeral storage" ou use a aba "Files"
3. Upload manual do arquivo via interface

### Passo 2: Servir o Arquivo via Gradio

```python
import gr
from pathlib import Path

exe_path = Path("releases/birdnet-uploader-1.0.0-windows.zip")

if exe_path.exists():
    with gr.Group("Download Windows Portable"):
        gr.File(
            label="📥 Click to download Windows portable",
            value=str(exe_path),
        )
```

⚠️ **Limitação**: Espaço limitado, melhor para versão única.

## Opção 3: GitHub Releases + Link no HF

Se você usar GitHub para gerenciar releases:

```python
# No web_ui.py
download_url = "https://github.com/jrrribeiro/BirdNET-Uploader-App/releases/download/v1.0.0/birdnet-uploader-1.0.0-windows.zip"

with gr.Group("Download"):
    gr.Markdown(f"""
    [📥 Download Windows Portable](download_url)
    """)
```

## Fluxo de Release Completo

### Para cada nova versão (ex: 1.0.0):

```bash
# 1. Build local ✅ (já feito)
python build/release_uploader.py --version 1.0.0

# 2. Verificar arquivo
dir build\release\*.zip

# 3. Upload para HF Dataset
python scripts/upload_release_to_hf.py `
  --repo-id your-org/birdnet-uploader-releases `
  --version 1.0.0

# 4. Atualizar link no código
# Edite src/uploader/web_ui.py com novo link

# 5. Commit e push para repo
git add -A
git commit -m "Release v1.0.0: Windows portable"
git push
```

## Validação de Download

### Para usuários, validar integridade:

```powershell
# Após download
$expected = "hash-sha256-aqui"
$actual = (Get-FileHash -Path "birdnet-uploader-1.0.0-windows.zip" -Algorithm SHA256).Hash
if ($actual -eq $expected) {
    Write-Host "✅ Arquivo verificado com sucesso"
} else {
    Write-Host "❌ Checksum inválido!"
}
```

## Melhorias Futuras

1. **CDN**: Usar Cloudflare CDN para acelerar downloads
2. **Auto-update**: Implementar verificação de versão no app
3. **Code signing**: Assinar o .exe com certificado
4. **Mirror**: Hospedar em multiple plataformas (GitHub, SourceForge, etc)

## Recomendação Final

**Use a Opção 1 (Dataset HF)** porque:
- ✅ Hospedagem gratuita e ilimitada
- ✅ Download automático com HF CDN (rápido)
- ✅ Versionamento histórico
- ✅ Fácil integração com Space
- ✅ Sem dependência de GitHub
