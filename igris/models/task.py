"""Task data models for IGRIS agent."""

from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TaskFamily(str, Enum):
    """Classification families for tasks."""

    OBSERVATION = "observation"
    SYNTHESIS = "synthesis"
    REPO_DIFF_DISCOVERY = "repo_diff_discovery"
    PATCH_STRATEGY = "patch_strategy"
    BRANCH_PR_PLAN = "branch_pr_plan"
    REVIEW_GATE = "review_gate"
    CANDIDATE_MATERIALIZATION = "candidate_materialization"
    MASTERY_CYCLE = "mastery_cycle"
    MASTERY_GATE = "mastery_gate"
    SCHOOL_REPORT = "school_report"
    GRADING_DIAGNOSIS = "grading_diagnosis"
    STABILIZATION_AUDIT = "stabilization_audit"
    CODE_IMPLEMENTATION = "code_implementation"
    BUG_FIX = "bug_fix"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    REFACTORING = "refactoring"
    DEPLOYMENT = "deployment"
    REMEDIATION = "remediation"
    OTHER = "other"


class TaskStatus(str, Enum):
    """Task lifecycle states."""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskPriority(str, Enum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskRisk(str, Enum):
    """Risk assessment for task execution."""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"


class Task(BaseModel):
    """Core task model for IGRIS agent."""

    id: str = Field(default_factory=lambda: f"task-{int(time.time() * 1000)}")
    title: str
    description: str = ""
    family: TaskFamily = TaskFamily.OTHER
    status: TaskStatus = TaskStatus.NEW
    priority: TaskPriority = TaskPriority.MEDIUM
    risk: TaskRisk = TaskRisk.LOW
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    blocked_reason: str | None = None
    execution_count: int = 0
    max_retries: int = 3
    parent_task_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    files_involved: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    success_criteria: str = ""
    execution_strategy: str = ""
    test_plan: str = ""
    rollback_plan: str = ""
    outcome: str = ""
    semantic_hash: str = ""
    source: str = "manual"

    def model_post_init(self, __context: Any) -> None:
        if not self.semantic_hash:
            self.semantic_hash = self._compute_semantic_hash()

    def _compute_semantic_hash(self) -> str:
        content = f"{self.family.value}:{self.title.lower().strip()}:{self.description.lower().strip()[:200]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @property
    def is_observation_like(self) -> bool:
        return self.family in {
            TaskFamily.OBSERVATION,
            TaskFamily.SYNTHESIS,
            TaskFamily.REPO_DIFF_DISCOVERY,
            TaskFamily.SCHOOL_REPORT,
            TaskFamily.GRADING_DIAGNOSIS,
        }

    @property
    def is_actionable(self) -> bool:
        return self.status in {TaskStatus.NEW, TaskStatus.IN_PROGRESS} and self.risk != TaskRisk.DESTRUCTIVE

    @property
    def is_blocked(self) -> bool:
        return self.status == TaskStatus.BLOCKED

    def mark_in_progress(self) -> None:
        self.status = TaskStatus.IN_PROGRESS
        self.updated_at = time.time()
        self.execution_count += 1

    def mark_completed(self, outcome: str = "") -> None:
        self.status = TaskStatus.COMPLETED
        self.updated_at = time.time()
        self.completed_at = time.time()
        self.outcome = outcome

    def mark_blocked(self, reason: str) -> None:
        self.status = TaskStatus.BLOCKED
        self.blocked_reason = reason
        self.updated_at = time.time()

    def mark_failed(self, outcome: str = "") -> None:
        self.status = TaskStatus.FAILED
        self.updated_at = time.time()
        self.outcome = outcome

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.id}.json"
        path.write_text(json.dumps(self.model_dump(), indent=2, default=str), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> Task:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)
