# BirdNET Uploader: Sprint Roadmap (MVP 6-8 semanas)

## Overview
**Objetivo**: Entregar executável local moderno, um fluxo integrado, pausa/retomada, compatibilidade com validador.

**Timeline**: 
- **Semanas 1-2**: Arquitetura + Setup (Foundation)
- **Semanas 3-4**: Módulos Core (Auth, Repo, Upload)
- **Semanas 5-6**: UI + Session Manager (Integration)
- **Semanas 7-8**: Build + Testes + Release (Polish)

**Team**: 2-3 engineers (1 backend, 1 frontend/UI, 1 QA/DevOps)

---

## SPRINT 1: Foundation & Architecture (Semanas 1-2)

### Semana 1: Setup Inicial + Design Review

#### Task 1.1: Setup do Projeto (2 dias, 3 pts)
**Objetivo**: Estrutura base, dependências, CI/CD

**Tarefas**:
- [ ] Criar branch `feature/birdnet-uploader-cli`
- [ ] Criar estrutura de diretórios (`src/`, `tests/`, `build/`)
- [ ] Setup `pyproject.toml` e `requirements.txt`
  - huggingface_hub>=0.28.0
  - click>=8.0.0
  - textual>=0.30.0 (TUI)
  - rich>=13.0.0
  - pydantic>=2.0.0
  - pandas>=2.0.0
  - pyarrow>=14.0.0
  - keyring>=24.0.0
- [ ] Setup GitHub Actions para lint/test
- [ ] Criar `src/__init__.py` e `src/main.py` (skeleton)

**Critério de Pronto**:
- `pip install -r requirements.txt` sem erro
- `python -m src.main --help` roda e exibe help text

---

#### Task 1.2: Design Review + Arquitetura Finalizada (2 dias, 2 pts)
**Objetivo**: Alinhamento com stakeholders, decisões arquiteturais bloqueantes

**Tarefas**:
- [ ] Revisar documento REDESIGN com time
- [ ] Decisão final: Textual vs Rich+Click vs Typer (recomendação: Textual para melhor UX)
- [ ] Decidir sobre persistência: SQLite vs JSON files (recomendação: JSON + estrutura de diretórios)
- [ ] Validar estrutura de repositório HF (audio/index/validations/audit)
- [ ] Documentar todas as decisões em `docs/architecture-decisions.md`

**Critério de Pronto**:
- Documento de decisões assinado
- Time alinhado em tecnologia stack
- Nenhuma bloqueante técnica identificada

---

#### Task 1.3: Estrutura Base de Módulos (2 dias, 3 pts)
**Objetivo**: Criar interfaces/contracts de todos os módulos

**Tarefas**:
- [ ] Criar `src/auth/__init__.py` + `auth_service.py` (skeleton com docstrings)
- [ ] Criar `src/repository/__init__.py` + `repo_service.py` (skeleton)
- [ ] Criar `src/upload/__init__.py` + `scanner.py`, `uploader.py`, `deduplicator.py` (skeleton)
- [ ] Criar `src/csv/__init__.py` + `csv_matcher.py`, `indexer.py` (skeleton)
- [ ] Criar `src/session/__init__.py` + `session_manager.py`, `checkpoint.py` (skeleton)
- [ ] Criar `src/ui/__init__.py` + `tui.py`, `progress_renderer.py` (skeleton)
- [ ] Criar `src/logger/__init__.py` + `structured_logger.py` (skeleton)
- [ ] Criar `src/utils/__init__.py` + `file_utils.py`, `hash_utils.py`, `error_handler.py` (skeleton)

**Critério de Pronto**:
- Todos os módulos existem com `pass` ou docstrings
- Nenhum erro de import circular
- `python -c "import src; print('OK')"` funciona

---

#### Task 1.4: Testes Base + Test Fixtures (1 dia, 2 pts)
**Objetivo**: Infraestrutura de testes pronta

**Tarefas**:
- [ ] Setup `pytest.ini` e `conftest.py`
- [ ] Criar test fixtures para:
  - Mock HfApi
  - Pasta local temporária com arquivos de teste
  - Session mock
  - Token mock
