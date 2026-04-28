"""
Memoria operativa persistente di IGRIS.

Salva e recupera contesto tra sessioni:
- Identita' utente (nome, preferenze, progetti correnti)
- Contesto operativo (ultimo task, file modificati)
- Apprendimento (errori frequenti, pattern preferiti)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("igris.memory")

MEMORY_VERSION = 1


class OperationalMemory:
    """
    Memoria persistente di IGRIS tra sessioni.
    Salvata in .igris/memory/operational.json
    """

    def __init__(self, memory_dir: Path):
        self.path = memory_dir / "operational.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
                logger.debug(f"Memoria caricata: {len(self._data)} chiavi")
            except Exception as e:
                logger.warning(f"Errore caricamento memoria: {e}")
                self._data = {}

    def _save(self) -> None:
        try:
            self._data["_version"] = MEMORY_VERSION
            self._data["_updated_at"] = time.time()
            self.path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Errore salvataggio memoria: {e}")

    # ------------------------------------------------------------------ #
    #  API pubblica                                                        #
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def update(self, updates: dict) -> None:
        self._data.update(updates)
        self._save()

    def remember_user(self, info: dict) -> None:
        """Aggiorna le info sull'utente."""
        user = self._data.get("user", {})
        user.update(info)
        user["last_seen"] = time.time()
        self._data["user"] = user
        self._save()

    def remember_project(self, name: str, path: str, description: str = "") -> None:
        """Registra un progetto su cui si sta lavorando."""
        projects = self._data.get("projects", {})
        projects[name] = {
            "path": path,
            "description": description,
            "last_worked": time.time(),
        }
        self._data["projects"] = projects
        self._save()

    def add_learning(self, category: str, content: str) -> None:
        """Aggiunge un apprendimento (errore, pattern, preferenza)."""
        learnings = self._data.get("learnings", [])
        learnings.append({
            "category": category,
            "content": content,
            "timestamp": time.time(),
        })
        # Mantieni solo gli ultimi 50
        self._data["learnings"] = learnings[-50:]
        self._save()

    def get_context_summary(self) -> str:
        """
        Genera un riassunto del contesto per il system prompt.
        Chiamato all'inizio di ogni sessione.
        """
        lines = []

        user = self._data.get("user", {})
        if user.get("name"):
            lines.append(f"- Utente: {user['name']}")
        if user.get("preferences"):
            lines.append(f"- Preferenze: {user['preferences']}")

        projects = self._data.get("projects", {})
        if projects:
            recent = sorted(
                projects.items(),
                key=lambda x: x[1].get("last_worked", 0),
                reverse=True,
            )[:3]
            proj_list = ", ".join(f"{n} ({p['path']})" for n, p in recent)
            lines.append(f"- Progetti recenti: {proj_list}")

        last_task = self._data.get("last_task")
        if last_task:
            lines.append(f"- Ultimo task: {last_task}")

        learnings = self._data.get("learnings", [])
        if learnings:
            recent_l = [l["content"] for l in learnings[-3:]]
            lines.append(f"- Note operative: {'; '.join(recent_l)}")

        if not lines:
            return ""

        return "\n## Memoria Operativa\n" + "\n".join(lines)

    def set_last_task(self, task: str) -> None:
        self._data["last_task"] = task[:200]
        self._save()

    def clear(self) -> None:
        self._data = {}
        self._save()

    def dump(self) -> dict:
        return dict(self._data)
