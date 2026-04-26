"""Robust Git operations layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from igris.layers.execution.runner import CommandRunner
from igris.models.config import IgrisConfig
from igris.models.report import CommandLog

logger = logging.getLogger("igris.git")


@dataclass
class GitResult:
    """Result of a git operation."""

    success: bool
    message: str
    logs: list[CommandLog] = field(default_factory=list)


class GitOperations:
    """Robust git operations with conflict awareness and auto-recovery."""

    def __init__(self, config: IgrisConfig, runner: CommandRunner):
        self.config = config
        self.runner = runner
        self.project_root = Path(config.project_root).resolve()

    def status(self) -> GitResult:
        log = self.runner.execute("git status --porcelain")
        return GitResult(
            success=log.return_code == 0,
            message=log.stdout,
            logs=[log],
        )

    def current_branch(self) -> str:
        log = self.runner.execute("git branch --show-current")
        if log.return_code == 0:
            return log.stdout.strip()
        return "unknown"

    def has_changes(self) -> bool:
        result = self.status()
        return bool(result.message.strip())

    def add_all(self) -> GitResult:
        log = self.runner.execute("git add -A")
        return GitResult(
            success=log.return_code == 0,
            message="All changes staged" if log.return_code == 0 else log.stderr,
            logs=[log],
        )

    def add_files(self, files: list[str]) -> GitResult:
        if not files:
            return self.add_all()
        cmd = "git add " + " ".join(f'"{f}"' for f in files)
        log = self.runner.execute(cmd)
        return GitResult(
            success=log.return_code == 0,
            message=f"Staged {len(files)} files" if log.return_code == 0 else log.stderr,
            logs=[log],
        )

    def commit(self, message: str) -> GitResult:
        if not self.has_changes():
            return GitResult(success=True, message="Nothing to commit")

        self.add_all()
        log = self.runner.execute(f'git commit -m "{message}"')
        return GitResult(
            success=log.return_code == 0,
            message=log.stdout if log.return_code == 0 else log.stderr,
            logs=[log],
        )

    def safe_push(self, branch: str | None = None) -> GitResult:
        """Push with pre-push pull --rebase for safety."""
        logs: list[CommandLog] = []

        target = branch or self.current_branch()
        if target == "unknown":
            return GitResult(success=False, message="Cannot determine current branch")

        rebase_log = self.runner.execute(f"git pull --rebase origin {target} 2>&1 || true")
        logs.append(rebase_log)

        if "CONFLICT" in rebase_log.stdout or "CONFLICT" in rebase_log.stderr:
            abort_log = self.runner.execute("git rebase --abort")
            logs.append(abort_log)
            return GitResult(
                success=False,
                message="Rebase conflict detected. Aborted rebase. Manual resolution needed.",
                logs=logs,
            )

        push_log = self.runner.execute(f"git push origin {target}")
        logs.append(push_log)

        if push_log.return_code != 0:
            if "rejected" in push_log.stderr.lower():
                logger.warning("Push rejected, attempting force-with-lease")
                force_log = self.runner.execute(f"git push --force-with-lease origin {target}")
                logs.append(force_log)
                return GitResult(
                    success=force_log.return_code == 0,
                    message="Force-push succeeded" if force_log.return_code == 0 else force_log.stderr,
                    logs=logs,
                )
            return GitResult(
                success=False,
                message=f"Push failed: {push_log.stderr}",
                logs=logs,
            )

        return GitResult(
            success=True,
            message=f"Successfully pushed to {target}",
            logs=logs,
        )

    def create_branch(self, name: str) -> GitResult:
        log = self.runner.execute(f"git checkout -b {name}")
        return GitResult(
            success=log.return_code == 0,
            message=f"Created branch {name}" if log.return_code == 0 else log.stderr,
            logs=[log],
        )

    def checkout(self, branch: str) -> GitResult:
        log = self.runner.execute(f"git checkout {branch}")
        return GitResult(
            success=log.return_code == 0,
            message=f"Checked out {branch}" if log.return_code == 0 else log.stderr,
            logs=[log],
        )

    def get_recent_commits(self, count: int = 10) -> list[str]:
        log = self.runner.execute(f"git log --oneline -n {count}")
        if log.return_code == 0:
            return [line for line in log.stdout.strip().split("\n") if line]
        return []

    def get_diff_summary(self) -> str:
        log = self.runner.execute("git diff --stat")
        return log.stdout if log.return_code == 0 else ""

    def auto_commit(self, task_title: str = "") -> GitResult:
        """Automatic commit with sensible message."""
        if not self.has_changes():
            return GitResult(success=True, message="Nothing to commit")

        diff_log = self.runner.execute("git diff --stat")
        files_changed = diff_log.stdout.strip().split("\n")[-1] if diff_log.stdout.strip() else "changes"

        if task_title:
            msg = f"igris: {task_title[:60]}"
        else:
            msg = f"igris: auto-commit ({files_changed.strip()})"

        return self.commit(msg)

    def safe_commit_and_push(self, message: str) -> GitResult:
        """Full commit + push workflow."""
        commit_result = self.commit(message)
        if not commit_result.success and "Nothing to commit" not in commit_result.message:
            return commit_result

        if self.config.auto_push:
            push_result = self.safe_push()
            return GitResult(
                success=push_result.success,
                message=f"Commit: {commit_result.message} | Push: {push_result.message}",
                logs=commit_result.logs + push_result.logs,
            )

        return commit_result
