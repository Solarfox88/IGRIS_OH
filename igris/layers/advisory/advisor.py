"""Advisory engine - generates task advisories from LLM."""

from __future__ import annotations

import json
import logging
from typing import Any

from igris.layers.advisory.router import LLMResponse, LLMRouter
from igris.models.config import IgrisConfig
from igris.models.state import ProjectState
from igris.models.task import Task, TaskFamily, TaskPriority, TaskRisk

logger = logging.getLogger("igris.advisory")

ADVISORY_SYSTEM_PROMPT = """You are the advisory engine for IGRIS, an autonomous AI engineering agent.
Your role is to analyze the current project state and recommend the single best next task.

You MUST respond with valid JSON containing:
{
  "best_next_task": {
    "title": "concise task title",
    "description": "what to do and why",
    "family": "one of the task families",
    "priority": "critical|high|medium|low",
    "risk": "safe|low|medium|high",
    "execution_strategy": "step-by-step how to execute",
    "success_criteria": "how to verify it worked",
    "test_plan": "how to test the result",
    "rollback_plan": "how to undo if it fails",
    "files_involved": ["list", "of", "files"],
    "commands": ["list", "of", "commands"]
  },
  "reasoning": "why this is the best next task",
  "blocked_analysis": "what is currently blocking progress",
  "alternative_tasks": [{"title": "...", "family": "...", "why_not": "..."}]
}

Task families: observation, synthesis, repo_diff_discovery, patch_strategy,
branch_pr_plan, review_gate, candidate_materialization, mastery_cycle,
mastery_gate, school_report, grading_diagnosis, stabilization_audit,
code_implementation, bug_fix, testing, documentation, refactoring,
deployment, remediation, other

Rules:
- Prefer actionable tasks over observation-like tasks
- Do NOT suggest tasks in saturated families
- The task must produce REAL forward progress
- Be specific: include actual file paths, commands, and success criteria
- If the project needs code, suggest code_implementation or bug_fix
- If the project is stuck, suggest remediation with a concrete strategy shift
"""


class Advisory:
    """Contains a parsed advisory from the LLM."""

    def __init__(self, raw: dict[str, Any], response: LLMResponse):
        self.raw = raw
        self.response = response
        self.best_task_data = raw.get("best_next_task", {})
        self.reasoning = raw.get("reasoning", "")
        self.blocked_analysis = raw.get("blocked_analysis", "")
        self.alternatives = raw.get("alternative_tasks", [])

    def to_task(self) -> Task | None:
        if not self.best_task_data:
            return None
        try:
            family_str = self.best_task_data.get("family", "other")
            try:
                family = TaskFamily(family_str)
            except ValueError:
                family = TaskFamily.OTHER

            priority_str = self.best_task_data.get("priority", "medium")
            try:
                priority = TaskPriority(priority_str)
            except ValueError:
                priority = TaskPriority.MEDIUM

            risk_str = self.best_task_data.get("risk", "low")
            try:
                risk = TaskRisk(risk_str)
            except ValueError:
                risk = TaskRisk.LOW

            return Task(
                title=self.best_task_data.get("title", "Untitled advisory task"),
                description=self.best_task_data.get("description", ""),
                family=family,
                priority=priority,
                risk=risk,
                execution_strategy=self.best_task_data.get("execution_strategy", ""),
                success_criteria=self.best_task_data.get("success_criteria", ""),
                test_plan=self.best_task_data.get("test_plan", ""),
                rollback_plan=self.best_task_data.get("rollback_plan", ""),
                files_involved=self.best_task_data.get("files_involved", []),
                commands=self.best_task_data.get("commands", []),
                source="advisory",
            )
        except Exception as e:
            logger.error(f"Failed to convert advisory to task: {e}")
            return None


class Advisor:
    """Generates task advisories using LLM."""

    def __init__(self, config: IgrisConfig, router: LLMRouter):
        self.config = config
        self.router = router

    async def get_advisory(
        self,
        project_context: str,
        state: ProjectState,
        current_tasks: list[Task] | None = None,
    ) -> Advisory | None:
        prompt = self._build_advisory_prompt(project_context, state, current_tasks)

        try:
            response = await self.router.query(
                prompt=prompt,
                system_prompt=ADVISORY_SYSTEM_PROMPT,
            )
            parsed = self._parse_response(response.content)
            if parsed:
                return Advisory(parsed, response)
            logger.warning("Failed to parse advisory response")
            return None
        except Exception as e:
            logger.error(f"Advisory generation failed: {e}")
            return None

    def _build_advisory_prompt(
        self,
        project_context: str,
        state: ProjectState,
        current_tasks: list[Task] | None,
    ) -> str:
        saturation = state.saturation.get_summary()

        task_summary = ""
        if current_tasks:
            active = [t for t in current_tasks if t.is_actionable]
            blocked = [t for t in current_tasks if t.is_blocked]
            task_summary = f"""
### Current Tasks
Active ({len(active)}):
{chr(10).join(f'- [{t.family.value}] {t.title} (priority={t.priority.value})' for t in active[:10])}

Blocked ({len(blocked)}):
{chr(10).join(f'- [{t.family.value}] {t.title}: {t.blocked_reason}' for t in blocked[:5])}
"""

        return f"""## Current Project State

{project_context}

{task_summary}

### Saturation State
- Saturated families (DO NOT suggest these): {', '.join(saturation['saturated_families']) or 'none'}
- Blocked families: {', '.join(saturation['blocked_families']) or 'none'}
- Family execution counts: {json.dumps(saturation['family_counts'])}
- Total cycles: {saturation['global_cycle_count']}

### Recovery Pattern
- Consecutive observation-like tasks: {state.recovery.consecutive_observation_like}
- Recent teacher assignments: {', '.join(state.recovery.recent_teacher_assignments[-3:]) or 'none'}
- Escalation count: {state.recovery.escalation_count}

What is the single best next task to produce REAL forward progress?
"""

    def _parse_response(self, content: str) -> dict | None:
        content = content.strip()

        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            content = content[start:end].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        for i in range(len(content)):
            if content[i] == "{":
                brace_count = 0
                for j in range(i, len(content)):
                    if content[j] == "{":
                        brace_count += 1
                    elif content[j] == "}":
                        brace_count -= 1
                    if brace_count == 0:
                        try:
                            return json.loads(content[i : j + 1])
                        except json.JSONDecodeError:
                            break
                break

        logger.warning("Could not parse JSON from advisory response")
        return None
