# hf_upload_app

Projeto isolado para uso como aplicativo (GUI) e empacotamento executavel.

## Execucao local
python app.py

## Gerar executavel (PyInstaller)
pyinstaller hf_upload_app.spec --noconfirm

## Estrutura
- app.py: entrypoint GUI/CLI
- uploader/: modulos de upload
- hf_upload_app.spec: spec do PyInstaller
- launcher.bat: launcher local
- requirements.txt: dependencias
- Temp/: arquivos temporarios locais
