# BirdNET Uploader: Redesign CLI Moderno

## Visão Geral

Executável local moderno com **um único fluxo integrado**: login → criar repositório → apontar pasta → fazer upload.

Interface limpa, baseada em TUI (Textual) ou rich terminal output, compatível com a estrutura esperada pelo BirdNET Validator.

---

## 1. FLUXO DE UX ÚNICO INTEGRADO

### Tela 1: Autenticação
```
┌─────────────────────────────────────────────────┐
│  BirdNET Uploader                               │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                 │
│  🐦  Autentique-se no Hugging Face             │
│                                                 │
│  [i] Cole seu token HF (Settings → Access     │
│      Tokens em huggingface.co)                 │
│                                                 │
│  Token: [●●●●●●●●●●●●●●●●●●●●●●]             │
│                                                 │
│         [ Continuar ] [ Sair ]                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Tela 2: Configuração (Um formulário integrado)
```
┌─────────────────────────────────────────────────┐
│  BirdNET Uploader - Configuração                │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                 │
│  Conectado como: alice@example.com             │
│                                                 │
│  REPOSITÓRIO                                    │
│  Nome do repo:     [my-birds-2026    ]          │
│  Visibilidade:     ( ) Público   (●) Privado   │
│                                                 │
│  ARQUIVOS                                       │
│  Pasta segmentos:  [C:\audio\segments]          │
│  Arquivo CSV:      [C:\audio\metadata.csv] (opt)
│  [ Verificar ]                                  │
│  ✓ 1.247 arquivos encontrados                  │
│  ✓ Tamanho total: 53 GB                        │
│  ✓ CSV compatível: 1.200 linhas                │
│                                                 │
│         [ Criar Repo e Fazer Upload ]          │
│         [ Voltar ]                             │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Tela 3: Resumo e Confirmação
```
┌─────────────────────────────────────────────────┐
│  Pronto para Começar                            │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                 │
│  Repositório: alice/my-birds-2026               │
│  Visibilidade: Privado                          │
│  URL: https://huggingface.co/datasets/alice/..  │
│                                                 │
│  Origem:                                        │
│    Pasta: C:\audio\segments                     │
│    Arquivos: 1.247                              │
│    Tamanho: 53 GB                               │
│    CSV: metadata.csv (1.200 linhas)             │
│                                                 │
│  Duração estimada: ~4 horas (com conexão 10MB/s)
│                                                 │
│  [ Iniciar Upload ]  [ Cancelar ]               │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Tela 4: Upload em Andamento
```
┌─────────────────────────────────────────────────┐
│  Upload em Andamento                            │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                 │
│  Progresso Global                               │
│  ████████████████░░░░░░░░░░░░░░  62.3%          │
│                                                 │
│  Arquivos: 775/1.247 (skipped: 18, erro: 2)   │
│  Dados: 33 GB / 53 GB                           │
│  Velocidade: 9.6 MB/s | ETA: 01h 15m            │
│                                                 │
│  Arquivo Atual: Parrot_Ara_001.wav              │
│  ████████████░░░░░░░░░░░░░░░░░░░  45.2%        │
│  3.2 / 7.1 MB                                   │
│                                                 │
│  Último evento: ✓ Thrush_042.wav enviado (2s)  │
│                                                 │
│  [ Pausar ]  [ Cancelar ]  [ Detalhes ]         │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Tela 5: Resumo Final
```
┌─────────────────────────────────────────────────┐
│  ✓ Upload Concluído!                            │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                 │
│  Repositório: alice/my-birds-2026               │
│  URL: https://huggingface.co/datasets/alice/..  │
│                                                 │
│  Resumo:                                        │
│    ✓ Enviados: 1.227 arquivos                  │
│    → Pulados: 18 (já existiam)                  │
│    ✗ Erros: 2 (revisar detalhes)               │
│    ⏱  Tempo total: 4h 23min                     │
│    📊 Velocidade média: 9.8 MB/s                │
│                                                 │
│  Próximos passos:                               │
│    1. Validar dados com BirdNET Validator      │
│    2. Verificar relatório de ingestão          │
│                                                 │
│  Relatório salvo em: ~/.birdnet-uploader/      │
│                      sessions/upload-xxx/      │
│                      report.json                │
│                                                 │
│  [ Ver Relatório Completo ]  [ Sair ]           │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## 2. ARQUITETURA LIMPA E MODULAR

### Estrutura de Diretórios do Projeto

```
birdnet-uploader/
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entrypoint principal
│   ├── config.py                  # Config app e constantes
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── auth_service.py        # Login, token, keyring
│   │   └── token_manager.py       # Gerenciamento de token
│   ├── repository/
│   │   ├── __init__.py
│   │   ├── repo_service.py        # Criar/validar dataset HF
│   │   └── structure_initializer.py # Init estrutura padrão
│   ├── upload/
│   │   ├── __init__.py
│   │   ├── scanner.py             # Varrer pasta local
│   │   ├── uploader.py            # Motor de upload por lotes
│   │   ├── deduplicator.py        # Checagem de duplicação
│   │   └── batch_processor.py     # Processamento de lotes
│   ├── csv/
│   │   ├── __init__.py
│   │   ├── csv_matcher.py         # Matching CSV + segmentos
│   │   └── indexer.py             # Geração de índice/shards
│   ├── session/
│   │   ├── __init__.py
│   │   ├── session_manager.py     # Gerenciamento de sessão
│   │   ├── checkpoint.py          # Persistência de checkpoint
│   │   └── state_store.py         # State file I/O
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── tui.py                 # Interface Textual (TUI)
│   │   ├── progress_renderer.py   # Barra de progresso rich
│   │   └── prompts.py             # Diálogos e inputs
│   ├── logger/
│   │   ├── __init__.py
│   │   ├── structured_logger.py   # Logs estruturados JSONL
│   │   └── telemetry.py           # Eventos de telemetria
│   └── utils/
│       ├── __init__.py
│       ├── file_utils.py          # Operações de arquivo
│       ├── hash_utils.py          # Computação de hash
│       └── error_handler.py       # Tratamento de erros
├── build/
│   ├── pyinstaller_config.spec    # Config do PyInstaller
│   └── build.py                   # Script de build
├── tests/
│   ├── __init__.py
│   ├── test_auth.py
│   ├── test_uploader.py
│   ├── test_session.py
│   └── test_csv_matcher.py
├── README.md
├── requirements.txt
└── setup.py
```

### Dependências Principais

```
# requirements.txt
huggingface_hub>=0.28.0          # HF Hub API
click>=8.0.0                      # CLI framework
textual>=0.30.0                   # TUI moderna
rich>=13.0.0                      # Terminal formatting
pydantic>=2.0.0                   # Validação de dados
pandas>=2.0.0                     # CSV parsing
pyarrow>=14.0.0                   # Parquet para shards
keyring>=24.0.0                   # Armazenamento seguro
cryptography>=41.0.0              # Criptografia local
```

---

## 3. COMPATIBILIDADE COM ESTRUTURA DO VALIDADOR

### Estrutura Esperada do Dataset

```
dataset_repo_id = "username/project-dataset"

