# 🛠️ Troubleshooting Guide - BirdNET Uploader Windows Portable

## Problema: "Abre tela preta e fecha sozinho"

### Solução Rápida

1. **Extraia o ZIP corretamente**
   - Clique direito > "Extrair tudo"
   - Extraia para uma pasta sem caracteres especiais (ex: `C:\BirdNET-Uploader`)
   - ❌ Não extraia para pastas com: `ç`, `ã`, `é`, espaços (se possível)

2. **Desbloqueie o arquivo**
   ```powershell
   # No PowerShell, na pasta extraída:
   Unblock-File -Path "birdnet-uploader.exe"
   ```

3. **Execute com launcher interativo**
   ```powershell
   cd C:\seu-caminho\birdnet-uploader
   
   # Use este comando para ver erros:
   .\birdnet-uploader.exe 2>&1 | Tee-Object error.log
   
   # Ou abra PowerShell como admin e execute:
   powershell -ExecutionPolicy Bypass -File ".\run-debug.ps1"
   ```

### Se o Problema Persistir

#### Verifique a Porta

A porta 7860 pode estar em uso. Tente mudar:

```powershell
# No PowerShell:
$env:BIRDNET_UPLOADER_PORT = "8080"
.\birdnet-uploader.exe
```

Depois acesse: `http://localhost:8080`

#### Verifique Permissões

```powershell
# Execute como administrador
# Clique direito no PowerShell > "Executar como administrador"

cd C:\seu-caminho\birdnet-uploader
.\birdnet-uploader.exe
```

#### Veja os Logs

A aplicação tenta criar logs aqui:

```
C:\Users\seu_usuario\.birdnet-uploader\logs\
```

Procure pelo arquivo mais recente:

```powershell
# Listar logs mais recentes
Get-ChildItem "$env:USERPROFILE\.birdnet-uploader\logs\" -Order LastWriteTime -Descending | Select -First 5
```

#### Tente a Versão Debug

Se extraiu corretamente, crie um script PowerShell:

```powershell
# Crie arquivo: debug-app.ps1
# Conteúdo:
python -c "
import sys
import os
os.chdir(r'$PWD')
sys.path.insert(0, '.')
from app import *
"
```

Depois execute:
```powershell
powershell -ExecutionPolicy Bypass -File "debug-app.ps1"
```

---

## Problema: Windows Defender/SmartScreen bloqueia execução

### Solução

