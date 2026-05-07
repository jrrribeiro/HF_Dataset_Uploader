# 🚀 Release Process - BirdNET Uploader Windows Portable

Este documento descreve o fluxo completo para construir, testar e publicar a versão Windows portable do BirdNET Uploader.

## Visão Geral do Fluxo

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  1. Build Local  │ → │  2. Upload HF    │ → │ 3. Update App    │
│  PyInstaller     │     │  (Dataset)       │     │ Links & Deploy   │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

## Requisitos

- **Python 3.11+** com `pip` configurado
- **Hugging Face CLI**: `huggingface-cli` instalado
- **Token HF**: Com permissão `write` em dataset (obtenha em https://huggingface.co/settings/tokens)
- **Espaço em disco**: ~3 GB (para build + temp files)
- **Windows 10/11** para build do .exe (ou use CI/CD)

## Passo a Passo

### 1️⃣ Build Local do Executável

```powershell
# Navegar para o diretório do projeto
cd C:\Users\seu_usuario\Documents\Python\BirdNET-Uploader-App

# Instalar dependências de build
python -m pip install -q pyinstaller

# Executar o build (demora ~5-10 minutos)
python build/release_uploader.py --version 1.0.0
```

**Resultado:**
- Arquivo criado: `build/release/birdnet-uploader-1.0.0-windows.zip` (~100 MB)
- Arquivo criado: `build/release/birdnet-uploader-1.0.0-windows.zip.sha256`

### 2️⃣ Criar Dataset no Hugging Face (Primeira Vez)

Acesse https://huggingface.co/new-dataset e configure:

- **Repository name**: `birdnet-uploader-releases`
- **License**: `mit`
- **Private**: Deixe **desmarcado** (público)

### 3️⃣ Upload para Hugging Face

```powershell
# Definir variáveis de ambiente
$env:HF_TOKEN = "hf_xxxxxxxxxxxx"  # Seu token HF

# Executar script de upload
.\scripts\upload_release.ps1 `
  -Version 1.0.0 `
  -RepoId "your-org/birdnet-uploader-releases"
```

Ou usar o script Python direto:

```powershell
python scripts/upload_release_to_hf.py `
  --repo-id your-org/birdnet-uploader-releases `
  --version 1.0.0 `
  --token $env:HF_TOKEN
```

### 4️⃣ Atualizar Links na Aplicação Web

Após upload bem-sucedido, você receberá URLs como:

```
https://huggingface.co/datasets/your-org/birdnet-uploader-releases/resolve/main/releases/v1.0.0/birdnet-uploader-1.0.0-windows.zip
```

**Atualize** [src/uploader/web_ui.py](../src/uploader/web_ui.py):

```python
# Procure por "with gr.Group("Download")" e atualize a URL
new_url = "https://huggingface.co/datasets/your-org/birdnet-uploader-releases/resolve/main/releases/v1.0.0/birdnet-uploader-1.0.0-windows.zip"
```

### 5️⃣ Deploy no Hugging Face Spaces

Se você tem um Space com o app:

```bash
# Commit e push as alterações
git add src/uploader/web_ui.py
git commit -m "Release 1.0.0: Update Windows portable download link"
git push

# O Space será atualizado automaticamente (ou você pode forçar rebuild)
```

## Verificação Pré-Release

Antes de publicar, valide:

### ✅ Teste Local do Executável

```powershell
# Extrair o ZIP
Expand-Archive -Path "build/release/birdnet-uploader-1.0.0-windows.zip" `
  -DestinationPath "temp_test"

# Testar interface web
cd temp_test/birdnet-uploader
.\birdnet-uploader.exe

# Abrir navegador em http://localhost:7860
# Testar login, upload de arquivo pequeno, etc.
```

### ✅ Validar Checksum

```powershell
# Verificar integridade do arquivo
$hash = Get-FileHash -Path "build/release/birdnet-uploader-1.0.0-windows.zip" -Algorithm SHA256
$hash.Hash  # Compare com arquivo .sha256
```

### ✅ Testar Download do HF

```powershell
# Depois do upload, baixar e validar
$url = "https://huggingface.co/datasets/your-org/birdnet-uploader-releases/resolve/main/releases/v1.0.0/birdnet-uploader-1.0.0-windows.zip"

# Download manual via navegador ou curl
curl -L -o test_download.zip $url

# Validar tamanho e integridade
Get-Item test_download.zip | Format-List Length
```

## Estrutura do Dataset HF

Após upload, seu dataset terá esta estrutura:

```
birdnet-uploader-releases/
├── releases/
│   ├── v1.0.0/
│   │   ├── birdnet-uploader-1.0.0-windows.zip
│   │   └── birdnet-uploader-1.0.0-windows.zip.sha256
│   ├── v1.1.0/
│   │   ├── birdnet-uploader-1.1.0-windows.zip
│   │   └── birdnet-uploader-1.1.0-windows.zip.sha256
│   └── README.md (opcional)
└── ...
```

## Automação com GitHub Actions

Para automatizar o build e upload (futuro):

```yaml
# .github/workflows/release.yml
name: Build and Release Windows Portable

on:
  push:
    tags:
      - 'v*.*.*'

jobs:
  build-and-upload:
    runs-on: windows-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install -r requirements.txt
          python -m pip install pyinstaller
      
      - name: Build Windows executable
        run: python build/release_uploader.py --version ${{ github.ref_name }}
      
      - name: Upload to Hugging Face
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
        run: |
          python scripts/upload_release_to_hf.py `
            --repo-id jrrribeiro/birdnet-uploader-releases `
            --version ${{ github.ref_name }}
```

## Troubleshooting

### Erro: "File not found" durante build

```
Release file not found: build/release/birdnet-uploader-1.0.0-windows.zip
```

**Solução**: Execute `python build/release_uploader.py --version 1.0.0` primeiro.

### Erro: "Authentication failed" durante upload

```
HfApi.upload_file(): Invalid token or insufficient permissions
```

**Solução**:
1. Gere novo token em https://huggingface.co/settings/tokens
2. Certifique-se de ter permissão `write`
3. Execute `huggingface-cli login` novamente

### Executável não abre após download

**Solução**:
1. Desative Windows Defender temporariamente (é falso positivo)
2. Ou execute: `powershell -Command "Unblock-File -Path 'birdnet-uploader.exe'"`

### Arquivo ZIP muito grande (>200 MB)

**Causa**: Dependências desnecessárias incluídas

**Solução**: Atualize `build/pyinstaller_uploader.spec` para excluir módulos desnecessários:

```python
# No spec file, adicione em excludes:
excludes=['PIL', 'scipy', 'sklearn', 'torch', ...]
```

## Documentação para Usuários

Após publicar, compartilhe o [WINDOWS_PORTABLE_SETUP.md](./WINDOWS_PORTABLE_SETUP.md) com instruções de instalação.

## Checklist de Release

- [ ] Build local completado sem erros
- [ ] Teste do executável realizado
- [ ] Checksum verificado
- [ ] Dataset criado no HF (primeira vez)
- [ ] Upload concluído com sucesso
- [ ] Links atualizados em `src/uploader/web_ui.py`
- [ ] Changes commitadas e pushed
- [ ] Space/App atualizado
- [ ] Documentação atualizada
- [ ] Versão marcada no Git (git tag v1.0.0)

## Versioning

Use **Semantic Versioning**:
- **Major.Minor.Patch** (ex: 1.0.0, 1.1.0, 1.1.1)
- Major: Mudanças incompatíveis
- Minor: Novo recurso compatível
- Patch: Bugfix compatível

## Suporte

Dúvidas? Abra uma issue em: https://github.com/jrrribeiro/BirdNET-Uploader-App/issues