audio/
├── {project_slug}/
│   ├── Specie_A/
│   │   ├── segment_001.wav
│   │   ├── segment_002.wav
│   │   └── ...
│   ├── Specie_B/
│   │   └── ...
│   └── ...

index/
├── shards/
│   ├── shard-00000.parquet
│   ├── shard-00001.parquet
│   └── ...
└── manifest.json

validations/
├── results-20250419.parquet

audit/
├── ingestion-runs/
│   └── 20250419T100000Z.json
```

### Manifest Format (Mantém compatibilidade)

```json
{
  "schema_version": "1.0.0",
  "project_slug": "my-birds",
  "dataset_repo_id": "alice/my-birds-2026",
  "updated_at": "2025-04-19T10:45:30Z",
  "index": {
    "total_detections": 1227,
    "total_audio_files": 1227,
    "shard_size": 10000,
    "shards": [
      {
        "path": "index/shards/shard-00000.parquet",
        "rows": 10000,
        "sha256": "abc123...",
        "size_bytes": 5242880
      }
    ]
  }
}
```

---

## 4. MÓDULO POR MÓDULO

### 4.1 Auth Service (`src/auth/auth_service.py`)

```python
from keyring import get_password, set_password
from huggingface_hub import HfApi, login

class AuthService:
    KEYRING_SERVICE = "birdnet-uploader"
    
    def authenticate(self, token: str) -> dict:
        """Valida token e retorna context do usuário."""
        try:
            api = HfApi(token=token)
            user_info = api.whoami()
            
            # Salvar em keyring seguro
            set_password(self.KEYRING_SERVICE, "hf_token", token)
            
            return {
                "username": user_info["name"],
                "email": user_info.get("email", ""),
                "user_id": user_info["user_id"],
                "token_expiry": self._estimate_expiry()
            }
        except Exception as e:
            raise AuthenticationError(f"Token inválido: {str(e)}")
    
    def get_token(self) -> str:
        """Recupera token do keyring."""
        token = get_password(self.KEYRING_SERVICE, "hf_token")
        if not token:
            raise TokenNotFoundError("Token não encontrado. Execute 'birdnet auth login'")
        return token
