"""Project context reader - scans and understands repository state."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from igris.models.config import IgrisConfig
from igris.models.state import ProjectState
from igris.models.task import Task, TaskStatus

logger = logging.getLogger("igris.context")


class ProjectReader:
    """Reads and builds project context from the repository."""

    IMPORTANT_FILES = [
        "README.md", "CONTRIBUTING.md", "pyproject.toml", "package.json",
        "Cargo.toml", "Makefile", "Dockerfile", "docker-compose.yml",
        "requirements.txt", "setup.py", "setup.cfg", ".gitignore",
        "tsconfig.json", "go.mod", "pom.xml", "build.gradle",
    ]

    IGNORED_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".eggs", "*.egg-info", ".igris",
    }

    def __init__(self, config: IgrisConfig):
        self.config = config
        self.root = Path(config.project_root).resolve()

    def read_project_state(self) -> ProjectState:
        state = ProjectState(
            project_name=self.config.project_name,
            project_root=str(self.root),
        )
        state.key_files = self._find_key_files()
        state.recent_commits = self._read_recent_commits()
        state.current_branch = self._read_current_branch()

        tasks = self._load_all_tasks()
        state.active_tasks = [t.id for t in tasks if t.status in {TaskStatus.NEW, TaskStatus.IN_PROGRESS}]
        state.blocked_tasks = [t.id for t in tasks if t.status == TaskStatus.BLOCKED]
        state.completed_tasks = [t.id for t in tasks if t.status == TaskStatus.COMPLETED]

        state.project_health = self._assess_health(tasks)
        return state

    def _find_key_files(self) -> list[str]:
        found = []
        for name in self.IMPORTANT_FILES:
            path = self.root / name
            if path.exists():
                found.append(name)
        return found

    def _read_recent_commits(self, count: int = 10) -> list[str]:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "log", "--oneline", f"-{count}"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")
        except Exception:
            pass
        return []

    def _read_current_branch(self) -> str:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    def _load_all_tasks(self) -> list[Task]:
        tasks_dir = self.root / self.config.tasks_dir
        if not tasks_dir.exists():
            return []
        tasks = []
        for task_file in tasks_dir.glob("*.json"):
            try:
                tasks.append(Task.load(task_file))
            except Exception as e:
                logger.warning(f"Failed to load task {task_file}: {e}")
        return tasks

    def _assess_health(self, tasks: list[Task]) -> str:
        if not tasks:
            return "no_tasks"
        blocked = sum(1 for t in tasks if t.status == TaskStatus.BLOCKED)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        active = sum(1 for t in tasks if t.status in {TaskStatus.NEW, TaskStatus.IN_PROGRESS})
        if blocked > active:
            return "blocked"
        if failed > 3:
            return "failing"
        if active == 0:
            return "idle"
        return "healthy"

    def read_file_content(self, relative_path: str, max_chars: int = 5000) -> str:
        path = self.root / relative_path
        if not path.exists():
            return ""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return content[:max_chars]
        except Exception:
            return ""

    def get_directory_tree(self, max_depth: int = 3) -> str:
        lines: list[str] = []
        self._walk_tree(self.root, "", max_depth, 0, lines)
        return "\n".join(lines[:200])

    def _walk_tree(self, path: Path, prefix: str, max_depth: int, depth: int, lines: list[str]) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        dirs = [e for e in entries if e.is_dir() and e.name not in self.IGNORED_DIRS]
        files = [e for e in entries if e.is_file()]

        for f in files[:20]:
            lines.append(f"{prefix}{f.name}")

        for d in dirs[:10]:
            lines.append(f"{prefix}{d.name}/")
            self._walk_tree(d, prefix + "  ", max_depth, depth + 1, lines)

    def get_recent_reports(self, count: int = 5) -> list[dict]:
        reports_dir = self.root / self.config.reports_dir
        if not reports_dir.exists():
            return []
        report_files = sorted(reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        reports = []
        for rf in report_files[:count]:
            try:
                reports.append(json.loads(rf.read_text(encoding="utf-8")))
            except Exception:
                pass
        return reports

    def build_context_summary(self, max_tokens: int = 4000) -> str:
        state = self.read_project_state()
        tree = self.get_directory_tree(max_depth=2)
        readme = self.read_file_content("README.md", max_chars=2000)

        summary = f"""## Project: {state.project_name}
**Root:** {state.project_root}
**Branch:** {state.current_branch}
**Health:** {state.project_health}
**Key files:** {', '.join(state.key_files)}

### Active tasks: {len(state.active_tasks)}
### Blocked tasks: {len(state.blocked_tasks)}
### Completed tasks: {len(state.completed_tasks)}

### Recent commits:
{chr(10).join(state.recent_commits[:5])}

### Directory structure:
```
{tree[:1500]}
```

### README (excerpt):
{readme[:1000]}
"""
        return summary[:max_tokens * 4]
