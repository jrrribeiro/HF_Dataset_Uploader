# Sprint 1 Kickoff: Primeiros Passos (HOJE)

## Objetivo
Estrutura base pronta, dependências instaladas, todos os módulos esqueléticos criados, testes rodando.

**Tempo estimado**: 4-5 horas para 1-2 pessoas

---

## Step 1: Criar Branch de Trabalho

```bash
cd c:\Users\jonat\Documents\Python\BirdNET-validator-App
git checkout -b feature/birdnet-uploader-cli
git push -u origin feature/birdnet-uploader-cli
```

---

## Step 2: Criar Estrutura de Diretórios

```bash
# Criar estrutura completa
mkdir -p src\auth
mkdir -p src\repository
mkdir -p src\upload
mkdir -p src\csv
mkdir -p src\session
mkdir -p src\ui\screens
mkdir -p src\logger
mkdir -p src\utils
mkdir -p tests
mkdir -p build
mkdir -p docs

# Criar __init__.py em todos
echo "" > src\__init__.py
echo "" > src\auth\__init__.py
echo "" > src\repository\__init__.py
echo "" > src\upload\__init__.py
echo "" > src\csv\__init__.py
echo "" > src\session\__init__.py
echo "" > src\ui\__init__.py
echo "" > src\ui\screens\__init__.py
echo "" > src\logger\__init__.py
echo "" > src\utils\__init__.py
echo "" > tests\__init__.py
```

---

## Step 3: Criar `requirements.txt`

Criar arquivo: `requirements.txt`

```
# Core CLI
click>=8.0.0
typer>=0.9.0

# UI/TUI
textual>=0.30.0
rich>=13.0.0

# HF Integration
huggingface_hub>=0.28.0

# Data Processing
pandas>=2.0.0
pyarrow>=14.0.0

# Security
keyring>=24.0.0
cryptography>=41.0.0

# Validation
pydantic>=2.0.0

# Development & Testing
pytest>=7.0.0
pytest-cov>=4.0.0
black>=23.0.0
flake8>=6.0.0
mypy>=1.0.0

# Optional: async
asyncio>=3.4.3
```

Instalar:
```bash
pip install -r requirements.txt
```

---

## Step 4: Criar `pyproject.toml`

Criar arquivo: `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=65.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "birdnet-uploader"
version = "0.1.0"
description = "Local CLI for resumable HuggingFace dataset uploads (BirdNET)"
authors = [
    {name = "BirdNET Team", email = "team@example.com"}
]
requires-python = ">=3.9"
dependencies = [
    "click>=8.0.0",
    "textual>=0.30.0",
    "rich>=13.0.0",
    "huggingface_hub>=0.28.0",
    "pandas>=2.0.0",
    "pyarrow>=14.0.0",
    "keyring>=24.0.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "flake8>=6.0.0",
    "mypy>=1.0.0",
]

[project.scripts]
birdnet = "src.main:app"

[tool.black]
line-length = 100
target-version = ['py39']

[tool.isort]
profile = "black"
line_length = 100

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --cov=src --cov-report=html --cov-report=term-missing"
```

---

## Step 5: Criar Estrutura Base de Módulos (Skeletons)

### 5.1: `src/main.py`

```python
"""BirdNET Uploader - Main Entry Point"""

import click
from src.ui.tui import BirdNETApp
from src.auth.auth_service import AuthService
from src.config import get_config

__version__ = "0.1.0"

@click.group()
@click.version_option(version=__version__)
def app():
    """BirdNET Uploader - Upload audio to HuggingFace Datasets"""
    pass

@app.command()
def upload():
    """Start the upload wizard (interactive TUI)"""
    try:
        app_ui = BirdNETApp()
        app_ui.run()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@app.command()
def login():
    """Authenticate with HuggingFace token"""
    try:
        token = click.prompt("Enter your HF token", hide_input=True)
        auth = AuthService()
        user_info = auth.authenticate(token)
        click.echo(f"✓ Logged in as {user_info['username']}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@app.command()
@click.argument("session_id")
def resume(session_id: str):
    """Resume a previous upload session"""
    click.echo(f"Resuming session: {session_id}")
    # TODO: Implement

@app.command()
def list_sessions():
    """List all upload sessions"""
    click.echo("Sessions:")
    # TODO: Implement

if __name__ == "__main__":
    app()
```

