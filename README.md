# HF Dataset Uploader

Pipeline de upload para segmentos de audio e deteccoes BirdNET em datasets do Hugging Face.

Este repositorio foi desenhado para um fluxo cientifico de curadoria: os segmentos e metadados enviados por este uploader sao consumidos posteriormente em um sistema de validacao manual e colaborativa, com foco em controle de qualidade de deteccoes bioacusticas.

## Sumario

- [1. Escopo Cientifico](#1-escopo-cientifico)
- [2. O que Este Projeto Resolve](#2-o-que-este-projeto-resolve)
- [3. Arquitetura do Repositorio](#3-arquitetura-do-repositorio)
- [4. Requisitos de Ambiente](#4-requisitos-de-ambiente)
- [5. Instalacao Rapida](#5-instalacao-rapida)
- [6. Como Usar - CLI (Script)](#6-como-usar---cli-script)
- [7. Como Usar - GUI (App)](#7-como-usar---gui-app)
- [8. Como Gerar e Usar o EXE](#8-como-gerar-e-usar-o-exe)
- [9. Pasta Temp](#9-pasta-temp)
- [10. Variaveis de Ambiente](#10-variaveis-de-ambiente)
- [11. Fluxo Recomendado de Operacao](#11-fluxo-recomendado-de-operacao)
- [12. Estrutura de Pastas](#12-estrutura-de-pastas)
- [13. Qualidade, Limites e Boas Praticas](#13-qualidade-limites-e-boas-praticas)
- [14. Documentacao Complementar](#14-documentacao-complementar)

## 1. Escopo Cientifico

BirdNET gera inferencias automaticas sobre especies a partir de gravações ambientais. Esse processo possui incerteza estatistica e ruido operacional. O objetivo deste projeto e organizar o envio de:

- segmentos de audio (evidencia primaria);
- deteccoes em CSV (metadado derivado);
- indice/manifests auxiliares para auditoria.

Ao centralizar esses dados em um dataset Hugging Face, voce habilita um fluxo de validacao humana posterior, com reproducibilidade e rastreabilidade.

## 2. O que Este Projeto Resolve

- padroniza uploads de grandes lotes de segmentos;
- permite retomar sessoes interrompidas;
- oferece deduplicacao e organizacao por estrutura remota;
- suporta dois modos de operacao:
	- CLI para automacao;
	- GUI para operacao assistida.

## 3. Arquitetura do Repositorio

O repositorio contem dois projetos isolados:

- `hf_upload_script`: CLI standalone para execucao por terminal, scripts e pipelines.
- `hf_upload_app`: aplicacao com interface Gradio e opcao de empacotamento em executavel.

Importante: os dois projetos possuem base de codigo semelhante, mas sao independentes em entrada/execucao.

## 4. Requisitos de Ambiente

- Python 3.10+
- Conta Hugging Face com permissao para criar/escrever datasets
- Token HF (recomendado com escopo minimo necessario)
- Conexao de rede estavel para upload de arquivos grandes

Opcional:

- PyInstaller (para gerar executavel)

## 5. Instalacao Rapida

### 5.1 CLI (hf_upload_script)

```bash
cd hf_upload_script
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5.2 GUI/EXE (hf_upload_app)

```bash
cd hf_upload_app
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 6. Como Usar - CLI (Script)

No diretorio `hf_upload_script`:

### 6.1 Ver comandos disponiveis

```bash
python app.py --help
```

### 6.2 Autenticacao

```bash
python app.py login
```

### 6.3 Criar dataset

```bash
python app.py init-repo --repo-id usuario/nome-do-dataset --private
```

### 6.4 Fazer scan local

```bash
python app.py scan --segments "C:/dados/segments"
```

### 6.5 Iniciar sessao resumivel

```bash
python app.py start --repo-id usuario/nome-do-dataset --segments "C:/dados/segments"
```

### 6.6 Upload completo (audio + CSV opcional)

```bash
python app.py upload \
	--repo-id usuario/nome-do-dataset \
	--segments "C:/dados/segments" \
	--csv "C:/dados/detections.csv" \
	--remote-base audio \
	--workers 4 \
	--upload-mode direct
```

### 6.7 Dry run (sem enviar)

```bash
python app.py upload --repo-id usuario/nome-do-dataset --segments "C:/dados/segments" --dry-run
```

## 7. Como Usar - GUI (App)

No diretorio `hf_upload_app`:

```bash
python app.py
```

Fluxo na interface:

1. informar token Hugging Face;
2. informar `owner/dataset`;
3. enviar audio (ou arquivo `.tar`, `.tar.gz`, `.zip`);
4. opcionalmente enviar CSV de deteccoes;
5. configurar workers e iniciar upload.

A GUI foi desenhada para uso interativo e suporta progress tracking durante a subida.

## 8. Como Gerar e Usar o EXE

No diretorio `hf_upload_app`:

```bash
python -m pip install pyinstaller
pyinstaller hf_upload_app.spec --noconfirm
```

Saida esperada:

- executavel na pasta `dist/` (gerada pelo PyInstaller).

Uso do EXE:

1. copiar pasta final para maquina de destino;
2. executar binario;
3. operar via mesma interface GUI.

## 9. Pasta Temp
Use `Temp/` na raiz para arquivos temporarios gerais.
Cada subprojeto tambem possui sua propria pasta `Temp/`.

## 10. Variaveis de Ambiente

Variaveis suportadas pelo codigo atual:

- `HF_TOKEN`: token para autenticacao sem prompt.
- `BIRDNET_UPLOADER_CLI`: no app, força modo CLI (`1`, `true`, `yes`).
- `PORT` ou `BIRDNET_UPLOADER_PORT`: porta da GUI.
- `BIRDNET_UPLOADER_HOST`: host de bind da GUI (padrao `0.0.0.0`).
- `BIRDNET_UPLOADER_DATA_DIR`: raiz para sessao/cache/log.
- `BIRDNET_UPLOADER_SESSION_DIR`: override de sessoes.
- `BIRDNET_UPLOADER_CACHE_DIR`: override de cache.
- `BIRDNET_UPLOADER_LOG_DIR`: override de logs.

Tunings de rede/upload:

- `BNU_REPO_CREATE_ATTEMPTS`
- `BNU_REPO_CREATE_BACKOFF`
- `BNU_HUB_UPLOAD_ATTEMPTS`
- `BNU_HUB_UPLOAD_TIMEOUT`
- `BNU_HUB_UPLOAD_BACKOFF`
- `BNU_FOLDER_UPLOAD_TIMEOUT`

## 11. Fluxo Recomendado de Operacao

1. gerar segmentos e deteccoes no pipeline BirdNET;
2. revisar estrutura local de arquivos;
3. executar dry-run para validar lote;
4. fazer upload de audio + CSV;
5. validar dataset remoto;
6. encaminhar dataset para etapa de validacao colaborativa.

## 12. Estrutura de Pastas

```text
HF_Dataset_Uploader/
├─ hf_upload_script/    # CLI standalone
├─ hf_upload_app/       # GUI + build executavel
├─ Temp/                # temporarios de repositorio
└─ README.md
```

## 13. Qualidade, Limites e Boas Praticas

- prefira nomes de arquivo estaveis e consistentes;
- valide encoding e delimitadores do CSV antes do upload;
- use `--dry-run` em lotes grandes;
- use sessao resumivel para robustez operacional;
- mantenha token fora de logs e scripts versionados.

## 14. Documentacao Complementar

- `hf_upload_script/README.md`: operacao detalhada do CLI.
- `hf_upload_app/README.md`: operacao GUI e empacotamento.
- `docs/SCIENTIFIC_SCOPE.md`: fundamentacao de escopo cientifico.
- `docs/OPERATIONS_GUIDE.md`: guia operacional completo por cenario.
- `docs/ARCHITECTURE.md`: componentes internos e fluxo tecnico.
- `docs/TROUBLESHOOTING.md`: diagnostico e resolucao de problemas.