- [ ] Criar `tests/test_auth.py` (skeleton)
- [ ] Criar `tests/test_uploader.py` (skeleton)
- [ ] Criar `tests/test_session.py` (skeleton)

**Critério de Pronto**:
- `pytest` executa sem erro (mesmo que tests sejam vazios)
- Fixtures estão disponíveis para todos os testes

---

### Semana 2: Auth + Repository Services

#### Task 2.1: Auth Service - Implementação Completa (2.5 dias, 5 pts)
**Objetivo**: Login com token, validação, armazenamento seguro

**Tarefas**:
- [ ] Implementar `AuthService.authenticate(token)`:
  - Validar token contra HF API
  - Recuperar info do usuário (username, email, user_id)
  - Salvar em keyring (Windows DPAPI)
  - Retornar user context
- [ ] Implementar `AuthService.get_stored_token()`:
  - Recuperar token do keyring
  - Lançar erro claro se não encontrado
- [ ] Implementar `AuthService.clear_token()`:
  - Remover token do keyring
- [ ] Implementar `TokenManager`:
  - Gerenciar TTL de token
  - Detectar expiração
  - Forçar re-autenticação se necessário
- [ ] Tests:
  - [ ] `test_auth_valid_token()`
  - [ ] `test_auth_invalid_token()`
  - [ ] `test_auth_token_stored_in_keyring()`
  - [ ] `test_auth_token_retrieval()`

**Critério de Pronto**:
- Todos os testes de auth passando
- Token nunca é logado/printed
- Falha de auth retorna mensagem clara

---

#### Task 2.2: Repository Service - Criar Dataset (2 dias, 4 pts)
**Objetivo**: Criar dataset HF e inicializar estrutura padrão

**Tarefas**:
- [ ] Implementar `RepositoryService.create_dataset()`:
  - Validar nome do repositório (slug format)
  - Criar dataset no HF (público/privado)
  - Inicializar pastas padrão (audio/, index/shards/, validations/, audit/)
  - Criar manifest.json inicial
  - Retornar repo_id
- [ ] Implementar `RepositoryService.validate_repo()`:
  - Verificar permissão de escrita
  - Verificar estrutura esperada
  - Retornar validation result
- [ ] Tests:
  - [ ] `test_create_dataset_public()`
  - [ ] `test_create_dataset_private()`
  - [ ] `test_create_dataset_name_validation()`
  - [ ] `test_validate_repo_structure()`

**Critério de Pronto**:
- Dataset criado no HF com structure correta
- Manifest.json com schema_version, project_slug, index
- Testes mockeados passando

---

#### Task 2.3: Config + Constants Finalizadas (1 dia, 2 pts)
**Objetivo**: Configuração centralizada do app

**Tarefas**:
- [ ] Criar `src/config.py`:
  - `AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac', '.ogg']`
  - `SESSION_DIR = ~/.birdnet-uploader/sessions/`
  - `CACHE_DIR = ~/.birdnet-uploader/cache/`
  - `MAX_BATCH_SIZE = 10`
  - `RETRY_MAX_ATTEMPTS = 3`
  - `RETRY_INITIAL_BACKOFF = 1.0`
  - `MANIFEST_SCHEMA_VERSION = "1.0.0"`
- [ ] Implementar config via `.env` se necessário

**Critério de Pronto**:
- Todas as constantes centralizadas
- Nenhum hardcoded value em módulos

---

#### Task 2.4: Error Handling Framework (1.5 dias, 3 pts)
**Objetivo**: Exceções customizadas e mensagens claras

**Tarefas**:
- [ ] Criar `src/exceptions.py`:
  - `AuthenticationError`
  - `RepositoryError`
  - `UploadError`
  - `SessionError`
  - `ValidationError`
- [ ] Implementar `src/utils/error_handler.py`:
  - Converter exceções em mensagens user-friendly
  - Log estruturado de erros
  - Sugestões de ação

**Critério de Pronto**:
- Todas as exceções possuem mensagem clara
- Tests cobrem cenários de erro

---

