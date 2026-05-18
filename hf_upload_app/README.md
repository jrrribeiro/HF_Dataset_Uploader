# hf_upload_app

Aplicacao GUI para upload e empacotamento em executavel Windows.

Este subprojeto contem a interface Gradio e o spec do PyInstaller para gerar um `.exe` standalone.

## Execucao local (desenvolvimento)

1. crie e ative um ambiente virtual dentro de `hf_upload_app`

```powershell
cd hf_upload_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Ao executar, a interface sera exposta via Gradio (por padrao `http://localhost:7860`).

## Gerar executavel (PyInstaller) - Local

Um script PowerShell `build_windows.ps1` foi adicionado para automatizar a geracao e empacotamento local:

```powershell
cd hf_upload_app
.\build_windows.ps1
```

O script cria `dist/`, empacota o conteudo em um `.zip` e o coloca na raiz do subprojeto.

## Gerar executavel (GitHub Actions) - Automatizado

O repositório inclui um workflow: `.github/workflows/build-and-release-windows.yml`.
Esse workflow é disparado por _tags_ no formato `v*` (por exemplo `v1.0.1`) e:

- instala dependências em uma runner `windows-latest`;
- executa `pyinstaller hf_upload_app.spec`;
- compacta a saída `dist/` em `hf_upload_app-<tag>-windows.zip`;
- cria um release no GitHub e anexa o `.zip` como asset de release.

Para publicar um release que gera o EXE, crie e envie uma tag:

```bash
git tag v1.0.1
git push origin v1.0.1
```

Após a conclusão do workflow, o botão `Releases` do GitHub conterá o `.zip` com o executavel e um link de download direto.

## Estrutura

- `app.py`: entrypoint GUI/CLI
- `uploader/`: modulos de upload e interface
- `hf_upload_app.spec`: spec do PyInstaller
- `build_windows.ps1`: script para build local no Windows
- `launcher.bat`: launcher local para Windows
- `requirements.txt`: dependencias do projeto
- `Temp/`: arquivos temporarios locais

## Observacoes e Boas Praticas

- Teste a aplicacao com `python app.py` antes de empacotar.
- Verifique a versao do PyInstaller (`python -m PyInstaller --version`) se o build falhar.
- Ao publicar um release, inclua notas de release e checksum SHA256 do `.zip`.

