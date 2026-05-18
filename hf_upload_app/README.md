# hf_upload_app

Aplicação GUI nativa (Tkinter) para upload e empacotamento em executável Windows.

Este subprojeto agora fornece uma interface nativa Tkinter empacotada como um `.exe` via PyInstaller.
O demo Gradio foi movido para `Temp/gradio_ui/` e não faz parte do executável.

## Execução local (desenvolvimento)

1. Crie e ative um ambiente virtual dentro de `hf_upload_app`

```powershell
cd hf_upload_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app_native.py
```

Isso iniciará a interface nativa Tkinter.

Na tela principal você pode adicionar pastas, arquivos soltos ou arquivos compactados, acompanhar a barra de progresso, ver o log em tempo real, copiar o log e interromper o envio com `Stop Upload`.

## Gerar executável (PyInstaller) - Local

Um script PowerShell `build_windows.ps1` está disponível para automatizar a geração local:

```powershell
cd hf_upload_app
.\build_windows.ps1
```

O script cria `dist/`, empacota o conteúdo em um `.zip` e o coloca na raiz do subprojeto.

## Gerar executável (GitHub Actions) - Automatizado

O repositório inclui um workflow que é acionado por _tags_ no formato `v*` (por exemplo `v1.0.1`) e:

- instala dependências em um runner `windows-latest`;
- executa `pyinstaller hf_upload_app.spec` (que agora usa `app_native.py`);
- compacta a saída `dist/` em `hf_upload_app-<tag>-windows.zip`;
- cria um release no GitHub e anexa o `.zip` como asset de release.

Para publicar um release que gera o EXE, crie e envie uma tag:

```bash
git tag v1.0.1
git push origin v1.0.1
```

Após a conclusão do workflow, o botão `Releases` do GitHub conterá o `.zip` com o executável e um link de download direto.

## Estrutura

- `app_native.py`: entrypoint da GUI nativa
- `native_ui.py`: código da interface Tkinter
- `uploader/`: módulos de upload e backend
- `hf_upload_app.spec`: spec do PyInstaller
- `build_windows.ps1`: script para build local no Windows
- `requirements.txt`: dependências do projeto
- `Temp/gradio_ui/`: demo Gradio movido para desenvolvimento

## Observações e Boas Práticas

- Teste a aplicação com `python app_native.py` antes de empacotar.
- Verifique a versão do PyInstaller (`python -m PyInstaller --version`) se o build falhar.
- Ao publicar um release, inclua notas de release e checksum SHA256 do `.zip`.