## SPRINT 2: Upload & CSV Matching (Semanas 3-4)

### Semana 3: Scanner + File Operations

#### Task 3.1: Local Scanner - Varrer Pasta (2 dias, 4 pts)
**Objetivo**: Descobrir arquivos locais, agrupar por espécie

**Tarefas**:
- [ ] Implementar `LocalScanner.scan_folder()`:
  - Varrer recursivamente
  - Filtrar por extensões de áudio
  - Inferir espécie do caminho/nome
  - Calcular tamanho total e contagem
  - Retornar estrutura normalizada
- [ ] Implementar estratégia de inferência de espécie:
  - Strategy 1: Usar última pasta como specie
  - Strategy 2: Usar prefixo do arquivo
  - Strategy 3: Permitir mapeamento manual
- [ ] Tests:
  - [ ] `test_scan_folder_empty()`
  - [ ] `test_scan_folder_multiple_species()`
  - [ ] `test_scan_folder_specie_inference()`
  - [ ] `test_scan_folder_with_nested_dirs()`

**Critério de Pronto**:
- Escaneia pasta com 1000+ arquivos em <5 segundos
- Estrutura normalizada e validada

---

#### Task 3.2: Hash Utils + File Operations (1.5 dias, 3 pts)
**Objetivo**: Computação de hash segura, operações de arquivo

**Tarefas**:
- [ ] Implementar `compute_file_hash(path) -> str`:
  - SHA256 eficiente (streaming para arquivos grandes)
  - Cache local de hashes
- [ ] Implementar `verify_file_integrity(path, hash)`:
  - Validar arquivo não corrompido
- [ ] Tests:
  - [ ] `test_compute_hash_small_file()`
  - [ ] `test_compute_hash_large_file()`
  - [ ] `test_hash_consistency()`

**Critério de Pronto**:
- Hash de arquivo 1GB < 2 segundos
- Testes passando

---

#### Task 3.3: Deduplicator - Verificar Existência (2 dias, 3 pts)
**Objetivo**: Detectar arquivos já no destino

**Tarefas**:
- [ ] Implementar `Deduplicator.check_remote()`:
  - Query HF API para verificar existência por caminho
  - Comparar tamanho + hash opcional
  - Retornar status (SKIP, UPLOAD, CONFLICT)
- [ ] Implementar dedup local cache (evitar queries repetidas)
- [ ] Tests:
  - [ ] `test_check_remote_new_file()`
  - [ ] `test_check_remote_existing_file()`
  - [ ] `test_check_remote_conflict()`

**Critério de Pronto**:
- Dedup funciona sem re-query excessiva
- Cache valida corretamente

---

#### Task 3.4: Session + Checkpoint - State Persistence (2.5 dias, 5 pts)
**Objetivo**: Persistência atomática de estado para retomada

**Tarefas**:
- [ ] Implementar `SessionManager.create_session()`:
  - Gerar session_id
  - Criar diretório de sessão
  - Inicializar metadata.json
- [ ] Implementar `CheckpointManager.save_checkpoint()`:
  - Escrita atômica (temp + rename)
  - Validação de JSON
  - Flush para disco (fsync)
- [ ] Implementar `CheckpointManager.load_checkpoint()`:
  - Recuperar último checkpoint
  - Validação de integridade
- [ ] Implementar `SessionManager.mark_file_done()`:
  - Atualizar manifest por arquivo
- [ ] Tests:
  - [ ] `test_session_creation()`
  - [ ] `test_checkpoint_atomic_write()`
  - [ ] `test_checkpoint_recovery_after_crash()`
  - [ ] `test_session_resume_same_id()`

**Critério de Pronto**:
- Checkpoint atomático garante consistência
- Recuperação de crash funciona
- Testes cobrem falha de escrita

---

### Semana 4: Upload Engine + CSV Matching

#### Task 4.1: Batch Uploader - Motor Principal (3 dias, 6 pts)
**Objetivo**: Upload resiliente com retry/dedup/pause

**Tarefas**:
- [ ] Implementar `BatchUploader.upload_files()`:
  - Iterar sobre estrutura de arquivos
  - Aplicar dedup check
  - Upload com retry automático
  - Atualizar checkpoint por lote
  - Callback de progresso
