@echo off
rem Avvia OpenVideoStudio (http://127.0.0.1:7870) e apre il browser.
rem ComfyUI non serve per Remix; per Create parte da solo quando si genera
rem (usa COMFYUI_ROOT in studio\.env). Ollama deve essere in esecuzione per Create.
cd /d "%~dp0studio"
.venv\Scripts\python.exe -m server
