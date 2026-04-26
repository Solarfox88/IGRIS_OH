"""Report data models for IGRIS agent."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CommandLog(BaseModel):
    """Log of a single command execution."""

    command: str
    return_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    safe: bool = True


class ExecutionReport(BaseModel):
    """Report of a task execution cycle."""

    task_id: str
    task_title: str
    task_family: str
    started_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    success: bool = False
    outcome: str = ""
    commands_run: list[CommandLog] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    def finalize(self, success: bool, outcome: str) -> None:
        self.completed_at = time.time()
        self.success = success
        self.outcome = outcome

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        ts = int(self.started_at)
        path = directory / f"exec_report_{self.task_id}_{ts}.json"
        path.write_text(json.dumps(self.model_dump(), indent=2, default=str), encoding="utf-8")
        return path


class SelfTestCheck(BaseModel):
    """A single self-test check result."""

    name: str
    passed: bool
    message: str = ""
    severity: str = "info"


class SelfTestReport(BaseModel):
    """Self-test report after execution."""

    task_id: str
    timestamp: float = Field(default_factory=time.time)
    checks: list[SelfTestCheck] = Field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return len(self.checks)

    @property
    def passed_checks(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks) if self.checks else True

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        ts = int(self.timestamp)
        path = directory / f"selftest_{self.task_id}_{ts}.json"
        data = self.model_dump()
        data["summary"] = {
            "total": self.total_checks,
            "passed": self.passed_checks,
            "failed": self.failed_checks,
            "all_passed": self.all_passed,
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path

    def to_markdown(self) -> str:
        lines = [
            f"# Self-Test Report — {self.task_id}",
            "",
            f"**Total:** {self.total_checks} | **Passed:** {self.passed_checks} | **Failed:** {self.failed_checks}",
            "",
        ]
        for check in self.checks:
            icon = "PASS" if check.passed else "FAIL"
            lines.append(f"- [{icon}] {check.name}: {check.message}")
        return "\n".join(lines)