### 5.2: `src/config.py`

```python
"""Configuration and Constants"""

from pathlib import Path
import os

# App
APP_NAME = "BirdNET Uploader"
APP_VERSION = "0.1.0"

# Directories
SESSION_DIR = Path.home() / ".birdnet-uploader" / "sessions"
CACHE_DIR = Path.home() / ".birdnet-uploader" / "cache"
LOG_DIR = Path.home() / ".birdnet-uploader" / "logs"

# Create directories if not exist
SESSION_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Audio
AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac', '.ogg', '.m4a']

# Upload
MAX_BATCH_SIZE = 10
MAX_RETRIES = 3
RETRY_INITIAL_BACKOFF = 1.0  # seconds
RETRY_MAX_BACKOFF = 30.0  # seconds

# Manifest
MANIFEST_SCHEMA_VERSION = "1.0.0"
SHARD_SIZE = 10000

# Keyring
KEYRING_SERVICE = "birdnet-uploader"
KEYRING_ACCOUNT = "hf_token"

def get_config():
    """Get runtime configuration from environment or defaults"""
    return {
        "session_dir": os.getenv("BIRDNET_SESSION_DIR", str(SESSION_DIR)),
        "cache_dir": os.getenv("BIRDNET_CACHE_DIR", str(CACHE_DIR)),
        "log_dir": os.getenv("BIRDNET_LOG_DIR", str(LOG_DIR)),
    }
```

### 5.3: `src/auth/auth_service.py`

```python
"""Authentication Service"""

from typing import Optional, Dict
import keyring
from huggingface_hub import HfApi, HfFolder
from src.config import KEYRING_SERVICE, KEYRING_ACCOUNT

class AuthenticationError(Exception):
    """Authentication failed"""
    pass

class AuthService:
    """Manage authentication with HuggingFace"""
    
    def __init__(self):
        self.api = None
    
    def authenticate(self, token: str) -> Dict[str, str]:
        """
        Validate token and store it securely.
        
        Args:
            token: HF API token
            
        Returns:
            User info dict with username, email, user_id
            
        Raises:
            AuthenticationError: If token is invalid
        """
        try:
            api = HfApi(token=token)
            user_info = api.whoami()
            
            # Store token in keyring
            keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, token)
            
            self.api = api
            return {
                "username": user_info.get("name"),
                "email": user_info.get("email", ""),
                "user_id": user_info.get("user_id"),
            }
        except Exception as e:
            raise AuthenticationError(f"Invalid token: {str(e)}")
    
    def get_token(self) -> Optional[str]:
        """Get stored token from keyring"""
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    
    def clear_token(self):
        """Clear stored token"""
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
```

### 5.4: `src/repository/repo_service.py`

```python
"""Repository Service"""

from typing import Optional
from huggingface_hub import HfApi
import json
from io import BytesIO

class RepositoryError(Exception):
    """Repository operation failed"""
    pass

class RepositoryService:
    """Manage HuggingFace datasets"""
    
    def __init__(self, token: str):
        self.api = HfApi(token=token)
    
    def create_dataset(self, repo_name: str, private: bool = True) -> str:
        """
        Create a new dataset on HuggingFace.
        
        Args:
            repo_name: Dataset name
            private: Whether dataset should be private
            
        Returns:
            Full repo_id (username/repo_name)
        """
        try:
            # Create repo
            repo = self.api.create_repo(
                repo_id=repo_name,
                repo_type="dataset",
                private=private,
                exist_ok=True
            )
            repo_id = repo.repo_id
            
            # Initialize structure
            self._init_structure(repo_id)
            
            return repo_id
        except Exception as e:
            raise RepositoryError(f"Failed to create dataset: {str(e)}")
    
    def _init_structure(self, repo_id: str):
        """Initialize default folder structure"""
        folders = [
            "audio/project",
            "index/shards",
            "validations",
            "audit/ingestion-runs"
        ]
        
        for folder in folders:
            # Upload placeholder file to create folder
            self.api.upload_file(
                path_or_fileobj=BytesIO(b""),
                path_in_repo=f"{folder}/.gitkeep",
                repo_id=repo_id,
                repo_type="dataset"
            )
    
    def validate_repo(self, repo_id: str) -> bool:
        """Validate dataset has expected structure"""
        # TODO: Implement
        return True
```