- [ ] Implementar retry com exponential backoff:
  - Backoff: 1s → 2s → 5s → 10s → 30s
  - Tratamento de 429 (rate limit)
  - Max 3 retries por padrão
- [ ] Implementar pause/resume:
  - Signal SIGTERM/SIGINT
  - Salvar state
  - Resume com checkpoint
- [ ] Tests:
  - [ ] `test_upload_batch_success()`
  - [ ] `test_upload_with_retry()`
  - [ ] `test_upload_skip_existing()`
  - [ ] `test_upload_pause_resume()`

**Critério de Pronto**:
- Upload funciona end-to-end
- Retry logic testado
- Pause/resume funciona

---

#### Task 4.2: CSV Matcher + Index Generator (2.5 dias, 5 pts)
**Objetivo**: Matching CSV com segmentos e geração de índice

**Tarefas**:
- [ ] Implementar `CSVMatcher.match_detections()`:
  - Ler CSV com validação de schema
  - Fazer matching com segmentos (source_file → arquivo local)
  - Gerar detection_key determinístico
  - Retornar matched + unmatched + ambiguous
- [ ] Implementar `IndexGenerator.generate_shards()`:
  - Particionar dados em shards (tamanho configurável)
  - Salvar como parquet
  - Gerar metadata de shards
- [ ] Implementar `ManifestBuilder.build()`:
  - Construir manifest.json com schema_version
  - Incluir metadados de index
  - Serializar JSON
- [ ] Tests:
  - [ ] `test_csv_matching_success()`
  - [ ] `test_csv_missing_columns()`
  - [ ] `test_shard_generation()`
  - [ ] `test_manifest_format()`

**Critério de Pronto**:
- CSV+segmentos matchados corretamente
- Shards gerados com formato correto
- Manifest válido e legível

---

## SPRINT 3: UI + Integration (Semanas 5-6)

### Semana 5: UI TUI Implementation

#### Task 5.1: Textual TUI - Fluxo Principal (3 dias, 6 pts)
**Objetivo**: Interface TUI moderna para guiar usuário

**Tarefas**:
- [ ] Criar `src/ui/screens/login_screen.py`:
  - Input para token HF
  - Validação em tempo real
  - Mensagens de erro claras
- [ ] Criar `src/ui/screens/config_screen.py`:
  - Form com campos: repo name, visibility, segments path, csv path
  - Verificação de pasta
  - Validação de formato
- [ ] Criar `src/ui/screens/summary_screen.py`:
  - Exibir configuração resumida
  - Botão de confirmação
- [ ] Criar `src/ui/screens/upload_screen.py`:
  - Barra de progresso principal
  - Progresso por arquivo
  - Arquivo atual
  - Último evento
  - Botões pause/cancel
- [ ] Implementar navegação entre screens

**Critério de Pronto**:
- Fluxo completo funcionando (login → config → summary → upload)
- Inputs validados
- Navegação intuitiva

---

#### Task 5.2: Progress Renderer (1.5 dias, 3 pts)
**Objetivo**: Visualização rich de progresso

**Tarefas**:
- [ ] Implementar progress bar customizada:
  - Percentual + barra visual
  - ETA com update em tempo real
  - Arquivo atual
  - Contadores (uploaded/pending/failed/skipped)
- [ ] Implementar event log:
  - Últimos 10 eventos
  - Código de status/cor por tipo

**Critério de Pronto**:
- Progress bar atualiza sem flicker
- ETA coerente
- Eventos visíveis

---

### Semana 6: Integration + Testes End-to-End

#### Task 6.1: Integration Testing + Mocks (2 dias, 4 pts)
**Objetivo**: Teste de fluxo completo (mockeado)

**Tarefas**:
- [ ] Criar `tests/test_integration.py`:
  - Teste login + config + upload (mockeado)
  - Teste pause/resume
  - Teste com CSV
- [ ] Mockar HfApi completamente
- [ ] Rodar testes de carga (1000+ arquivos mockeados)

