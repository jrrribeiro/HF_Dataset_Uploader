# hf_upload_app

Projeto isolado para uso como aplicativo (GUI) e empacotamento executavel.

## Objetivo
- Executar a interface grafica e, se necessario, o modo CLI auxiliar.
- Empacotar o aplicativo como executavel independente.

## Instalacao
```bash
python -m pip install -r requirements.txt
```

## Execucao local
```bash
python app.py
```

## Gerar executavel (PyInstaller)
```bash
python -m pip install pyinstaller
pyinstaller hf_upload_app.spec --noconfirm
```

## Estrutura
- `app.py`: entrypoint GUI/CLI
- `uploader/`: modulos de upload e interface
- `hf_upload_app.spec`: spec do PyInstaller
- `launcher.bat`: launcher local para Windows
- `requirements.txt`: dependencias do projeto
- `Temp/`: arquivos temporarios locais

## Observacoes
- Este projeto nao compartilha arquivos com `hf_upload_script`.
- Use `Temp/` para logs, caches e artefatos temporarios.