```

### 4.2 Repository Service (`src/repository/repo_service.py`)

```python
class RepositoryService:
    def create_dataset(self, 
                       repo_name: str, 
                       private: bool = True) -> str:
        """Cria dataset no HF com estrutura padrão."""
        api = HfApi(token=self.get_token())
        
        repo_id = f"{username}/{repo_name}"
        
        # Criar repo
        repo = api.create_repo(
            repo_id=repo_id,
            repo_type="dataset",
            private=private,
            exist_ok=True
        )
        
        # Inicializar estrutura padrão
        self._init_structure(repo_id)
        
        return repo_id
    
    def _init_structure(self, repo_id: str):
        """Inicializa pastas e arquivos padrão."""
        folders = [
            "audio/{project_slug}",
            "index/shards",
            "validations",
            "audit/ingestion-runs"
        ]
        
        for folder in folders:
            # Criar .gitkeep
            api.upload_file(
                path_or_fileobj=BytesIO(b""),
                path_in_repo=f"{folder}/.gitkeep",
                repo_id=repo_id,
                repo_type="dataset"
            )
        
        # Criar manifest.json inicial
        manifest = {
            "schema_version": "1.0.0",
            "project_slug": project_slug,
            "dataset_repo_id": repo_id,
            "index": {
                "total_detections": 0,
                "total_audio_files": 0,
                "shard_size": 10000,
                "shards": []
            }
        }
        
        api.upload_file(
            path_or_fileobj=BytesIO(json.dumps(manifest).encode()),
            path_in_repo="index/manifest.json",
            repo_id=repo_id,
            repo_type="dataset"
        )
```

### 4.3 Scanner (`src/upload/scanner.py`)

```python
class LocalScanner:
    def scan_folder(self, folder_path: str) -> dict:
        """Varre pasta recursiva e retorna estrutura."""
        structure = {}
        total_size = 0
        file_count = 0
        
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(('.wav', '.mp3', '.flac', '.ogg')):
                    full_path = os.path.join(root, file)
                    
                    # Inferir espécie do caminho ou nome
                    specie = self._infer_specie(root, file)
                    
                    if specie not in structure:
                        structure[specie] = []
                    
                    size = os.path.getsize(full_path)
                    structure[specie].append({
                        "name": file,
                        "full_path": full_path,
                        "size": size,
                        "local_hash": compute_hash(full_path)
                    })
                    
                    total_size += size
                    file_count += 1
        
        return {
            "total_files": file_count,
            "total_size": total_size,
            "by_specie": structure,
            "scan_timestamp": datetime.now()
        }
    
    def _infer_specie(self, root: str, file: str) -> str:
        """Inferir espécie do caminho da pasta."""
        # Estratégia 1: última pasta em root é a espécie
        parts = root.split(os.sep)
        if len(parts) > 0:
            return parts[-1]
        
        # Fallback: usar nome do arquivo
        return file.replace(".wav", "").split("_")[0]
