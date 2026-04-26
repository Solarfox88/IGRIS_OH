"""Chat engine - manages conversations with IGRIS identity and REAL command execution."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

from igris.core.identity import get_chat_system_prompt
from igris.layers.advisory.router import LLMRouter
from igris.layers.execution.runner import CommandRunner
from igris.layers.git_layer.git_ops import GitOperations
from igris.models.config import IgrisConfig

logger = logging.getLogger("igris.chat")


class ChatMessage:
    """A single chat message."""

    def __init__(self, role: str, content: str, metadata: dict | None = None):
        self.id = str(uuid.uuid4())
        self.role = role
        self.content = content
        self.timestamp = time.time()
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class ChatSession:
    """A conversation session with IGRIS."""

    def __init__(self, session_id: str, project_name: str = ""):
        self.id = session_id
        self.project_name = project_name
        self.messages: list[ChatMessage] = []
        self.created_at = time.time()
        self.updated_at = time.time()
        self.title = ""

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> ChatMessage:
        msg = ChatMessage(role, content, metadata)
        self.messages.append(msg)
        self.updated_at = time.time()
        if not self.title and role == "user" and len(self.messages) <= 2:
            self.title = content[:60] + ("..." if len(content) > 60 else "")
        return msg

    def get_history(self, max_messages: int = 50) -> list[dict]:
        return [m.to_dict() for m in self.messages[-max_messages:]]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "title": self.title or "New Chat",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
        }

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.id}.json"
        data = {
            "id": self.id,
            "project_name": self.project_name,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ChatSession:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = cls(data["id"], data.get("project_name", ""))
        session.title = data.get("title", "")
        session.created_at = data.get("created_at", time.time())
        session.updated_at = data.get("updated_at", time.time())
        for msg_data in data.get("messages", []):
            msg = ChatMessage(msg_data["role"], msg_data["content"], msg_data.get("metadata"))
            msg.id = msg_data.get("id", str(uuid.uuid4()))
            msg.timestamp = msg_data.get("timestamp", time.time())
            session.messages.append(msg)
        return session


# Regex patterns for command/file extraction from LLM responses
CMD_PATTERN = re.compile(r'\[CMD\](.*?)\[/CMD\]', re.DOTALL)
WRITE_FILE_PATTERN = re.compile(
    r'\[WRITE_FILE\s+path=["\']([^"\']+)["\']\](.*?)\[/WRITE_FILE\]',
    re.DOTALL,
)


class ChatEngine:
    """Manages IGRIS chat conversations with REAL tool execution capabilities."""

    AUTONOMOUS_TRIGGERS = [
        "esegui", "fai", "crea", "implementa", "scrivi", "genera",
        "deploy", "pubblica", "lancia", "avvia", "correggi", "fixxa",
        "execute", "create", "implement", "write", "build", "run",
        "deploy", "fix", "generate", "start", "do it", "go",
        "installa", "install", "cancella", "delete", "rimuovi", "remove",
        "modifica", "modify", "aggiorna", "update", "apri", "open",
        "salva", "save", "compila", "compile", "testa", "test",
    ]

    def __init__(self, config: IgrisConfig):
        self.config = config
        self.router = LLMRouter(config)
        self.runner = CommandRunner(config)
        self.git = GitOperations(config, self.runner)
        self.sessions: dict[str, ChatSession] = {}
        self.projects: dict[str, list[str]] = {}
        self.data_dir = Path(config.workspace_root or ".") / ".igris" / "chats"
        self._load_sessions()

    def _load_sessions(self) -> None:
        if not self.data_dir.exists():
            return
        for f in self.data_dir.glob("*.json"):
            try:
                session = ChatSession.load(f)
                self.sessions[session.id] = session
                project = session.project_name or "__general__"
                if project not in self.projects:
                    self.projects[project] = []
                if session.id not in self.projects[project]:
                    self.projects[project].append(session.id)
            except Exception as e:
                logger.warning(f"Failed to load chat session {f}: {e}")

    def create_session(self, project_name: str = "") -> ChatSession:
        session_id = str(uuid.uuid4())
        session = ChatSession(session_id, project_name)
        self.sessions[session_id] = session

        project = project_name or "__general__"
        if project not in self.projects:
            self.projects[project] = []
        self.projects[project].append(session_id)

        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)

    def list_projects(self) -> list[dict]:
        result = []
        for project_name, session_ids in self.projects.items():
            sessions = []
            for sid in session_ids:
                s = self.sessions.get(sid)
                if s:
                    sessions.append(s.to_dict())
            sessions.sort(key=lambda x: x["updated_at"], reverse=True)
            result.append({
                "name": project_name if project_name != "__general__" else "General",
                "sessions": sessions,
            })
        result.sort(key=lambda x: x["name"])
        return result

    async def send_message(self, session_id: str, content: str) -> ChatMessage:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        session.add_message("user", content)

        is_autonomous = self._detect_autonomous_mode(content)

        # Build full conversation history for context
        llm_messages = self._build_llm_messages(session, is_autonomous)

        try:
            # Send full history to LLM
            response = await self.router.query(
                prompt=content,
                system_prompt="",
                messages=llm_messages,
            )

            raw_response = response.content
            executed_actions = []

            # Parse and execute [WRITE_FILE] blocks
            write_matches = list(WRITE_FILE_PATTERN.finditer(raw_response))
            for match in write_matches:
                file_path = match.group(1).strip()
                file_content = match.group(2).strip()
                result = self._write_file(file_path, file_content)
                executed_actions.append(result)

            # Parse and execute [CMD] blocks
            cmd_matches = list(CMD_PATTERN.finditer(raw_response))
            for match in cmd_matches:
                command = match.group(1).strip()
                if command:
                    result = self._execute_command(command)
                    executed_actions.append(result)

            # Build final response content
            display_content = self._build_display_content(raw_response, executed_actions)

            metadata = {
                "model": response.model,
                "tier": response.tier.value,
                "tokens": response.tokens_used,
                "cost": response.cost,
                "latency": round(response.latency, 2),
                "autonomous": is_autonomous,
            }
            if executed_actions:
                metadata["actions_executed"] = len(executed_actions)
                metadata["actions"] = executed_actions

            assistant_msg = session.add_message("assistant", display_content, metadata)

        except Exception as e:
            logger.error(f"Chat query failed: {e}")
            assistant_msg = session.add_message(
                "assistant",
                f"Mi dispiace, c'è stato un errore: {str(e)}. "
                "Controlla che Ollama sia in esecuzione (`ollama serve`).",
                metadata={"error": str(e)},
            )

        session.save(self.data_dir)
        return assistant_msg

    def _write_file(self, file_path: str, content: str) -> dict:
        """Actually write a file to disk."""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            logger.info(f"File written: {file_path} ({len(content)} bytes)")
            return {
                "type": "write_file",
                "path": file_path,
                "success": True,
                "size": len(content),
                "message": f"File creato: {file_path}",
            }
        except Exception as e:
            logger.error(f"Failed to write file {file_path}: {e}")
            return {
                "type": "write_file",
                "path": file_path,
                "success": False,
                "error": str(e),
                "message": f"Errore nella creazione del file: {e}",
            }

    def _execute_command(self, command: str) -> dict:
        """Actually execute a command via CommandRunner."""
        try:
            log = self.runner.execute(command, cwd=str(self.config.project_root))
            success = log.return_code == 0
            output = log.stdout or ""
            error = log.stderr or ""
            logger.info(f"Command executed: {command} -> rc={log.return_code}")
            return {
                "type": "command",
                "command": command,
                "success": success,
                "return_code": log.return_code,
                "stdout": output[:5000],
                "stderr": error[:2000],
                "duration": log.duration_seconds,
                "message": f"$ {command}\n{output[:2000]}" + (f"\nERROR: {error[:500]}" if error and not success else ""),
            }
        except Exception as e:
            logger.error(f"Failed to execute command {command}: {e}")
            return {
                "type": "command",
                "command": command,
                "success": False,
                "error": str(e),
                "message": f"Errore nell'esecuzione: {e}",
            }

    def _build_display_content(self, raw_response: str, executed_actions: list[dict]) -> str:
        """Build the final display content by replacing tags with execution results."""
        display = raw_response

        # Replace [WRITE_FILE] blocks with results
        for action in executed_actions:
            if action["type"] == "write_file":
                if action["success"]:
                    icon = "📄"
                    status = f'{icon} **File creato:** `{action["path"]}` ({action["size"]} bytes)'
                else:
                    icon = "❌"
                    status = f'{icon} **Errore file:** {action.get("error", "errore sconosciuto")}'

                # Replace the WRITE_FILE block in the display
                pattern = re.compile(
                    r'\[WRITE_FILE\s+path=["\']' + re.escape(action["path"]) + r'["\']\].*?\[/WRITE_FILE\]',
                    re.DOTALL,
                )
                display = pattern.sub(status, display, count=1)

        # Replace [CMD] blocks with results
        for action in executed_actions:
            if action["type"] == "command":
                cmd = action["command"]
                if action["success"]:
                    stdout = action.get("stdout", "").strip()
                    result_text = f'```\n$ {cmd}\n{stdout}\n```' if stdout else f'```\n$ {cmd}\n(completato)\n```'
                else:
                    stderr = action.get("stderr", "").strip()
                    result_text = f'```\n$ {cmd}\nERRORE (rc={action.get("return_code", "?")}):\n{stderr}\n```'

                # Escape special regex characters in the command
                escaped_cmd = re.escape(cmd)
                pattern = re.compile(r'\[CMD\]' + escaped_cmd + r'\[/CMD\]', re.DOTALL)
                display = pattern.sub(result_text, display, count=1)

        # Clean up any remaining tags that weren't matched
        display = CMD_PATTERN.sub(lambda m: f'```\n$ {m.group(1).strip()}\n```', display)
        display = WRITE_FILE_PATTERN.sub(
            lambda m: f'📄 File: `{m.group(1)}`', display
        )

        return display.strip()

    def _build_llm_messages(self, session: ChatSession, is_autonomous: bool = False) -> list[dict]:
        """Build full message history for LLM, including system prompt."""
        system_prompt = get_chat_system_prompt()
        if session.project_name:
            system_prompt += f"\n\nProgetto corrente: {session.project_name}"

        # Detect OS from config or environment
        if os.name == "nt":
            system_prompt += "\n\nSistema operativo: Windows"
        else:
            system_prompt += "\n\nSistema operativo: " + os.uname().sysname

        if is_autonomous:
            system_prompt += (
                "\n\n**MODALITA' AUTONOMA ATTIVA**: L'utente vuole che tu ESEGUA. "
                "Usa i tag [CMD] e [WRITE_FILE] per eseguire le azioni richieste. "
                "NON descrivere cosa faresti — FALLO usando i tag."
            )

        messages = [{"role": "system", "content": system_prompt}]

        # Include conversation history (last 20 messages for context window management)
        for msg in session.messages[-20:]:
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    def _detect_autonomous_mode(self, content: str) -> bool:
        content_lower = content.lower().strip()
        for trigger in self.AUTONOMOUS_TRIGGERS:
            if trigger in content_lower:
                return True
        return False

    def delete_session(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if not session:
            return False
        project = session.project_name or "__general__"
        if project in self.projects and session_id in self.projects[project]:
            self.projects[project].remove(session_id)
        path = self.data_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
        return True
