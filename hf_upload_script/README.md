# hf_upload_script

Projeto isolado para uso via codigo/CLI.

## Objetivo
- Executar o fluxo de upload pela linha de comando.
- Manter a logica totalmente separada do aplicativo GUI.

## Instalacao
```bash
python -m pip install -r requirements.txt
```

## Execucao
```bash
python app.py --help
```

## Estrutura
- `app.py`: entrypoint CLI
- `uploader/`: modulos de upload e suporte
- `requirements.txt`: dependencias do projeto
- `Temp/`: arquivos temporarios locais

## Observacoes
- Este projeto nao compartilha arquivos com `hf_upload_app`.
- Use `Temp/` para saídas temporarias, testes locais e artefatos intermediarios.
