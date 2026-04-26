"""Task selection engine with anti-loop and saturation awareness."""

from __future__ import annotations

import logging
import time

from igris.models.config import IgrisConfig
from igris.models.state import ProjectState
from igris.models.task import Task, TaskFamily, TaskPriority, TaskRisk

logger = logging.getLogger("igris.task.selector")


class TaskSelector:
    """Selects the best next task respecting saturation and anti-loop rules."""

    PRIORITY_SCORE = {
        TaskPriority.CRITICAL: 100,
        TaskPriority.HIGH: 75,
        TaskPriority.MEDIUM: 50,
        TaskPriority.LOW: 25,
    }

    def __init__(self, config: IgrisConfig):
        self.config = config
        self.anti_loop = config.anti_loop

    def select_next_task(
        self,
        tasks: list[Task],
        state: ProjectState,
        advisory_best: Task | None = None,
    ) -> Task | None:
        """Select the best next task from available candidates.

        Respects:
        - Advisory best-task fidelity (if advisory suggests a clear best, follow it)
        - Family saturation (don't repeat saturated families)
        - Anti-observation-loop (limit consecutive observation-like tasks)
        - Risk constraints
        - Priority scoring
        """
        eligible = self._filter_eligible(tasks, state)

        if not eligible:
            logger.warning("No eligible tasks found")
            return None

        if advisory_best and self._is_advisory_valid(advisory_best, state):
            logger.info(f"Following advisory best task: {advisory_best.title}")
            return advisory_best

        scored = [(t, self._score_task(t, state)) for t in eligible]
        scored.sort(key=lambda x: x[1], reverse=True)

        if scored:
            best = scored[0]
            logger.info(
                f"Selected task: {best[0].title} (score={best[1]:.1f}, family={best[0].family.value})"
            )
            return best[0]

        return None

    def _filter_eligible(self, tasks: list[Task], state: ProjectState) -> list[Task]:
        eligible = []
        for task in tasks:
            if not task.is_actionable:
                continue
            if task.risk == TaskRisk.DESTRUCTIVE:
                continue
            if task.execution_count >= task.max_retries:
                continue
            if state.saturation.is_family_saturated(task.family):
                logger.debug(f"Skipping saturated family task: {task.title}")
                continue
            if self._would_create_observation_loop(task, state):
                logger.debug(f"Skipping observation-like to prevent loop: {task.title}")
                continue
            eligible.append(task)
        return eligible

    def _is_advisory_valid(self, task: Task, state: ProjectState) -> bool:
        if task.risk == TaskRisk.DESTRUCTIVE:
            return False
        if state.saturation.is_family_saturated(task.family):
            return False
        if task.execution_count >= task.max_retries:
            return False
        return True

    def _would_create_observation_loop(self, task: Task, state: ProjectState) -> bool:
        if not task.is_observation_like:
            return False
        return state.recovery.consecutive_observation_like >= self.anti_loop.max_consecutive_observation_like

    def _score_task(self, task: Task, state: ProjectState) -> float:
        score = float(self.PRIORITY_SCORE.get(task.priority, 50))

        if not task.is_observation_like:
            score += 15.0

        family_key = task.family.value
        if family_key in state.saturation.families:
            metrics = state.saturation.families[family_key]
            penalty = metrics.consecutive_executions * 10.0
            score -= penalty

        if task.execution_count > 0:
            score -= task.execution_count * 20.0

        if task.family in {TaskFamily.CODE_IMPLEMENTATION, TaskFamily.BUG_FIX, TaskFamily.PATCH_STRATEGY}:
            score += 10.0

        age_hours = (time.time() - task.created_at) / 3600
        if age_hours > 24:
            score += 5.0

        return max(score, 0.0)

    def get_selection_explanation(
        self,
        tasks: list[Task],
        state: ProjectState,
    ) -> str:
        eligible = self._filter_eligible(tasks, state)
        scored = [(t, self._score_task(t, state)) for t in eligible]
        scored.sort(key=lambda x: x[1], reverse=True)

        lines = [f"Task selection analysis ({len(eligible)}/{len(tasks)} eligible):"]
        for task, score in scored[:10]:
            lines.append(
                f"  [{score:6.1f}] {task.family.value:25s} | {task.title[:50]}"
            )

        sat_summary = state.saturation.get_summary()
        if sat_summary["saturated_families"]:
            lines.append(f"  Saturated: {', '.join(sat_summary['saturated_families'])}")
        if sat_summary["blocked_families"]:
            lines.append(f"  Blocked: {', '.join(sat_summary['blocked_families'])}")

        return "\n".join(lines)
