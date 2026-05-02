"""FastAPI web server for IGRIS chat interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from igris.core.chat_engine import ChatEngine
from igris.models.config import IgrisConfig

logger = logging.getLogger("igris.web")

WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"


class SendMessageRequest(BaseModel):
    content: str


class CreateSessionRequest(BaseModel):
    project_name: str = ""


class CreateProjectRequest(BaseModel):
    name: str


class SetTierRequest(BaseModel):
    tier: str  # auto | local | api | vastai


def create_app(config: IgrisConfig | None = None) -> FastAPI:
    if config is None:
        config = IgrisConfig.load_or_default(".")

    app = FastAPI(title="IGRIS", description="AI Engineering Agent", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    engine = ChatEngine(config)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_path = TEMPLATES_DIR / "index.html"
        if index_path.exists():
            return index_path.read_text(encoding="utf-8")
        return "<h1>IGRIS Web UI</h1><p>Template not found.</p>"

    @app.get("/api/projects")
    async def list_projects():
        return {"projects": engine.list_projects()}

    @app.post("/api/projects")
    async def create_project(req: CreateProjectRequest):
        project_name = req.name.strip()
        if not project_name:
            raise HTTPException(400, "Project name required")
        if project_name not in engine.projects:
            engine.projects[project_name] = []
        return {"name": project_name, "sessions": []}

    @app.post("/api/sessions")
    async def create_session(req: CreateSessionRequest):
        session = engine.create_session(req.project_name)
        return session.to_dict()

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        session = engine.get_session(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        return {
            **session.to_dict(),
            "messages": session.get_history(),
        }

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if not engine.delete_session(session_id):
            raise HTTPException(404, "Session not found")
        return {"deleted": True}

    @app.put("/api/sessions/{session_id}/tier")
    async def set_session_tier(session_id: str, req: SetTierRequest):
        try:
            engine.set_session_tier(session_id, req.tier)
            return {"session_id": session_id, "tier": req.tier}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, req: SendMessageRequest):
        if not req.content.strip():
            raise HTTPException(400, "Message content required")
        try:
            msg = await engine.send_message(session_id, req.content)
            return msg.to_dict()
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            logger.error(f"Send message failed: {e}")
            raise HTTPException(500, f"Error: {str(e)}")

    @app.post("/api/sessions/{session_id}/messages/stream")
    async def send_message_stream(session_id: str, req: SendMessageRequest):
        if not req.content.strip():
            raise HTTPException(400, "Message content required")

        async def event_generator():
            try:
                async for chunk in engine.send_message_stream(session_id, req.content):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            except ValueError as e:
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            except Exception as e:
                logger.error(f"Stream failed: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/vastai/test")
    async def test_vastai_provisioning():
        """Test completo provisioning Vast.ai con traceback dettagliato."""
        import traceback
        import httpx
        VAST_API_BASE = "https://console.vast.ai/api/v0"
        api_key = config.vastai.api_key
        result = {"step": "start", "error": None, "traceback": None}
        try:
            # Step 1: auth
            result["step"] = "auth"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{VAST_API_BASE}/users/current/",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                r.raise_for_status()
                result["auth"] = {"ok": True, "user": r.json().get("username")}

            # Step 2: search (POST con Bearer)
            result["step"] = "search_post_bearer"
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{VAST_API_BASE}/bundles/",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"gpu_name": {"in": ["RTX 4090"]}, "rentable": {"eq": True}, "limit": 3}
                )
                result["search_status"] = r.status_code
                result["search_body_preview"] = r.text[:500]
                r.raise_for_status()
                data = r.json()
                offers = data.get("offers", [])
                result["offers_found"] = len(offers)
                result["best_offer"] = offers[0] if offers else None

            result["step"] = "completed"
        except Exception as e:
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()
        return result

    @app.post("/api/vastai/test-create")
    async def test_vastai_create():
        """Testa la creazione istanza (dry-run: crea e distrugge subito)."""
        import httpx
        VAST_API_BASE = "https://console.vast.ai/api/v0"
        api_key = config.vastai.api_key
        if not api_key:
            return {"error": "api_key mancante"}
        hdrs = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        result = {}

        # 1. Trova offerta
        m = engine.router.vastai_manager
        if not m:
            return {"error": "manager non inizializzato"}
        try:
            offer = await m._find_best_offer()
            result["offer"] = {"id": offer["id"], "price": offer.get("dph_total"), "loc": offer.get("geolocation")}
        except Exception as e:
            return {"error": f"find_offer failed: {e}"}

        # 2. Tenta create - mostra raw response
        payload = {
            "image": "nvidia/cuda:12.4.1-runtime-ubuntu22.04",
            "label": "igris-test",
            "disk": 40,
            "runtype": "cmd",
            "target_state": "running",
            "cancel_unavail": True,
            "env": {"11434/tcp": [{"HostIp": "0.0.0.0", "HostPort": "11434"}]},
            "onstart": "bash -c 'curl -fsSL https://ollama.com/install.sh | sh && OLLAMA_HOST=0.0.0.0 nohup ollama serve > /tmp/ollama.log 2>&1 & sleep 20 && ollama pull qwen2.5-coder:7b'",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.put(
                    f"{VAST_API_BASE}/asks/{offer['id']}/",
                    headers=hdrs,
                    json=payload,
                )
                result["create_status"] = resp.status_code
                result["create_body"] = resp.json()

                # 3. Se creata, distruggi subito
                instance_id = result["create_body"].get("new_contract")
                if instance_id:
                    result["instance_id"] = instance_id
                    del_resp = await client.delete(
                        f"{VAST_API_BASE}/instances/{instance_id}/",
                        headers=hdrs,
                    )
                    result["destroy_status"] = del_resp.status_code
                    result["destroy_ok"] = del_resp.status_code == 200
        except Exception as e:
            result["create_error"] = str(e)

        return result

    @app.get("/api/vastai/raw-instance")
    async def raw_instance_status():
        """Legge il raw status dell'istanza corrente direttamente dall'API Vast.ai."""
        import httpx
        m = engine.router.vastai_manager
        if not m or not m.state.instance_id:
            return {"error": "nessuna istanza", "instance_id": None}
        hdrs = {"Authorization": f"Bearer {config.vastai.api_key}"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://console.vast.ai/api/v0/instances/{m.state.instance_id}/",
                headers=hdrs
            )
            data = resp.json()
        return data

    @app.post("/api/vastai/vps/start")
    async def vps_start():
        """Avvia la VPS Vast.ai in modalità persistente (guard anti-duplicazione)."""
        if not engine.router.vastai_manager:
            return {"error": "Vast.ai non configurato"}
        m = engine.router.vastai_manager

        # Guard: se già in corso, ritorna stato attuale senza creare
        if m.state.status in ("provisioning", "running", "ready"):
            return {
                "ok": True,
                "synced": True,
                "status": m.state.status,
                "instance_id": m.state.instance_id,
                "message": f"Istanza già {m.state.status} — sincronizzato senza crearne un'altra",
            }

        m.set_persistent(True)

        import asyncio, traceback
        async def _provision_with_log():
            try:
                logger.info("VPS: avvio provisioning persistente...")
                api_base = await m.ensure_ready()
                logger.info(f"VPS: pronta su {api_base}")
            except RuntimeError as e:
                if "__PROVISIONING__" in str(e):
                    logger.info("VPS: provisioning già in corso, attendo")
                else:
                    logger.error(f"VPS provisioning FALLITO: {e}")
                    m.state.status = "error"
                    m.state.save()
            except Exception as e:
                logger.error(f"VPS provisioning FALLITO: {e}\n{traceback.format_exc()}")
                m.state.status = "error"
                m.state.save()

        asyncio.ensure_future(_provision_with_log())
        return {"ok": True, "synced": False, "status": "provisioning", "instance_id": m.state.instance_id}

    @app.post("/api/run-test100")
    async def run_test100():
        """Lancia test_100.py in background senza bloccare IGRIS."""
        import asyncio
        import subprocess
        from pathlib import Path
        repo   = Path("C:/Igris/repo/IGRIS_DEVIN")
        python = str(repo / ".venv" / "Scripts" / "python.exe")
        script = str(repo / "test_100.py")
        out    = "C:/Users/Admin/Desktop/test100_output.txt"
        try:
            # Usa subprocess.Popen (non bloccante, sincrono, cross-platform)
            with open(out, "w", encoding="utf-8") as f:
                proc = subprocess.Popen(
                    [python, "-u", script, "1", "100"],
                    stdout=f, stderr=subprocess.STDOUT,
                    cwd=str(repo),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0,
                )
            return {"ok": True, "pid": proc.pid, "output": out}
        except Exception as e:
            import traceback
            return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}

    @app.get("/api/run-test100/status")
    async def test100_status():
        """Legge le ultime righe dell'output del test."""
        from pathlib import Path
        out = Path("C:/Users/Admin/Desktop/test100_output.txt")
        if not out.exists():
            return {"running": False, "lines": []}
        lines = out.read_text(encoding="utf-8", errors="ignore").splitlines()
        return {"running": True, "total_lines": len(lines), "last_10": lines[-10:]}

    @app.get("/api/routing/explain")
    async def explain_routing_endpoint(prompt: str):
        """Mostra come l'orchestratore instradera' questo prompt."""
        return engine.router.explain_routing(prompt)

    @app.get("/api/vastai/debug")
    async def debug_vastai():
        """Debug completo: testa ogni step del provisioning Vast.ai."""
        import httpx, json as _json
        VAST_API_BASE = "https://console.vast.ai/api/v0"
        api_key = config.vastai.api_key
        result = {
            "key_present": bool(api_key),
            "key_len": len(api_key) if api_key else 0,
            "manager_initialized": engine.router.vastai_manager is not None,
        }
        if not api_key:
            result["error"] = "api_key vuota in config.json"
            return result

        hdrs = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # Step 1: auth
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{VAST_API_BASE}/users/current/", headers=hdrs)
                if resp.status_code == 200:
                    u = resp.json()
                    result["auth"] = {"ok": True, "user": u.get("username"), "credit": u.get("credit")}
                else:
                    result["auth"] = {"ok": False, "status": resp.status_code, "body": resp.text[:200]}
                    return result
        except Exception as e:
            result["auth"] = {"ok": False, "error": str(e)}
            return result

        # Step 2: search con GET (metodo debug)
        try:
            q = _json.dumps({"gpu_name": {"eq": "RTX 4090"}, "rentable": {"eq": True}, "order": [["dph_total", "asc"]], "limit": 3})
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{VAST_API_BASE}/bundles/", headers=hdrs, params={"q": q})
                d = resp.json()
                offers_get = d.get("offers", [])
                result["search_GET"] = {"ok": resp.status_code == 200, "count": len(offers_get), "status": resp.status_code}
        except Exception as e:
            result["search_GET"] = {"ok": False, "error": str(e)}

        # Step 3: search con POST (metodo vastai_manager)
        try:
            payload = {"gpu_name": {"in": ["RTX 4090"]}, "rentable": {"eq": True}, "verified": {"eq": True}, "type": "ondemand", "limit": 3}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{VAST_API_BASE}/bundles/", headers=hdrs, json=payload)
                d = resp.json()
                offers_post = d.get("offers", [])
                result["search_POST"] = {
                    "ok": resp.status_code == 200,
                    "status": resp.status_code,
                    "count": len(offers_post),
                    "body_preview": resp.text[:200] if resp.status_code != 200 else None,
                    "cheapest": {"id": offers_post[0]["id"], "price": offers_post[0].get("dph_total"), "loc": offers_post[0].get("geolocation")} if offers_post else None
                }
        except Exception as e:
            result["search_POST"] = {"ok": False, "error": str(e)}

        # Step 4: testa _find_best_offer() del manager
        if engine.router.vastai_manager:
            try:
                offer = await engine.router.vastai_manager._find_best_offer()
                result["manager_find_offer"] = {"ok": True, "offer": {"id": offer["id"], "price": offer.get("dph_total"), "loc": offer.get("geolocation")} if offer else None}
            except Exception as e:
                result["manager_find_offer"] = {"ok": False, "error": str(e), "type": type(e).__name__}

        return result

    @app.post("/api/restart")
    async def restart_server():
        """Riavvia IGRIS gracefully."""
        import asyncio, os, sys
        async def _do_restart():
            await asyncio.sleep(0.5)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        asyncio.ensure_future(_do_restart())
        return {"ok": True, "message": "Riavvio in corso..."}

    @app.post("/api/vastai/vps/start-sync")
    async def vps_start_sync():
        """Avvia VPS in modo SINCRONO - mostra errori direttamente."""
        if not engine.router.vastai_manager:
            return {"error": "manager non inizializzato"}
        m = engine.router.vastai_manager
        m.set_persistent(True)
        try:
            api_base = await m.ensure_ready()
            return {"ok": True, "api_base": api_base, "instance_id": m.state.instance_id, "status": m.state.status}
        except Exception as e:
            import traceback
            return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}

    @app.post("/api/vastai/vps/start")
    async def vps_start():
        """Avvia VPS GPU. Guard anti-duplicazione: se esiste gia' un'istanza la sincronizza."""
        if not engine.router.vastai_manager:
            return {"error": "Vast.ai non configurato"}
        m = engine.router.vastai_manager

        # Guard: se gia' in corso, ritorna stato attuale senza creare
        if m.state.status in ("provisioning", "running", "ready"):
            return {
                "ok": True,
                "synced": True,
                "status": m.state.status,
                "instance_id": m.state.instance_id,
                "message": f"Istanza gia' {m.state.status} — sincronizzato senza crearne un'altra"
            }

        m.set_persistent(True)

        import asyncio
        async def _provision_with_log():
            try:
                logger.info("VPS: avvio provisioning persistente...")
                api_base = await m.ensure_ready()
                logger.info(f"VPS: pronta su {api_base}")
            except RuntimeError as e:
                if "__PROVISIONING__" in str(e):
                    logger.info("VPS: provisioning gia' in corso, attendo")
                else:
                    logger.error(f"VPS provisioning FALLITO: {e}")
                    m.state.status = "error"
                    m.state.save()
            except Exception as e:
                import traceback
                logger.error(f"VPS provisioning FALLITO: {e}\n{traceback.format_exc()}")
                m.state.status = "error"
                m.state.save()

        asyncio.ensure_future(_provision_with_log())
        return {"ok": True, "synced": False, "status": "provisioning", "instance_id": m.state.instance_id}

    @app.post("/api/vastai/vps/stop")
    async def vps_stop():
        """Disattiva modalità VPS e distrugge l'istanza."""
        if not engine.router.vastai_manager:
            return {"error": "Vast.ai non configurato"}
        engine.router.vastai_manager.set_persistent(False)
        destroyed = await engine.router.vastai_manager.destroy()
        return {"ok": True, "destroyed": destroyed, "mode": "on_demand"}

    @app.get("/api/vastai/vps/status")
    async def vps_status():
        """Stato VPS: mode, istanza, costo stimato."""
        if not engine.router.vastai_manager:
            return {"mode": "not_configured", "persistent": False}
        m = engine.router.vastai_manager
        status = await m.get_status()
        status["mode"] = m.mode
        status["persistent"] = m.mode == "persistent"
        return status

    @app.get("/api/vastai/status")
    async def get_vastai_status():
        """Restituisce lo stato dell'istanza Vast.ai."""
        return await engine.router.get_vastai_status()

    @app.delete("/api/vastai/instance")
    async def destroy_vastai_instance():
        """Distrugge l'istanza Vast.ai corrente."""
        destroyed = await engine.router.destroy_vastai_instance()
        return {"destroyed": destroyed}

    @app.get("/api/dashboard")
    async def get_dashboard():
        """Dashboard stato completo di IGRIS."""
        from igris.core.system_context import get_system_context
        ctx = get_system_context()
        cost = engine.router.get_cost_summary()
        vastai_status = await engine.router.get_vastai_status() if engine.router.vastai_manager else {"status": "not_configured"}
        sessions_count = len(engine.sessions)
        memory = engine.memory.dump()
        return {
            "system": {
                "os": ctx["os"],
                "username": ctx["username"],
                "python": ctx["python_version"],
            },
            "llm": {
                "local_model": engine.router.local_config.model,
                "api_model": engine.router.api_config.model,
                "total_requests": cost["total_requests"],
                "total_cost_usd": cost["total_cost"],
            },
            "vastai": vastai_status,
            "sessions": sessions_count,
            "memory": {
                "user": memory.get("user", {}),
                "projects_count": len(memory.get("projects", {})),
                "learnings_count": len(memory.get("learnings", [])),
            },
        }

    @app.get("/api/memory")
    async def get_memory():
        """Restituisce la memoria operativa corrente."""
        return engine.memory.dump()

    @app.post("/api/memory")
    async def update_memory(data: dict):
        """Aggiorna la memoria operativa."""
        engine.memory.update(data)
        return {"ok": True}

    @app.delete("/api/memory")
    async def clear_memory():
        """Cancella la memoria operativa."""
        engine.memory.clear()
        return {"ok": True}

    @app.get("/api/extensions")
    async def list_extensions():
        """Lista le capacita' auto-installabili di IGRIS."""
        from igris.core.extensions import ExtensionManager
        mgr = ExtensionManager(config.workspace_root or ".")
        return {"capabilities": mgr.list_available()}

    @app.post("/api/extensions/{capability_id}/install")
    async def install_extension(capability_id: str):
        """Installa una capacita' (richiede autorizzazione per rischio medium/high)."""
        from igris.core.extensions import ExtensionManager
        mgr = ExtensionManager(config.workspace_root or ".")
        result = mgr.install(capability_id)
        return result

    @app.get("/api/extensions/{capability_id}/request")
    async def request_extension(capability_id: str, reason: str = "task richiesto dall'utente"):
        """Genera il messaggio di richiesta autorizzazione per una capacita'."""
        from igris.core.extensions import ExtensionManager
        mgr = ExtensionManager(config.workspace_root or ".")
        msg = mgr.generate_request_message(capability_id, reason)
        needs = mgr.needs_auth(capability_id)
        return {"message": msg, "needs_auth": needs, "capability_id": capability_id}

    @app.get("/api/status")
    async def get_status():
        return {
            "name": "IGRIS",
            "version": "0.1.0",
            "status": "running",
            "llm_local": {
                "provider": config.local_llm.provider,
                "model": config.local_llm.model,
                "url": config.local_llm.base_url,
            },
            "llm_fallback": {
                "provider": config.fallback_llm.provider,
                "model": config.fallback_llm.model,
            },
            "cost": engine.router.get_cost_summary(),
        }

    @app.get("/api/config")
    async def get_config():
        safe_config = config.model_dump()
        safe_config["fallback_llm"]["api_key"] = "***" if config.fallback_llm.api_key else ""
        safe_config["vastai"]["api_key"] = "***" if config.vastai.api_key else ""
        return safe_config

    @app.post("/api/run-benchmark")
    async def run_benchmark():
        """Lancia il benchmark LLM completo in background."""
        import subprocess
        from pathlib import Path
        repo   = Path("C:/Igris/repo/IGRIS_DEVIN")
        python = str(repo / ".venv" / "Scripts" / "python.exe")
        script = str(repo / "igris_llm_benchmark.py")
        out    = "C:/Users/Admin/Desktop/bench_live.txt"
        outfile = open(out, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [python, "-u", script],
            stdout=outfile, stderr=subprocess.STDOUT,
            cwd=str(repo),
        )
        return {"ok": True, "pid": proc.pid, "log": out}

    @app.get("/api/run-benchmark/status")
    async def benchmark_status():
        """Legge le ultime 20 righe del log benchmark live."""
        from pathlib import Path
        out = Path("C:/Users/Admin/Desktop/bench_live.txt")
        if not out.exists():
            return {"running": False, "lines": []}
        lines = out.read_text(encoding="utf-8", errors="ignore").splitlines()
        done = any("BENCHMARK COMPLETATO" in l for l in lines)
        return {"running": not done, "total_lines": len(lines),
                "last_20": lines[-20:], "done": done}

    return app


# Module-level ASGI app for uvicorn entrypoint
app = create_app()


def run_app(host: str = "0.0.0.0", port: int = 7778, reload: bool = False):
    """Run the ASGI app with uvicorn.

    Default host 0.0.0.0 and port 7778 to expose the server on the LAN.
    """
    import uvicorn
    # uvicorn.run accepts an ASGI app; pass the app directly
    uvicorn.run(app, host=host, port=port, reload=reload)