**Critério de Pronto**:
- Testes de integração passando
- Sem vazamento de recursos

---

#### Task 6.2: Real Integration Test (pequena escala) (2 dias, 4 pts)
**Objetivo**: Teste real com dataset HF de verdade

**Tarefas**:
- [ ] Criar dataset de teste no HF (alice/test-uploader-small)
- [ ] Teste com 100 arquivos reais (~500MB)
- [ ] Validar estrutura no HF pós-upload
- [ ] Validar manifest.json e shards

**Critério de Pronto**:
- Arquivos aparecem no HF
- Estrutura correta
- Manifest válido

---

## SPRINT 4: Build + Polish (Semanas 7-8)

### Semana 7: Build + Release

#### Task 7.1: PyInstaller Setup (2 dias, 4 pts)
**Objetivo**: Gerar executável portátil Windows

**Tarefas**:
- [ ] Criar `build/pyinstaller_config.spec`:
  - One-file executable
  - Hidden imports para textual, rich, pandas, pyarrow
  - Resource bundling
- [ ] Criar `build/build.py` script
- [ ] Testar executável gerado localmente
- [ ] Validar tamanho (~100-150MB)

**Critério de Pronto**:
- Executável funciona sem Python instalado
- Tamanho razoável
- Sem erros de runtime

---

#### Task 7.2: Documentação + README (1.5 dias, 2 pts)
**Objetivo**: Docs para usuários finais

**Tarefas**:
- [ ] Criar README.md com:
  - Quick start (download, run, autenticar)
  - Screenshots
  - Troubleshooting
  - FAQ
- [ ] Criar INSTALLATION.md
- [ ] Criar USAGE.md (exemplos de comando)

**Critério de Pronto**:
- Usuário não-técnico consegue rodar pelo README

---

#### Task 7.3: Testes de Carga + Stress (2 dias, 4 pts)
**Objetivo**: Validar com dados reais maiores

**Tarefas**:
- [ ] Teste com pasta 5GB (1000+ arquivos)
- [ ] Teste com CSV 5000+ linhas
- [ ] Teste pause/resume 5x
- [ ] Monitorar memória e CPU
- [ ] Documentar performance (tempo/MB/s)

**Critério de Pronto**:
- Memória < 500MB durante upload
- CPU < 30% média
- Upload rate > 5 MB/s (com rede OK)

---

### Semana 8: Release + Smoke Tests

#### Task 8.1: Release Pipeline (1.5 dias, 2 pts)
**Objetivo**: Setup de distribuição

**Tarefas**:
- [ ] Criar release no GitHub com:
  - Executável (`.exe`)
  - SHA256 hash
  - Release notes
  - Link para docs
- [ ] Testar download + execução do exe
- [ ] Validar assinatura (opcional nesta fase)

**Critério de Pronto**:
- Release publicado
- Download funciona
- Exe roda após download/extração

---

#### Task 8.2: Smoke Tests + Final QA (1.5 dias, 3 pts)
**Objetivo**: Validação final antes do release

**Tarefas**:
- [ ] Checklist final:
  - [ ] Login funciona
  - [ ] Criar repo funciona
  - [ ] Upload de 10GB completa
  - [ ] Pause/resume sem perda
  - [ ] CSV matching correto
  - [ ] Manifest válido no destino
  - [ ] Estrutura compatível com validador
- [ ] Teste com 3+ usuários externos (team)
- [ ] Coleta de feedback

**Critério de Pronto**:
- Zero bugs críticos
- Feedback incorporado
- Pronto para release

---

## BACKLOG: Priorização de Tasks

