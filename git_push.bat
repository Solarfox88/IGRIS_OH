@echo off
cd /d C:\Igris\repo\IGRIS_DEVIN
call .venv\Scripts\activate.bat

echo === GIT STATUS ===
git status --short

echo.
echo === GIT ADD ===
git add -A

echo.
echo === GIT COMMIT ===
git commit -m "feat: Vast.ai GPU integration completa

- VastAI manager con vastai/ollama:0.21.2 (SSH mode)
- Pulsante VPS toggle in homepage e chat header
- Modalita' persistent vs on-demand
- Sistema path automatico (system_context.py)
- Qwen2.5-Coder:7b come modello default (vs Mistral)
- Fix tag [WRITE_FILE] non visibili nella risposta
- Fix _should_execute_actions per conversazioni brevi
- Fix Windows cmd runner (cmd /c per builtins)
- Fix auth Vast.ai (Bearer token)
- Fix instances dict vs list dalla API Vast.ai
- Filtro GPU VRAM >= 16GB (esclude 3080Ti)
- runtype ssh + env dict + onstart bash
- Endpoint /api/vastai/vps/start|stop|status
- Endpoint /api/vastai/raw-instance debug
- Endpoint /api/vastai/vps/start-sync
- Config OpenAI e Vast.ai da .env
- .gitignore aggiornato (config.json escluso)"

echo.
echo === GIT PUSH ===
git push origin init-branch

echo.
echo === DONE ===
