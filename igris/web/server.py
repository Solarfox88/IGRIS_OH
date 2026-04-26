"""FastAPI web server for IGRIS chat interface."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

    return app