```

### 4.4 Uploader (`src/upload/uploader.py`)

```python
class BatchUploader:
    def __init__(self, repo_id: str, project_slug: str, token: str):
        self.repo_id = repo_id
        self.project_slug = project_slug
        self.api = HfApi(token=token)
        self.session = SessionManager(repo_id)
    
    async def upload_files(self, 
                           structure: dict,
                           csv_matcher: Optional[CSVMatcher] = None,
                           batch_size: int = 10,
                           on_progress: Optional[Callable] = None) -> dict:
        """Upload em lotes com retomada."""
        checkpoint = self.session.load_checkpoint()
        
        results = {
            "total": 0,
            "uploaded": 0,
            "skipped": 0,
            "failed": 0,
            "errors": []
        }
        
        for specie, files in structure["by_specie"].items():
            # Processar em lotes
            for i in range(0, len(files), batch_size):
                batch = files[i:i + batch_size]
                
                # Verificar checkpoint
                if self.session.is_batch_done(specie, i):
                    results["skipped"] += len(batch)
                    continue
                
                # Enviar batch
                for file_info in batch:
                    try:
                        if self._should_skip(file_info):
                            results["skipped"] += 1
                            self.session.mark_skipped(file_info)
                            continue
                        
                        remote_path = f"audio/{self.project_slug}/{specie}/{file_info['name']}"
                        
                        await self._upload_file_with_retry(
                            file_info["full_path"],
                            remote_path
                        )
                        
                        results["uploaded"] += 1
                        self.session.mark_done(file_info)
                        
                        if on_progress:
                            on_progress({
                                "total": structure["total_files"],
                                "uploaded": results["uploaded"],
                                "skipped": results["skipped"],
                                "failed": results["failed"],
                                "current_file": file_info["name"],
                                "current_size": file_info["size"]
                            })
                    
                    except Exception as e:
                        results["failed"] += 1
                        results["errors"].append({
                            "file": file_info["name"],
                            "error": str(e)
                        })
                        self.session.mark_failed(file_info)
                
                # Checkpoint por batch
                self.session.save_checkpoint()
        
        return results
    
    async def _upload_file_with_retry(self, 
                                       local_path: str, 
                                       remote_path: str,
                                       max_retries: int = 3):
        """Upload com retries e backoff exponencial."""
        for attempt in range(max_retries):
            try:
                self.api.upload_file(
                    path_or_fileobj=local_path,
                    path_in_repo=remote_path,
                    repo_id=self.repo_id,
                    repo_type="dataset"
                )
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    await asyncio.sleep(wait_time)
                else:
                    raise
    
    def _should_skip(self, file_info: dict) -> bool:
        """Verifica se arquivo já existe remotamente."""
        try:
            remote_path = f"audio/{self.project_slug}/{specie}/{file_info['name']}"
            file_info_remote = self.api.get_file_info(
                repo_id=self.repo_id,
                filename=remote_path
            )
            return file_info_remote.size == file_info["size"]
        except:
            return False