| Sprint | Semana | Task | Pts | Status |
|--------|--------|------|-----|--------|
| 1 | 1 | Setup + Design | 5 | Não iniciado |
| 1 | 1 | Arquitetura de Módulos | 3 | Não iniciado |
| 1 | 1 | Test Infrastructure | 2 | Não iniciado |
| 1 | 2 | Auth Service | 5 | Bloqueado por 1.1 |
| 1 | 2 | Repository Service | 4 | Bloqueado por 1.1 |
| 1 | 2 | Config + Constants | 2 | Bloqueado por 1.1 |
| 1 | 2 | Error Handling | 3 | Bloqueado por 1.1 |
| 2 | 3 | Local Scanner | 4 | Bloqueado por Sprint 1 |
| 2 | 3 | Hash Utils | 3 | Bloqueado por Sprint 1 |
| 2 | 3 | Deduplicator | 3 | Bloqueado por Sprint 1 |
| 2 | 3 | Session + Checkpoint | 5 | Bloqueado por Sprint 1 |
| 2 | 4 | Batch Uploader | 6 | Bloqueado por Sprint 1 |
| 2 | 4 | CSV Matcher | 5 | Bloqueado por Sprint 1 |
| 3 | 5 | Textual TUI | 6 | Bloqueado por Sprint 2 |
| 3 | 5 | Progress Renderer | 3 | Bloqueado por Sprint 2 |
| 3 | 6 | Integration Tests | 4 | Bloqueado por Sprint 2 |
| 3 | 6 | Real Integration Test | 4 | Bloqueado por Sprint 2 |
| 4 | 7 | PyInstaller | 4 | Bloqueado por Sprint 3 |
| 4 | 7 | Documentation | 2 | Bloqueado por Sprint 3 |
| 4 | 7 | Load Testing | 4 | Bloqueado por Sprint 3 |
| 4 | 8 | Release Pipeline | 2 | Bloqueado por Sprint 3 |
| 4 | 8 | Final QA | 3 | Bloqueado por Sprint 3 |

**Total: ~84 story points (6-8 semanas com 2-3 eng)**

---

## Velocity + Alocação de Equipe

### Cenário 1: Full Team (2 eng)
- Sprint de 2 semanas, 2 eng = ~40 pts/sprint
- Sprint 1-2: 26 pts (semana 1 paralelo, semana 2 paralelo) ✓ cabe
- Sprint 2 continuation: ~20 pts (cabe)
- Sprint 3: ~13 pts (cabe)
- Sprint 4: ~15 pts (cabe)

### Cenário 2: 3 Eng (Backend + Frontend + QA)
- Paralelizar mais agressivamente
- Timeline pode reduzir de 8 para 6-7 semanas

---

## Critérios de "Done" por Sprint

### Sprint 1 Done ✓
- [ ] Todos os módulos base existem (importáveis)
- [ ] Auth funciona com keyring
- [ ] Repo pode ser criado no HF
- [ ] Testes de auth e repo passando
- [ ] Setup pronto para Sprint 2

### Sprint 2 Done ✓
- [ ] Scanner varre pasta corretamente
- [ ] Uploader faz batch com retry
- [ ] CSV matcher funciona end-to-end
- [ ] Checkpoint salva e recupera estado
- [ ] Testes cobrem 80%+ de lógica

### Sprint 3 Done ✓
- [ ] Fluxo TUI completo (login → config → upload)
- [ ] Progresso visual atualiza sem flicker
- [ ] Integração completa mockeada testada
- [ ] Real integration test com 500MB+ passou
- [ ] Pronto para build

### Sprint 4 Done ✓
- [ ] Executável portátil gerado e testado
- [ ] Release pipeline setup
- [ ] Documentação completa
- [ ] Smoke tests passando
- [ ] Pronto para distribuição

---

## Next Steps

1. **Aprovação**: Confirmar timeline, team size, prioridades
2. **Sprint 1 Kickoff**: Semana que vem
3. **Daily Standups**: 15min todo dia weekday
4. **Sprint Reviews**: Sexta-feira cada semana
5. **Retrospectives**: Fim de cada sprint

---

## Notas & Riscos

- **Risco 1**: PyInstaller não empacotar corretamente → Mitigar: spike de 1 dia em week 7
- **Risco 2**: Performance ruim em 50GB+ → Mitigar: load test cedo (week 4)
- **Risco 3**: Incompatibilidade com validador → Mitigar: validação de manifest early (week 4)
- **Risco 4**: UX TUI confusa → Mitigar: user testing em week 6

Todas as risks têm mitigation strategy atrelada.
