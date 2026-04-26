"""State tracking models for IGRIS agent."""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, Field

from igris.models.task import TaskFamily


class FamilyMetrics(BaseModel):
    """Metrics tracked per task family."""

    family: TaskFamily
    total_executions: int = 0
    consecutive_executions: int = 0
    last_execution_time: float = 0.0
    blocked_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    is_saturated: bool = False
    saturated_at: float | None = None
    cooldown_until: float | None = None


class FamilySaturationState(BaseModel):
    """Tracks family saturation across the entire project."""

    families: dict[str, FamilyMetrics] = Field(default_factory=dict)
    global_cycle_count: int = 0
    last_strategy_shift_at: int = 0

    def record_execution(self, family: TaskFamily, max_reps: int = 3) -> None:
        key = family.value
        if key not in self.families:
            self.families[key] = FamilyMetrics(family=family)

        metrics = self.families[key]
        metrics.total_executions += 1
        metrics.consecutive_executions += 1
        metrics.last_execution_time = time.time()

        if metrics.consecutive_executions >= max_reps:
            metrics.is_saturated = True
            metrics.saturated_at = time.time()

        for other_key, other_metrics in self.families.items():
            if other_key != key:
                other_metrics.consecutive_executions = 0

        self.global_cycle_count += 1

    def record_completion(self, family: TaskFamily) -> None:
        key = family.value
        if key in self.families:
            self.families[key].completed_count += 1

    def record_failure(self, family: TaskFamily) -> None:
        key = family.value
        if key in self.families:
            self.families[key].failed_count += 1

    def record_blocked(self, family: TaskFamily) -> None:
        key = family.value
        if key in self.families:
            self.families[key].blocked_count += 1

    def is_family_saturated(self, family: TaskFamily) -> bool:
        key = family.value
        if key not in self.families:
            return False
        metrics = self.families[key]
        if metrics.cooldown_until and time.time() < metrics.cooldown_until:
            return True
        return metrics.is_saturated

    def reset_family(self, family: TaskFamily, cooldown_cycles: int = 5) -> None:
        key = family.value
        if key in self.families:
            metrics = self.families[key]
            metrics.is_saturated = False
            metrics.consecutive_executions = 0
            metrics.cooldown_until = time.time() + (cooldown_cycles * 60)

    def get_available_families(self) -> list[TaskFamily]:
        saturated = {
            TaskFamily(k)
            for k, v in self.families.items()
            if v.is_saturated
        }
        return [f for f in TaskFamily if f not in saturated]

    def get_blocked_families(self) -> list[TaskFamily]:
        return [
            TaskFamily(k)
            for k, v in self.families.items()
            if v.blocked_count > 0
        ]

    def get_summary(self) -> dict:
        return {
            "global_cycle_count": self.global_cycle_count,
            "saturated_families": [
                k for k, v in self.families.items() if v.is_saturated
            ],
            "blocked_families": [
                k for k, v in self.families.items() if v.blocked_count > 0
            ],
            "family_counts": {
                k: v.total_executions for k, v in self.families.items()
            },
        }


class RecoveryPattern(BaseModel):
    """Tracks recovery patterns for anti-loop detection."""

    recent_teacher_assignments: list[str] = Field(default_factory=list)
    observation_like_count: int = 0
    consecutive_observation_like: int = 0
    last_teacher_family: str = ""
    escalation_count: int = 0
    last_escalation_time: float = 0.0
    recovery_history: list[dict] = Field(default_factory=list)

    def record_teacher_assignment(self, family: str, task_title: str) -> None:
        self.recent_teacher_assignments.append(f"{family}:{task_title}")
        if len(self.recent_teacher_assignments) > 20:
            self.recent_teacher_assignments = self.recent_teacher_assignments[-20:]
        self.last_teacher_family = family

    def record_observation_like(self) -> None:
        self.observation_like_count += 1
        self.consecutive_observation_like += 1

    def record_non_observation(self) -> None:
        self.consecutive_observation_like = 0

    def record_escalation(self) -> None:
        self.escalation_count += 1
        self.last_escalation_time = time.time()


class ProjectState(BaseModel):
    """Complete project state snapshot."""

    project_name: str = ""
    project_root: str = "."
    last_updated: float = Field(default_factory=time.time)
    current_branch: str = "main"
    recent_commits: list[str] = Field(default_factory=list)
    active_tasks: list[str] = Field(default_factory=list)
    blocked_tasks: list[str] = Field(default_factory=list)
    completed_tasks: list[str] = Field(default_factory=list)
    saturation: FamilySaturationState = Field(default_factory=FamilySaturationState)
    recovery: RecoveryPattern = Field(default_factory=RecoveryPattern)
    key_files: list[str] = Field(default_factory=list)
    project_health: str = "unknown"
    strategic_notes: list[str] = Field(default_factory=list)

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "project_state.json"
        self.last_updated = time.time()
        path.write_text(json.dumps(self.model_dump(), indent=2, default=str), encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory: Path) -> ProjectState:
        path = directory / "project_state.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        return cls()
