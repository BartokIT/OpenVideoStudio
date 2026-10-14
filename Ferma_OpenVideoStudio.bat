@echo off
rem Ferma OpenVideoStudio (porta 7870) e ComfyUI (porta 8188), e libera la VRAM di Ollama
echo Arresto di OpenVideoStudio e ComfyUI...
powershell -NoProfile -Command "foreach ($port in 7870, 8188) { Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { $p = Get-Process -Id $_ -ErrorAction SilentlyContinue; if ($p) { Write-Host ('  Fermo ' + $p.ProcessName + ' (PID ' + $p.Id + ') sulla porta ' + $port); Stop-Process -Id $p.Id -Force } } }"
rem Scarica il modello dalla GPU senza chiudere Ollama
ollama stop qwen3:8b >nul 2>&1
echo Fatto.
timeout /t 3 >nul
