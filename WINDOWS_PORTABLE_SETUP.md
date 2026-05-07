# BirdNET Uploader - Windows Portable Setup

## Overview

O **BirdNET Uploader para Windows** é uma aplicação portátil que permite fazer upload de arquivos de áudio para Hugging Face sem necessidade de instalar Python ou dependências.

## Como usar

### 1. Download

Baixe o arquivo `birdnet-uploader-windows.zip` da [página de releases](https://huggingface.co/spaces/your-org/birdnet-uploader) ou diretamente do [Hugging Face](https://huggingface.co/spaces/your-org/birdnet-uploader-releases/tree/main).

### 2. Extração

Descompacte o arquivo em uma pasta de sua escolha, por exemplo:
```
C:\BirdNET-Uploader\
├── birdnet-uploader.exe
├── _internal\  (dependências do Python)
└── ...
```

### 3. Executar o Aplicativo

Existem duas formas de usar:

#### **Opção A: Interface Gráfica (Web)**
Simplesmente clique duas vezes em `birdnet-uploader.exe`. Isso abrirá a aplicação no seu navegador padrão em `http://localhost:7860`.

**Funcionalidades:**
- Upload de arquivos de áudio individuais
- Upload de arquivos em pacotes (.tar, .tar.gz, .zip)
- Upload opcional de arquivo CSV com metadados de detecção
- Progresso em tempo real
- Limite: até ~1 GB por sessão

#### **Opção B: Linha de Comando (CLI)**
Abra um terminal (PowerShell ou CMD) na pasta `BirdNET-Uploader` e use os comandos:

```powershell
# Ver todos os comandos disponíveis
.\birdnet-uploader.exe --help

# Login (armazena token com segurança)
.\birdnet-uploader.exe login

# Upload de uma pasta local
.\birdnet-uploader.exe upload `
  --repo-id username/dataset-name `
  --segments C:\caminho\para\audio `
  --csv C:\caminho\para\detections.csv `
  --workers 4

# Ver status da sessão
.\birdnet-uploader.exe resume abc-session-id-xyz

# Scan de arquivos (sem fazer upload)
.\birdnet-uploader.exe scan --segments C:\caminho\para\audio
```

## Requisitos

- **Espaço em disco**: ~2 GB (para arquivos temporários durante upload)
- **Conexão de internet**: Recomenda-se conexão estável
- **Windows**: 7 ou mais recente (32 ou 64 bits)

## Configuração Avançada

### Variáveis de Ambiente

Se precisar de configurações customizadas, defina variáveis de ambiente antes de rodar:

```powershell
# Usar modo CLI ao invés de Web
$env:BIRDNET_UPLOADER_CLI = "true"

# Mudar porta do servidor web
$env:BIRDNET_UPLOADER_PORT = "8080"

# Folder para sessões (default: C:\Users\seu_usuario\.birdnet-uploader\sessions)
$env:BIRDNET_UPLOADER_SESSION_DIR = "D:\BirdNET-Sessions"

# Token do HF (não recomendado para segurança)
$env:HF_TOKEN = "hf_xxxxxxxxxxxx"
```

Depois, rode o exe normalmente:
```powershell
.\birdnet-uploader.exe
```

## Solução de Problemas

### "O Windows protegeu seu computador"

Se receber um aviso de segurança:
1. Clique em **"Mais informações"**
2. Clique em **"Executar mesmo assim"**

Este aviso aparece porque o arquivo é novo e não possui certificado de segurança Windows.

### Upload falha com "HTTP 401"

- Verifique se o token HF está correto
- Abra https://huggingface.co/settings/tokens e valide
- Certifique-se de ter permissão `write` no dataset

### "Token not found" ao usar CLI

Execute primeiro:
```powershell
.\birdnet-uploader.exe login
```

Isto armazena o token de forma segura no seu computador.

### Upload interrompido

O aplicativo suporta retomar:
```powershell
# Listar ID da sessão anterior
dir C:\Users\seu_usuario\.birdnet-uploader\sessions\

# Retomar upload
.\birdnet-uploader.exe upload `
  --repo-id username/dataset-name `
  --segments C:\caminho\para\audio `
  --session-id upload-20260507T...
```

## Estrutura do Dataset

Após o upload, seus dados aparecerão no Hugging Face com esta estrutura:

```
meu-dataset/
├── audio/              # Arquivos de áudio
├── index/
│   ├── manifest.json   # Metadados do upload
│   ├── detections.csv  # CSV original (se fornecido)
│   └── shards/         # Índices Parquet (se CSV fornecido)
```

## Dicas de Performance

1. **Para uploads grandes**: Use CLI em vez de web UI
   - CLI: Sem limite de tamanho
   - Web: Limite ~1 GB

2. **Aumente paralelismo**: Use `--workers 8` ou mais na CLI

3. **Comprima bem**: Use `.tar.gz` ao invés de `.zip` para melhor compressão

4. **Conexão estável**: Não interrompa o upload. O aplicativo pode retomar.

## Suporte

- Dúvidas? Abra uma issue no [GitHub](https://github.com/jrrribeiro/BirdNET-Uploader-App/issues)
- Reportar bugs: Use o formulário de issues com detalhes do erro
- Chat: Veja [Discussions](https://github.com/jrrribeiro/BirdNET-Uploader-App/discussions)

## Licença

MIT License - Veja LICENSE para detalhes

---

**Desenvolvido para** [BirdNET](https://birdnet.cornell.edu/)
