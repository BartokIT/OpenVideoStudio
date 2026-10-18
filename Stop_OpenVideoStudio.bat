@echo off
rem Stop OpenVideoStudio (port 7870) and ComfyUI (port 8188), and free Ollama's VRAM
echo Stopping OpenVideoStudio and ComfyUI...
powershell -NoProfile -Command "foreach ($port in 7870, 8188) { Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { $p = Get-Process -Id $_ -ErrorAction SilentlyContinue; if ($p) { Write-Host ('  Stopping ' + $p.ProcessName + ' (PID ' + $p.Id + ') on port ' + $port); Stop-Process -Id $p.Id -Force } } }"
rem Unload the model from the GPU without closing Ollama
ollama stop qwen3:8b >nul 2>&1
echo Done.
timeout /t 3 >nul
