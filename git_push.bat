@echo off
cd /d C:\Igris\repo\IGRIS_DEVIN
call .venv\Scripts\activate.bat
echo.
echo === IGRIS GIT PUSH ===
echo.

git add -A
git status --short

echo.
git commit -m "feat: Vast.ai GPU, VPS toggle, memoria persistente, cost routing, dashboard

Vast.ai:
- vastai/ollama:0.21.2 image (ufficiale, funziona)
- runtype ssh + env dict + onstart bash (formato corretto)
- Porta 11434 mappata via ports dict nella risposta API
- Filtro GPU VRAM >= 16GB (no piu' 3080 Ti)
- Priorita' EU/US su CN/HK (boot piu' veloce)
- Fix instances dict vs list dalla API
- VPS toggle persistente/on-demand
- Endpoint /api/vastai/vps/start|stop|status|start-sync
- Endpoint /api/vastai/raw-instance debug
- Pull modello via API HTTP dopo Ollama pronto

Nuove funzionalita':
- Memoria operativa persistente tra sessioni (igris/core/memory.py)
- Dashboard /api/dashboard con stato sistema completo
- Cost routing automatico (LOCAL/API/VASTAI per complessita')
- Auto-reload uvicorn (igris web --reload default)

Fix:
- system_context.py rileva user/paths automaticamente
- Qwen2.5-Coder:7b come modello default
- Tag [WRITE_FILE] non visibili
- _should_execute_actions fix false positives
- Windows cmd runner (cmd /c per builtins)
- .gitignore aggiornato (config.json escluso)
- paramiko per SSH su Windows"

echo.
echo === PUSHING ===
git push origin init-branch

echo.
echo === DONE ===
pause