### 5.5: `src/upload/scanner.py`

```python
"""Local Folder Scanner"""

import os
from pathlib import Path
from typing import Dict, List
from src.config import AUDIO_EXTENSIONS

class LocalScanner:
    """Scan local folders for audio files"""
    
    def scan_folder(self, folder_path: str) -> Dict:
        """
        Recursively scan folder for audio files.
        
        Args:
            folder_path: Path to scan
            
        Returns:
            Structure dict with files grouped by species
        """
        structure = {}
        total_size = 0
        file_count = 0
        
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if any(file.lower().endswith(ext) for ext in AUDIO_EXTENSIONS):
                    full_path = os.path.join(root, file)
                    size = os.path.getsize(full_path)
                    
                    # Infer species
                    specie = self._infer_species(root, file)
                    
                    if specie not in structure:
                        structure[specie] = []
                    
                    structure[specie].append({
                        "name": file,
                        "full_path": full_path,
                        "size": size,
                    })
                    
                    total_size += size
                    file_count += 1
        
        return {
            "total_files": file_count,
            "total_size": total_size,
            "by_species": structure,
        }
    
    def _infer_species(self, root: str, filename: str) -> str:
        """Infer species from path or filename"""
        parts = root.split(os.sep)
        if len(parts) > 0:
            return parts[-1]
        return "unknown"
```

### 5.6: `src/session/session_manager.py`

```python
"""Session Management"""

import json
from pathlib import Path
from datetime import datetime
from src.config import SESSION_DIR

class SessionManager:
    """Manage upload sessions"""
    
    def __init__(self, session_id: str = None):
        if session_id is None:
            session_id = f"upload-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        self.session_id = session_id
        self.session_dir = Path(SESSION_DIR) / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
    
    def save_checkpoint(self, data: dict):
        """Save checkpoint atomically"""
        checkpoint_file = self.session_dir / "checkpoint.json"
        temp_file = checkpoint_file.with_suffix(".tmp")
        
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)
        
        temp_file.replace(checkpoint_file)
    
    def load_checkpoint(self) -> dict:
        """Load last checkpoint"""
        checkpoint_file = self.session_dir / "checkpoint.json"
        if checkpoint_file.exists():
            with open(checkpoint_file) as f:
                return json.load(f)
        return {}
```

### 5.7: `src/ui/tui.py`

```python
"""TUI Application (Textual)"""

from textual.app import ComposeResult, App
from textual.containers import Container
from textual.widgets import Static, Button

class BirdNETApp(App):
    """Main TUI Application"""
    
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Container(
            Static("BirdNET Uploader", id="header"),
            Button("Start Upload", id="btn_upload"),
            id="container"
        )
    
    def on_button_pressed(self) -> None:
        """Handle button press."""
        self.exit()

def run():
    """Run the TUI app"""
    app = BirdNETApp()
    app.run()
```

### 5.8: `src/utils/error_handler.py`

```python
"""Error Handling"""

class BirdNETError(Exception):
    """Base exception"""
    pass

class AuthenticationError(BirdNETError):
    """Authentication failed"""
    pass

class RepositoryError(BirdNETError):
    """Repository operation failed"""
    pass

class UploadError(BirdNETError):
    """Upload operation failed"""
    pass

class ValidationError(BirdNETError):
    """Validation failed"""
    pass
```

---

## Step 6: Criar Test Infrastructure

### 6.1: `pytest.ini`

```ini
[pytest]
testpaths = tests
addopts = -v --tb=short
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

### 6.2: `tests/conftest.py`

```python
"""Test Configuration and Fixtures"""

import pytest
from pathlib import Path
import tempfile
import json

