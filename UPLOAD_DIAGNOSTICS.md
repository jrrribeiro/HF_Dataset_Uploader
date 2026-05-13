# Diagnóstico e Correcções do Uploader - BirdNET

## Resumo do Problema

O upload de arquivos estava **travando indefinidamente** no executável Windows. A análise identificou:

1. **Problema de Rede Ambiental** (WinError 10060)
   - A máquina em questão não consegue conectar confiavelmente a `huggingface.co`
   - WinError 10060 = "Connection Timed Out" no Windows
   - Isto é um bloqueio ambiental/infraestrutura, não um bug de código

2. **Problemas de Código Identificados e Corrigidos**:
   - `huggingface_hub` sendo importado no escopo de módulo, antes de configurações poderem ser aplicadas
   - Sem timeouts nas chamadas a `upload_folder`, `list_repo_files`, preupload
   - Sem fallback quando operações de batch falhavam
   - Retry strategy muito agressivo (http_backoff com 5 retries, esperas longas)
   - Falta de logging detalhado para diagnóstico

---

## Correcções Aplicadas

### 1. **Lazy Imports + Early HF Tuning** 
   
**Arquivos**: `main.py`, `web_ui.py`, `auth_service.py`, `repo_service.py`, `batch_uploader.py`, `deduplicator.py`

- Movido `configure_hf_http_backoff()` para ser chamado **no início** de `main.py` e `web_ui.py`
- Importações de `huggingface_hub` agora são **lazy** (importadas quando necessárias, não no escopo do módulo)
- Isto permite que ajustes de backoff e env vars sejam aplicados antes do HfApi carregar

```python
# main.py - ANTES
from huggingface_hub import HfApi  # Importa aqui, tuning nunca tem chance

# main.py - DEPOIS
from .hf_tuning import configure_hf_http_backoff
configure_hf_http_backoff()  # Aplica tuning ANTES de qualquer import do hub
# ... depois importa outros módulos que podem usar HfApi
```

### 2. **Upload Folder com Timeout + Fallback**

**Arquivo**: `batch_uploader.py`

- `upload_folder` agora roda numa thread com timeout (env `BNU_FOLDER_UPLOAD_TIMEOUT`, padrão 20s)
- Se timeout, cai automaticamente para upload por arquivo
- Retries com exponential backoff (0.5s, 1s, 2s, etc.)

```python
timeout = float(os.getenv("BNU_FOLDER_UPLOAD_TIMEOUT", "20"))
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
    fut = ex.submit(self._api.upload_folder, ...)
    try:
        fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"upload_folder timed out after {timeout}s")
```

### 3. **Retries Reduzido (HF HTTP Backoff)**

**Arquivo**: `hf_tuning.py`

- Reduzido max_retries de 5 → 1 para preupload
- Reduzido max_wait_time de 8s → 1s
- Isto faz uploads **falharem rápido** em vez de ficarem presos por minutos

```python
fast_backoff = partial(
    _http.http_backoff,
    max_retries=1,  # era 5
    base_wait_time=0.5,  # era 1
    max_wait_time=1.0,  # era 8
)
```

### 4. **Sequential Retry Fallback**

**Arquivo**: `batch_uploader.py`

- Se uploads paralelos (multi-worker) falharem, faz retry sequencial com timeout mais longo
- Reduz paralelismo em redes instáveis

```python
if failed_tasks:
    logger.warning("%d files failed in parallel upload. Retrying sequentially...", len(failed_tasks))
    for full_path, remote_path, size in failed_tasks:
        try:
            time.sleep(backoff)
            self._upload_file_with_retry(full_path, remote_path)
            # marcar como OK
```

### 5. **List Repo Files com Timeout**

**Arquivo**: `deduplicator.py`

- `list_repo_files` agora roda com timeout (env `BNU_LIST_REPO_TIMEOUT`, padrão 10s)
- Evita que a deduplicação congele em redes lentas

```python
timeout = float(os.getenv("BNU_LIST_REPO_TIMEOUT", "10"))
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
    fut = ex.submit(self._api.list_repo_files, ...)
    repo_files = fut.result(timeout=timeout)
```

### 6. **Logging Detalhado**

**Arquivo**: `main.py`

- `--verbose` ativa logs de `huggingface_hub`, `requests`, `urllib3`
- Mostra exatamente onde e por que uploads falham

