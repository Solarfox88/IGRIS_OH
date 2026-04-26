"""Diagnostics engine - identifies system-level issues."""

from __future__ import annotations

import logging
from typing import Any

from igris.models.state import ProjectState
from igris.models.task import Task, TaskStatus

logger = logging.getLogger("igris.validation.diagnostics")


class DiagnosticResult:
    """Result of a diagnostic check."""

    def __init__(self, name: str, severity: str, message: str, suggestion: str = ""):
        self.name = name
        self.severity = severity
        self.message = message
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
        }


class Diagnostics:
    """Runs diagnostic checks on the agent's operational state."""

    def run_full_diagnostic(
        self,
        state: ProjectState,
        tasks: list[Task],
    ) -> list[DiagnosticResult]:
        results: list[DiagnosticResult] = []

        results.extend(self._check_task_starvation(state, tasks))
        results.extend(self._check_loop_patterns(state))
        results.extend(self._check_blocked_accumulation(tasks))
        results.extend(self._check_family_health(state))
        results.extend(self._check_recovery_escalation(state))

        for r in results:
            if r.severity in {"error", "critical"}:
                logger.warning(f"Diagnostic [{r.severity}] {r.name}: {r.message}")

        return results

    def _check_task_starvation(
        self, state: ProjectState, tasks: list[Task]
    ) -> list[DiagnosticResult]:
        results = []
        active = [t for t in tasks if t.status in {TaskStatus.NEW, TaskStatus.IN_PROGRESS}]
        if not active:
            results.append(DiagnosticResult(
                name="task_starvation",
                severity="error",
                message="No active tasks available. Agent has no work to do.",
                suggestion="Trigger teacher recovery or create new tasks from project analysis.",
            ))
        return results

    def _check_loop_patterns(self, state: ProjectState) -> list[DiagnosticResult]:
        results = []
        recovery = state.recovery

        if recovery.consecutive_observation_like >= 3:
            results.append(DiagnosticResult(
                name="observation_loop",
                severity="error",
                message=f"Observation loop detected: {recovery.consecutive_observation_like} consecutive observation-like tasks.",
                suggestion="Force strategy shift to code_implementation, bug_fix, or testing.",
            ))

        sat = state.saturation.get_summary()
        if len(sat["saturated_families"]) > 3:
            results.append(DiagnosticResult(
                name="mass_saturation",
                severity="warning",
                message=f"{len(sat['saturated_families'])} families saturated. Running out of options.",
                suggestion="Reset oldest saturated families or create novel task types.",
            ))

        return results

    def _check_blocked_accumulation(self, tasks: list[Task]) -> list[DiagnosticResult]:
        results = []
        blocked = [t for t in tasks if t.status == TaskStatus.BLOCKED]
        active = [t for t in tasks if t.status in {TaskStatus.NEW, TaskStatus.IN_PROGRESS}]

        if len(blocked) > len(active) and len(blocked) > 2:
            results.append(DiagnosticResult(
                name="blocked_accumulation",
                severity="warning",
                message=f"More blocked tasks ({len(blocked)}) than active ({len(active)}).",
                suggestion="Investigate and resolve blockers before creating new tasks.",
            ))
        return results

    def _check_family_health(self, state: ProjectState) -> list[DiagnosticResult]:
        results = []
        for key, metrics in state.saturation.families.items():
            if metrics.failed_count > 2:
                results.append(DiagnosticResult(
                    name=f"family_failing:{key}",
                    severity="warning",
                    message=f"Family '{key}' has {metrics.failed_count} failures.",
                    suggestion=f"Avoid family '{key}' or investigate root cause.",
                ))
        return results

    def _check_recovery_escalation(self, state: ProjectState) -> list[DiagnosticResult]:
        results = []
        if state.recovery.escalation_count > 5:
            results.append(DiagnosticResult(
                name="excessive_escalation",
                severity="error",
                message=f"Agent has escalated {state.recovery.escalation_count} times. Recovery is not working.",
                suggestion="Reset recovery state or manually intervene with specific task assignment.",
            ))
        return results

    def get_summary(
        self, results: list[DiagnosticResult]
    ) -> dict[str, Any]:
        return {
            "total_checks": len(results),
            "critical": sum(1 for r in results if r.severity == "critical"),
            "errors": sum(1 for r in results if r.severity == "error"),
            "warnings": sum(1 for r in results if r.severity == "warning"),
            "issues": [r.to_dict() for r in results if r.severity in {"critical", "error"}],
        }