1. **Clique em "Mais informações"**
   ![](https://raw.githubusercontent.com/jrrribeiro/BirdNET-Uploader-App/main/docs/images/defender-block.png)

2. **Clique em "Executar mesmo assim"**
   ![](https://raw.githubusercontent.com/jrrribeiro/BirdNET-Uploader-App/main/docs/images/defender-run-anyway.png)

3. **Na próxima vez, não aparecerá mais**

### Por que aparece?

- O .exe é novo (sem certificado digital)
- Criado em máquina local (sem assinatura)
- Normal para aplicações portáteis

### Solução Permanente (Futuro)

Vamos adicionar certificado digital na v1.1.0

---

## Problema: "Porta em uso" ou "Address already in use"

### Causas Comuns

- Outra instância já rodando
- Gradio server ainda preso na porta

### Soluções

**Opção 1: Mudar porta**
```powershell
$env:BIRDNET_UPLOADER_PORT = "8080"
.\birdnet-uploader.exe
```

**Opção 2: Liberar porta**
```powershell
# Ver qual processo usa a porta 7860
Get-NetTCPConnection -LocalPort 7860 | Select OwningProcess

# Matar o processo (ex: PID 1234)
Stop-Process -Id 1234 -Force

# Depois tente novamente
.\birdnet-uploader.exe
```

---

## Problema: Upload falha com "HTTP 401"

### Causas

- Token HF inválido
- Token expirou
- Sem permissão no dataset

### Solução

1. **Gere novo token**
   - Vá em: https://huggingface.co/settings/tokens
   - Clique "New token"
   - Copie o token

2. **Login novamente**
   ```powershell
   .\birdnet-uploader.exe login
   # Cole seu token
   ```

3. **Verifique permissão**
   - O dataset deve ter permissão `write`
   - O usuário HF deve ser o proprietário do dataset

---

## Problema: Erro ao extrair ZIP

### Causas

- ZIP corrompido
- Falta espaço em disco
- Permissões insuficientes

### Solução

1. **Validar checksum**
   ```powershell
   # Verificar integridade do arquivo
   $arquivo = "birdnet-uploader-1.0.0-windows.zip"
   $checksum_esperado = "fb022851524b6c7cf05c2f403118ae833f77656643f01fffef768a59865db631"
   $checksum_atual = (Get-FileHash -Path $arquivo -Algorithm SHA256).Hash
   
   if ($checksum_atual -eq $checksum_esperado) {
       Write-Host "✅ ZIP íntegro"
   } else {
       Write-Host "❌ ZIP corrompido, baixe novamente"
   }
   ```

2. **Liberar espaço**
   - Precisa de ~1 GB livre
   - Verifique com: `Get-Volume C:`

3. **Tentar extrair em pasta diferente**
   ```powershell
   Expand-Archive -Path "birdnet-uploader-1.0.0-windows.zip" -DestinationPath "D:\BirdNET"
   ```

---

## Problema: Web UI não abre (porta 7860 não responde)

### Causas

- Firewall bloqueando
- App não iniciou corretamente

### Solução

1. **Permitir no Firewall**
   ```powershell
   # Execute como admin
   New-NetFirewallRule -DisplayName "BirdNET Uploader" `
     -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7860
   ```

2. **Testar conectividade**
   ```powershell
   # Tente conectar
   Test-NetConnection -ComputerName localhost -Port 7860
   ```

3. **Ver logs**
   ```powershell
   Get-Content "$env:USERPROFILE\.birdnet-uploader\logs\*" -Tail 50
   ```

---

## Problema: Upload muito lento

### Otimizações

**Aumentar workers (paralelismo)**
```powershell
# CLI - aumentar de 4 para 8 workers
.\birdnet-uploader.exe upload `
  --repo-id seu-dataset `
  --segments C:\audios `
  --workers 8
```

**Comprimir bem o arquivo**
```powershell
# Usar .tar.gz (melhor compressão que .zip)
tar -czf audios.tar.gz -C C:\audios .

# No web UI, fazer upload do .tar.gz
```

**Melhorar conexão**
- Use ethernet (não Wi-Fi)
- Feche outros downloads
- Faça upload fora de horário pico

---

## Coleta de Informações para Suporte

Se nenhuma solução funcionar, reporte um issue com:

1. **Versão do Windows**
   ```powershell
   [System.Environment]::OSVersion.VersionString
   ```

2. **Versão do .exe**
   ```powershell
   (Get-Item ".\birdnet-uploader.exe").VersionInfo
   ```

3. **Logs completos**
   ```powershell
   # Copiar pasta de logs
   Copy-Item "$env:USERPROFILE\.birdnet-uploader\logs" -Destination ".\logs-backup" -Recurse
   ```

4. **Reproduzir erro e capturar output**
   ```powershell
   # Redirecionar para arquivo
   .\birdnet-uploader.exe 2>&1 | Tee-Object "error-details.txt"
   
   # Anexar error-details.txt na issue
   ```

---

## Contato & Suporte

- 🐛 **Reportar bug**: https://github.com/jrrribeiro/BirdNET-Uploader-App/issues
- 💬 **Discussões**: https://github.com/jrrribeiro/BirdNET-Uploader-App/discussions
- 📖 **Documentação**: [WINDOWS_PORTABLE_SETUP.md](./WINDOWS_PORTABLE_SETUP.md)

---

**Última atualização**: Maio 2026
