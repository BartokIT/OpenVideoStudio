@echo off
rem Start OpenVideoStudio (http://127.0.0.1:7870) and open the browser.
rem ComfyUI is not needed for Remix; Create starts it on demand
rem (from COMFYUI_ROOT in studio\.env). Ollama must be running for Create.
cd /d "%~dp0studio"
.venv\Scripts\python.exe -m server