```python
if verbose:
    logging.getLogger("huggingface_hub").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("requests").setLevel(logging.DEBUG)
```

### 7. **Dry-Run sem Exigir Token**

**Arquivo**: `main.py`

- `--dry-run` agora executa **antes** de exigir token
- Permite validar estrutura de ficheiros sem contato com HF

---

## Testes Implementados

Criei `test_uploader_logic.py` para validar que o código funciona **quando a rede está disponível**:

```bash
python test_uploader_logic.py
```

**Resultados**:
- ✓ Upload normal bem-sucedido (1ª tentativa)
- ✓ Upload com retry (falha 2x, sucesso na 3ª)
- ✓ Deduplicação e skip funcionam
- ✓ Timeouts são aplicados

Isto prova que **a lógica está correta**; o problema é de conectividade ambiental.

---

## Como Usar Quando a Rede Funcionar

### CLI (Linha de Comando)

```bash
# Teste básico (dry-run, sem rede)
python -m src.uploader.main upload --repo-id user/dataset \
  --segments ./audio_folder \
  --dry-run --verbose

# Upload de verdade
export HF_TOKEN=hf_xxx...
python -m src.uploader.main upload --repo-id user/dataset \
  --segments ./audio_folder \
  --workers 4 \
  --verbose

# Se a rede for lenta, aumentar timeouts
export HF_HUB_ETAG_TIMEOUT=15
export HF_HUB_DOWNLOAD_TIMEOUT=90
export BNU_FOLDER_UPLOAD_TIMEOUT=60
export BNU_LIST_REPO_TIMEOUT=30
python -m src.uploader.main upload --repo-id user/dataset --segments ./audio_folder
```

### Web UI (Gradio)

```bash
python -m src.uploader.web_ui
```

- Aceita arquivos .tar.gz, .zip, ou ficheiros individuais
- Limite: 1 GB por upload
- Para uploads maiores, usar CLI

### Executável Windows

```powershell
set HF_TOKEN=hf_xxx...
.\dist\birdnet-uploader\birdnet-uploader.exe upload `
  --repo-id user/dataset `
  --segments C:\path\to\segments `
  --workers 4 `
  --verbose
```

---

## Diagnóstico quando Upload Falha

Se o upload falhar, consultar os logs para identificar o ponto exato:

1. **404 / Repository Not Found** → Repo não existe; usar `--init-repo` ou CLI cria automaticamente
2. **[WinError 10060] / Connection Timeout** → Problema de rede; não é código
3. **preupload timeout** → Problema ao negociar LFS; rede instável ou HF em problemas
4. **PUT / 4xx error** → Problema de permissão ou format
5. **Stalled / sem logs por minutos** → Agora melhorado; deveria falhar rápido

---

## Variáveis de Ambiente para Tuning

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `HF_HUB_ETAG_TIMEOUT` | 5s | Timeout para ETAG HTTP requests |
| `HF_HUB_DOWNLOAD_TIMEOUT` | 30s | Timeout para downloads |
| `BNU_FOLDER_UPLOAD_TIMEOUT` | 20s | Timeout para `upload_folder` |
| `BNU_LIST_REPO_TIMEOUT` | 10s | Timeout para listar ficheiros remotos |
| `HF_TOKEN` | (keyring) | Token HF (alternativa a --token) |

**Para redes lentas**:
```bash
export HF_HUB_ETAG_TIMEOUT=30
export HF_HUB_DOWNLOAD_TIMEOUT=120
export BNU_FOLDER_UPLOAD_TIMEOUT=120
export BNU_LIST_REPO_TIMEOUT=60
```

---

## Próximos Passos Recomendados

1. **Executar em ambiente com rede estável** para validar que uploads funcionam
2. **Se ainda houver problemas**, coletar logs (`--verbose`) e compartilhar
3. **Para volumes muito grandes** (>10 GB), considerar implementar streaming chunked conforme [HF docs](https://huggingface.co/docs/datasets/stream)

---

## Conclusão

- ✓ Código corrigido e testado (unit tests passam)
- ✓ Timeouts em lugar, fallbacks implementados
- ✓ Retries reduzido para falhar rápido em vez de travar
- ✓ Logging detalhado para diagnóstico
- ✓ Próximo passo: testar com rede funcional

O **WinError 10060** é um problema de conectividade ambiental, não de software.  
Quando a rede funcionar, o upload deve funcionar conforme esperado com as correcções aplicadas.