@pytest.fixture
def temp_folder():
    """Create temporary folder with test audio files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test structure
        audio_dir = Path(tmpdir) / "audio" / "Parrot"
        audio_dir.mkdir(parents=True)
        
        # Create dummy audio files
        for i in range(5):
            (audio_dir / f"segment_{i:03d}.wav").write_bytes(b"fake audio data")
        
        yield tmpdir

@pytest.fixture
def mock_hf_token():
    """Mock HF token"""
    return "hf_test_token_12345"

@pytest.fixture
def session_dir(tmp_path):
    """Temporary session directory"""
    session_dir = tmp_path / "sessions" / "test-session"
    session_dir.mkdir(parents=True)
    return session_dir
```

### 6.3: `tests/test_auth.py`

```python
"""Tests for Auth Service"""

import pytest
from src.auth.auth_service import AuthService, AuthenticationError

def test_auth_invalid_token(mock_hf_token):
    """Test that invalid token raises error"""
    auth = AuthService()
    with pytest.raises(AuthenticationError):
        auth.authenticate("invalid_token_xyz")

# More tests to be implemented
```

### 6.4: `tests/test_scanner.py`

```python
"""Tests for File Scanner"""

import pytest
from src.upload.scanner import LocalScanner

def test_scan_folder_empty(tmp_path):
    """Test scanning empty folder"""
    scanner = LocalScanner()
    result = scanner.scan_folder(str(tmp_path))
    assert result["total_files"] == 0
    assert result["total_size"] == 0

def test_scan_folder_with_audio(temp_folder):
    """Test scanning folder with audio files"""
    scanner = LocalScanner()
    result = scanner.scan_folder(temp_folder)
    assert result["total_files"] == 5
    assert result["total_size"] > 0

# More tests to be implemented
```

---

## Step 7: Configurar CI/CD (GitHub Actions)

Criar arquivo: `.github/workflows/test.yml`

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11"]
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Lint
        run: |
          flake8 src tests
      
      - name: Run tests
        run: |
          pytest
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## Step 8: Testar Instalação

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar testes
pytest -v

# Testar import
python -c "import src; print('✓ Imports OK')"

# Rodar CLI help
python -m src.main --help
```

**Esperado**: Todos os comandos rodarem sem erro.

---

## Step 9: Commit Initial

```bash
git add -A
git commit -m "feat: Sprint 1 - Initial project structure and scaffolding"
git push origin feature/birdnet-uploader-cli
```

---

## Checklist: Sprint 1, Day 1 - DONE ✓

- [ ] Branch `feature/birdnet-uploader-cli` criada
- [ ] Estrutura de diretórios completa
- [ ] `requirements.txt` instalado
- [ ] `pyproject.toml` criado
- [ ] Todos os módulos esqueléticos criados (8+ arquivos)
- [ ] `pytest.ini` e `conftest.py` configurados
- [ ] Testes básicos criados
- [ ] CI/CD workflow criado
- [ ] Primeira execução sem erro: `pytest -v`
- [ ] Commit feito e pushed

**Tempo**: ~2-3 horas

---

## Próximos Passos (Task 1.2 - Design Review)

Quando tudo acima estiver **DONE**, fazer:

1. **Meeting de Design Review** com o time (30min)
   - Confirmar Tech Stack (Textual vs Rich+Click)
   - Confirmar persistência (JSON vs SQLite)
   - Validar estrutura de repo HF
   - Assinar decision log

2. **Começar Task 2.1** (Auth Service Implementation)
   - Implementar `AuthService.authenticate()` completo
   - Implementar keyring integration
   - Escrever testes com mocks

---

## Troubleshooting

**Problema**: `pip install` falha com erro de dependência
**Solução**: Upgrade pip: `pip install --upgrade pip`

**Problema**: Imports falhando
**Solução**: Adicionar `export PYTHONPATH="${PYTHONPATH}:$(pwd)"`

**Problema**: Pytest não encontra testes
**Solução**: Verificar que todos os `__init__.py` existem

---

## Documentação de Referência

- BIRDNET_UPLOADER_REDESIGN.md (arquitetura e UX)
- SPRINT_ROADMAP.md (timeline e tasks)
- Este arquivo (Sprint 1 Day 1 setup)
