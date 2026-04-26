"""Teacher module - diagnoses blockers and assigns remediation tasks."""

from __future__ import annotations

import json
import logging

from igris.layers.advisory.router import LLMRouter
from igris.models.config import IgrisConfig
from igris.models.state import ProjectState
from igris.models.task import Task, TaskFamily, TaskPriority, TaskRisk, TaskStatus

logger = logging.getLogger("igris.teacher")

TEACHER_SYSTEM_PROMPT = """You are the TEACHER module of IGRIS, an autonomous AI engineering agent.

Your role is to diagnose WHY the agent is stuck and assign EXACTLY ONE remediation task
that will help the agent recover autonomy and make real forward progress.

You are NOT a chatbot. You are a strict supervisor that:
1. Diagnoses the root cause of the blockage
2. Assigns one specific, actionable remediation task
3. Ensures the task breaks the current loop pattern
4. Never assigns tasks in saturated families
5. Never assigns observation-like tasks if the agent is in an observation loop

You MUST respond with valid JSON:
{
  "diagnosis": "clear description of why the agent is stuck",
  "root_cause": "the fundamental reason for the blockage",
  "remediation_task": {
    "title": "specific actionable task title",
    "description": "exactly what to do",
    "family": "task family (must NOT be saturated)",
    "priority": "high",
    "risk": "safe|low",
    "execution_strategy": "step-by-step execution plan",
    "success_criteria": "how to verify this worked",
    "test_plan": "how to test",
    "rollback_plan": "how to undo",
    "why_this_task": "why this specific task will break the loop",
    "files_involved": [],
    "commands": []
  },
  "strategy_shift": "what fundamental approach change is needed",
  "expected_outcome": "what should happen after this task completes"
}

RULES:
- The remediation task must be LOCAL and SAFE
- It must NOT be in a saturated family
- It must NOT repeat what the agent already tried
- It must produce a CONCRETE deliverable (file, commit, test result)
- If pure observation won't help, assign code_implementation, bug_fix, or testing
- Be SPECIFIC: include file paths, commands, concrete actions
- The goal is to restore the agent's autonomy, not to do the agent's work
"""


class TeacherPayload:
    """Rich context payload for the teacher."""

    def __init__(
        self,
        project_context: str,
        state: ProjectState,
        tasks: list[Task],
        recent_reports: list[dict],
    ):
        self.project_context = project_context
        self.state = state
        self.tasks = tasks
        self.recent_reports = recent_reports

    def to_prompt(self) -> str:
        sat = self.state.saturation.get_summary()
        recovery = self.state.recovery

        active = [t for t in self.tasks if t.status in {TaskStatus.NEW, TaskStatus.IN_PROGRESS}]
        blocked = [t for t in self.tasks if t.status == TaskStatus.BLOCKED]
        failed = [t for t in self.tasks if t.status == TaskStatus.FAILED]

        family_detail = ""
        for family_key, metrics in self.state.saturation.families.items():
            family_detail += (
                f"\n  {family_key}: total={metrics.total_executions}, "
                f"consecutive={metrics.consecutive_executions}, "
                f"blocked={metrics.blocked_count}, "
                f"saturated={metrics.is_saturated}"
            )

        reports_text = ""
        for r in self.recent_reports[:3]:
            reports_text += f"\n  - {r.get('task_title', 'unknown')}: success={r.get('success', False)}, outcome={r.get('outcome', '')[:100]}"

        return f"""## Teacher Diagnosis Request

### Project Context
{self.project_context[:3000]}

### Current State
- Health: {self.state.project_health}
- Branch: {self.state.current_branch}
- Global cycle count: {sat['global_cycle_count']}

### Task Inventory
- Active tasks: {len(active)}
- Blocked tasks: {len(blocked)}
- Failed tasks: {len(failed)}

Active tasks:
{chr(10).join(f'  - [{t.family.value}] {t.title}' for t in active[:5])}

Blocked tasks:
{chr(10).join(f'  - [{t.family.value}] {t.title}: {t.blocked_reason}' for t in blocked[:5])}

Failed tasks:
{chr(10).join(f'  - [{t.family.value}] {t.title}: {t.outcome[:80]}' for t in failed[:5])}

### Family Metrics{family_detail}

### Saturation
- Saturated families (DO NOT assign these): {', '.join(sat['saturated_families']) or 'none'}
- Blocked families: {', '.join(sat['blocked_families']) or 'none'}

### Recovery Pattern
- Observation-like count: {recovery.observation_like_count}
- Consecutive observation-like: {recovery.consecutive_observation_like}
- Recent teacher assignments: {', '.join(recovery.recent_teacher_assignments[-5:]) or 'none'}
- Last teacher family: {recovery.last_teacher_family or 'none'}
- Escalation count: {recovery.escalation_count}

### Recent Reports{reports_text}

### Policy
- DO NOT assign tasks in saturated families
- DO NOT assign observation-like tasks if consecutive_observation_like >= 2
- The task MUST be local, safe, and produce a concrete deliverable
- The task MUST break the current pattern
- Prefer: code_implementation, bug_fix, testing, patch_strategy, deployment
- Avoid: observation, synthesis, school_report (unless genuinely needed)

What is wrong and what EXACTLY should the agent do next?
"""


