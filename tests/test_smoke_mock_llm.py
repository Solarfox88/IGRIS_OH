import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _MockOllamaHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            messages = payload.get("messages") or []
            last = messages[-1].get("content", "") if messages else ""
            response = {"message": {"content": f"Mock reply to: {last}"}, "eval_count": 1}
            resp_bytes = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence the default HTTPServer logging to keep test output clean
        return


@pytest.fixture
def mock_ollama_server():
    """Start a local HTTP server bound to an ephemeral port and return its base URL."""
    server = HTTPServer(("127.0.0.1", 0), _MockOllamaHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"
    # Small pause to ensure server is ready
    time.sleep(0.05)
    try:
        yield base_url
    finally:
        server.shutdown()
        thread.join(timeout=1)


@pytest.mark.asyncio
async def test_chat_with_mock_ollama(mock_ollama_server, tmp_path):
    """Smoke test: ChatEngine should call the mock local LLM and return its reply.

    Uses tmp_path for project/workspace roots to avoid leaving artifacts in the repository.
    """
    from igris.core.chat_engine import ChatEngine
    from igris.models.config import IgrisConfig

    # Use an isolated temporary directory for project and workspace
    cfg = IgrisConfig.load_or_default(project_root=str(tmp_path))
    cfg.workspace_root = str(tmp_path)
    cfg.project_root = str(tmp_path)

    # Point local LLM to the mock server started by the fixture
    cfg.local_llm.provider = "ollama"
    cfg.local_llm.base_url = mock_ollama_server

    engine = ChatEngine(cfg)
    session = engine.create_session("smoke-test")

    try:
        assistant_msg = await engine.send_message(session.id, "Please create a test file")
        assert assistant_msg is not None
        assert "Mock reply to:" in assistant_msg.content
    finally:
        # Ensure we do not leave runtime artifacts in the workspace
        chats_dir = tmp_path / ".igris" / "chats"
        if chats_dir.exists():
            shutil.rmtree(tmp_path / ".igris")
