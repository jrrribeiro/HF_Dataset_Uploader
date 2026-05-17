# HF_Dataset_Uploader

Repositorio reorganizado em dois projetos isolados:

- hf_upload_script: uso via codigo/CLI
- hf_upload_app: uso via aplicativo/GUI e build de executavel

Nao ha compartilhamento de arquivos entre os dois projetos.

## Sobre `hf_bulk_upload_tool`
`hf_bulk_upload_tool` era a estrutura legada do projeto antigo. Ela foi removida deste repositario.
O funcionamento atual esta concentrado somente em `hf_upload_script` e `hf_upload_app`.

## Como usar

### 1) Script (CLI)
```bash
cd hf_upload_script
python -m pip install -r requirements.txt
python app.py --help
```

### 2) App (GUI)
```bash
cd hf_upload_app
python -m pip install -r requirements.txt
python app.py
```

### 3) Executavel (PyInstaller)
```bash
cd hf_upload_app
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller hf_upload_app.spec --noconfirm
```

## Pasta Temp
Use `Temp/` na raiz para arquivos temporarios gerais.
Cada subprojeto tambem possui sua propria pasta `Temp/`.