class Teacher:
    """Diagnoses blockers and assigns remediation tasks."""

    def __init__(self, config: IgrisConfig, router: LLMRouter):
        self.config = config
        self.router = router
        self.assignment_count = 0

    async def diagnose_and_assign(
        self,
        project_context: str,
        state: ProjectState,
        tasks: list[Task],
        recent_reports: list[dict] | None = None,
    ) -> Task | None:
        payload = TeacherPayload(
            project_context=project_context,
            state=state,
            tasks=tasks,
            recent_reports=recent_reports or [],
        )

        try:
            response = await self.router.query(
                prompt=payload.to_prompt(),
                system_prompt=TEACHER_SYSTEM_PROMPT,
            )
            result = self._parse_teacher_response(response.content)
            if not result:
                logger.error("Teacher response could not be parsed")
                return self._generate_fallback_task(state)

            task = self._result_to_task(result)
            if task:
                if state.saturation.is_family_saturated(task.family):
                    logger.warning(
                        f"Teacher assigned saturated family {task.family.value}, "
                        f"forcing strategy shift"
                    )
                    task = self._force_strategy_shift(task, state)

                self.assignment_count += 1
                state.recovery.record_teacher_assignment(
                    task.family.value, task.title
                )
                logger.info(
                    f"Teacher assigned: [{task.family.value}] {task.title}"
                )
                return task

        except Exception as e:
            logger.error(f"Teacher failed: {e}")

        return self._generate_fallback_task(state)

    def _parse_teacher_response(self, content: str) -> dict | None:
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
        return None

    def _result_to_task(self, result: dict) -> Task | None:
        task_data = result.get("remediation_task", {})
        if not task_data or not task_data.get("title"):
            return None

        family_str = task_data.get("family", "remediation")
        try:
            family = TaskFamily(family_str)
        except ValueError:
            family = TaskFamily.REMEDIATION

        return Task(
            title=task_data["title"],
            description=task_data.get("description", ""),
            family=family,
            priority=TaskPriority.HIGH,
            risk=TaskRisk(task_data.get("risk", "low")),
            execution_strategy=task_data.get("execution_strategy", ""),
            success_criteria=task_data.get("success_criteria", ""),
            test_plan=task_data.get("test_plan", ""),
            rollback_plan=task_data.get("rollback_plan", ""),
            files_involved=task_data.get("files_involved", []),
            commands=task_data.get("commands", []),
            source="teacher",
        )

    def _force_strategy_shift(self, task: Task, state: ProjectState) -> Task:
        available = state.saturation.get_available_families()
        preferred = [
            TaskFamily.CODE_IMPLEMENTATION,
            TaskFamily.BUG_FIX,
            TaskFamily.TESTING,
            TaskFamily.PATCH_STRATEGY,
            TaskFamily.DEPLOYMENT,
        ]
        for fam in preferred:
            if fam in available:
                task.family = fam
                logger.info(f"Strategy shift: reassigned to {fam.value}")
                return task
        for fam in available:
            if not Task(title="", family=fam).is_observation_like:
                task.family = fam
                return task
        return task

    def _generate_fallback_task(self, state: ProjectState) -> Task:
        available = state.saturation.get_available_families()
        family = TaskFamily.CODE_IMPLEMENTATION
        for fam in [TaskFamily.CODE_IMPLEMENTATION, TaskFamily.BUG_FIX, TaskFamily.TESTING]:
            if fam in available:
                family = fam
                break

        return Task(
            title="Identify and implement the most impactful improvement",
            description=(
                "The teacher could not determine a specific task. "
                "Review the project state, pick the single most impactful "
                "concrete action, and execute it. Produce a commit."
            ),
            family=family,
            priority=TaskPriority.HIGH,
            risk=TaskRisk.LOW,
            execution_strategy="1. Read project files\n2. Identify gap\n3. Implement fix\n4. Test\n5. Commit",
            success_criteria="A meaningful commit that advances the project",
            source="teacher_fallback",
        )