```

### 4.5 Session Manager (`src/session/session_manager.py`)

```python
class SessionManager:
    def __init__(self, repo_id: str):
        self.session_id = f"upload-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.session_dir = Path(f"~/.birdnet-uploader/sessions/{self.session_id}")
        self.session_dir.mkdir(parents=True, exist_ok=True)
    
    def save_checkpoint(self, data: dict):
        """Salva checkpoint atomicamente."""
        checkpoint_file = self.session_dir / "checkpoint.json"
        temp_file = checkpoint_file.with_suffix(".tmp")
        
        temp_file.write_text(json.dumps(data, indent=2))
        temp_file.replace(checkpoint_file)
    
    def load_checkpoint(self) -> dict:
        """Carrega último checkpoint."""
        checkpoint_file = self.session_dir / "checkpoint.json"
        if checkpoint_file.exists():
            return json.loads(checkpoint_file.read_text())
        return {}
```

### 4.6 CSV Matcher (`src/csv/csv_matcher.py`)

```python
class CSVMatcher:
    def match_and_generate_index(self,
                                 csv_path: str,
                                 files_structure: dict) -> pd.DataFrame:
        """Faz matching entre CSV e segmentos, gera índice."""
        df = pd.read_csv(csv_path)
        
        # Validar colunas esperadas
        required_cols = ["source_file", "scientific_name", "confidence", 
                        "start_time", "end_time"]
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV deve conter colunas: {required_cols}")
        
        # Matching lógica
        matched = []
        for _, row in df.iterrows():
            source_stem = Path(row["source_file"]).stem
            
            # Procurar arquivo correspondente
            for specie, files in files_structure["by_specie"].items():
                for file_info in files:
                    if source_stem in file_info["name"]:
                        matched.append({
                            **row,
                            "segment_path": f"audio/{self.project_slug}/{specie}/{file_info['name']}"
                        })
        
        return pd.DataFrame(matched)
    
    def generate_shards(self,
                       index_df: pd.DataFrame,
                       output_dir: str,
                       shard_size: int = 10000) -> list:
        """Gera shards parquet para índice."""
        shards = []
        
        for i in range(0, len(index_df), shard_size):
            shard_df = index_df.iloc[i:i+shard_size]
            shard_file = f"{output_dir}/shard-{i//shard_size:05d}.parquet"
            
            shard_df.to_parquet(shard_file, index=False)
            shards.append(shard_file)
        
        return shards
```

---

## 5. FLUXO DE COMANDOS CLI

```bash
# Autenticar
$ birdnet auth login
> Enter HF token: hf_...

# Upload simples (interactive)
$ birdnet upload

# Upload com flags (não-interativo)
$ birdnet upload \
    --repo alice/my-birds \
    --segments /path/to/segments \
    --csv /path/to/metadata.csv \
    --private

# Listar sessões
$ birdnet sessions list

# Retomar sessão
$ birdnet upload resume <session-id>

# Ver status
$ birdnet upload status <session-id>

# Exportar relatório
$ birdnet upload report <session-id>
```

---

## 6. CRITÉRIOS DE ACEITE DO MVP

- [ ] Usuário baixa executável portátil, sem Python pré-instalado
- [ ] Login com token HF funciona e não vaza em logs
- [ ] Criar dataset público/privado com estrutura padrão
- [ ] Varrer pasta local corretamente (recursivo, agrupa por espécie)
- [ ] Upload de 50GB+ com progresso contínuo e ETA coerente
- [ ] Pausar/fechar app/retomar sem duplicar upload
- [ ] Queda de rede + 429 recuperam com retries
- [ ] CSV opcional com matching integrado
- [ ] Relatório final estruturado (JSONL/JSON)
- [ ] Estrutura de arquivos compatível com validador
- [ ] Compatibilidade 100% com manifest/index esperado
- [ ] Sem regressão do fluxo atual do Space

---

## 7. PRÓXIMOS PASSOS

1. **Implementar módulos base** (Auth, Repo, Scanner, Uploader)
2. **Construir UI** (Textual TUI ou Rich + Click)
3. **Integrar Session Manager** e Checkpoint
4. **Testes de integração** (50GB+, retomada, rede)
5. **Construir executável** (PyInstaller)
6. **Validação end-to-end** com usuários reais
