"""Main autonomous execution loop for IGRIS."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from igris.layers.advisory.advisor import Advisor
from igris.layers.advisory.router import LLMRouter
from igris.layers.context.project_reader import ProjectReader
from igris.layers.execution.runner import CommandRunner
from igris.layers.git_layer.git_ops import GitOperations
from igris.layers.task.deduplicator import SemanticDeduplicator
from igris.layers.task.selector import TaskSelector
from igris.layers.teacher.teacher import Teacher
from igris.layers.validation.diagnostics import Diagnostics
from igris.layers.validation.self_test import SelfTester
from igris.models.config import IgrisConfig
from igris.models.report import ExecutionReport
from igris.models.state import ProjectState
from igris.models.task import Task

logger = logging.getLogger("igris.loop")


class LoopStatus:
    """Status of the autonomous loop."""

    def __init__(self):
        self.running = False
        self.cycle_count = 0
        self.current_task: Task | None = None
        self.last_outcome: str = ""
        self.errors: list[str] = []
        self.started_at: float = 0.0
        self.stopped_at: float | None = None
        self.stop_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "cycle_count": self.cycle_count,
            "current_task": self.current_task.title if self.current_task else None,
            "last_outcome": self.last_outcome,
            "errors": self.errors[-5:],
            "uptime_seconds": (time.time() - self.started_at) if self.started_at else 0,
        }


class AutonomousLoop:
    """The main autonomous execution loop.

    Workflow per cycle:
    1. Read project context
    2. Load and filter tasks
    3. Get advisory from LLM
    4. Select best task (respecting saturation/anti-loop)
    5. Execute task
    6. Run self-test
    7. Commit/push if needed
    8. Update state
    9. Check for loop patterns
    10. If no task: activate teacher recovery
    """

    def __init__(self, config: IgrisConfig):
        self.config = config
        self.runner = CommandRunner(config)
        self.router = LLMRouter(config)
        self.context = ProjectReader(config)
        self.selector = TaskSelector(config)
        self.deduplicator = SemanticDeduplicator(config.anti_loop.semantic_similarity_threshold)
        self.advisor = Advisor(config, self.router)
        self.teacher = Teacher(config, self.router)
        self.tester = SelfTester(config, self.runner)
        self.diagnostics = Diagnostics()
        self.git = GitOperations(config, self.runner)
        self.status = LoopStatus()
        self.state: ProjectState | None = None
        self._stop_requested = False
        self._callbacks: dict[str, list] = {
            "on_cycle_start": [],
            "on_cycle_end": [],
            "on_task_start": [],
            "on_task_end": [],
            "on_error": [],
            "on_stop": [],
        }

    def on(self, event: str, callback: Any) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, **kwargs: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(**kwargs)
            except Exception as e:
                logger.error(f"Callback error ({event}): {e}")

    def request_stop(self, reason: str = "user_requested") -> None:
        self._stop_requested = True
        self.status.stop_reason = reason
        logger.info(f"Stop requested: {reason}")

    async def run(self, max_cycles: int | None = None) -> LoopStatus:
        self.status.running = True
        self.status.started_at = time.time()
        self._stop_requested = False
        max_cycles = max_cycles or self.config.anti_loop.max_total_cycles

        logger.info(f"Autonomous loop starting (max_cycles={max_cycles})")

        try:
            while self.status.cycle_count < max_cycles and not self._stop_requested:
                await self._run_cycle()
                self.status.cycle_count += 1

                if self._stop_requested:
                    break

                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Loop crashed: {e}")
            self.status.errors.append(str(e))

        self.status.running = False
        self.status.stopped_at = time.time()
        if not self.status.stop_reason:
            self.status.stop_reason = "max_cycles_reached"

        logger.info(
            f"Loop stopped after {self.status.cycle_count} cycles: {self.status.stop_reason}"
        )
        self._emit("on_stop", status=self.status)
        return self.status

    async def run_single_task(self, task: Task) -> ExecutionReport:
        """Execute a single task outside the loop."""
        self.state = self.context.read_project_state()
        return await self._execute_task(task)

    async def _run_cycle(self) -> None:
        cycle_num = self.status.cycle_count + 1
        logger.info(f"=== Cycle {cycle_num} ===")
        self._emit("on_cycle_start", cycle=cycle_num)

        self.state = self.context.read_project_state()
        tasks = self._load_tasks()
        project_ctx = self.context.build_context_summary()

        task = await self._select_task(tasks, project_ctx)

        if not task:
            logger.warning("No task selected, activating teacher recovery")
            task = await self._teacher_recovery(project_ctx, tasks)

        if not task:
            logger.error("Teacher recovery failed to produce a task. Stopping.")
            self.request_stop("no_task_available")
            return

        report = await self._execute_task(task)

        self._update_state_after_execution(task, report)

        if self.config.auto_commit and report.files_modified:
            self.git.auto_commit(task.title)

        diag_results = self.diagnostics.run_full_diagnostic(self.state, tasks)
        if any(r.severity == "error" for r in diag_results):
            logger.warning("Diagnostics found errors, may need strategy shift")

        self._emit("on_cycle_end", cycle=cycle_num, task=task, report=report)

    def _load_tasks(self) -> list[Task]:
        tasks_dir = Path(self.config.project_root) / self.config.tasks_dir
        if not tasks_dir.exists():
            return []
        tasks = []
        for f in tasks_dir.glob("*.json"):
            try:
                tasks.append(Task.load(f))
            except Exception as e:
                logger.warning(f"Failed to load task {f}: {e}")
        return tasks

    async def _select_task(self, tasks: list[Task], project_ctx: str) -> Task | None:
        advisory = await self.advisor.get_advisory(project_ctx, self.state, tasks)

        advisory_task = None
        if advisory:
            advisory_task = advisory.to_task()
            if advisory_task:
                is_dup, existing = self.deduplicator.is_duplicate(advisory_task, tasks)
                if is_dup:
                    logger.info(f"Advisory task is duplicate of: {existing.title}")
                    advisory_task = None

        return self.selector.select_next_task(tasks, self.state, advisory_task)

    async def _teacher_recovery(
        self, project_ctx: str, tasks: list[Task]
    ) -> Task | None:
        self.state.recovery.record_escalation()
        reports = self.context.get_recent_reports()
        return await self.teacher.diagnose_and_assign(
            project_ctx, self.state, tasks, reports
        )

    async def _execute_task(self, task: Task) -> ExecutionReport:
        logger.info(f"Executing task: [{task.family.value}] {task.title}")
        self.status.current_task = task
        self._emit("on_task_start", task=task)

        task.mark_in_progress()
        report = ExecutionReport(
            task_id=task.id,
            task_title=task.title,
            task_family=task.family.value,
        )

        try:
            if task.commands:
                logs = self.runner.execute_sequence(task.commands, stop_on_error=True)
                report.commands_run.extend(logs)
                report.files_modified = task.files_involved

                all_ok = all(entry.return_code == 0 for entry in logs if entry.safe)
                if all_ok:
                    report.finalize(True, "All commands completed successfully")
                    task.mark_completed("Commands executed successfully")
                else:
                    failed_cmds = [entry.command for entry in logs if entry.return_code != 0]
                    report.finalize(False, f"Failed commands: {', '.join(failed_cmds)}")
                    task.mark_failed(f"Command failures: {', '.join(failed_cmds)}")

            elif task.execution_strategy:
                result = await self._execute_strategy(task)
                report.finalize(result["success"], result["outcome"])
                if result["success"]:
                    task.mark_completed(result["outcome"])
                else:
                    task.mark_failed(result["outcome"])

            else:
                report.finalize(False, "No commands or execution strategy defined")
                task.mark_blocked("No execution plan")

        except Exception as e:
            report.finalize(False, f"Execution error: {str(e)}")
            task.mark_failed(str(e))
            logger.error(f"Task execution failed: {e}")

        test_report = self.tester.run_self_test(task, report.commands_run)

        reports_dir = Path(self.config.project_root) / self.config.reports_dir
        report.save(reports_dir)
        test_report.save(reports_dir)

        tasks_dir = Path(self.config.project_root) / self.config.tasks_dir
        task.save(tasks_dir)

        self.status.current_task = None
        self.status.last_outcome = report.outcome
        self._emit("on_task_end", task=task, report=report, test_report=test_report)

        return report

    async def _execute_strategy(self, task: Task) -> dict:
        prompt = f"""Execute the following task and provide the result.

Task: {task.title}
Description: {task.description}
Strategy: {task.execution_strategy}
Success Criteria: {task.success_criteria}

Generate a list of shell commands to execute this task.
Respond with JSON: {{"commands": ["cmd1", "cmd2", ...], "explanation": "..."}}
"""
        try:
            response = await self.router.query(prompt)
            content = response.content
            if "```json" in content:
                start = content.index("```json") + 7
                end = content.index("```", start)
                content = content[start:end]
            data = json.loads(content)
            commands = data.get("commands", [])
            if commands:
                logs = self.runner.execute_sequence(commands, stop_on_error=True)
                all_ok = all(entry.return_code == 0 for entry in logs if entry.safe)
                return {
                    "success": all_ok,
                    "outcome": f"Executed {len(commands)} commands, all_ok={all_ok}",
                }
        except Exception as e:
            logger.error(f"Strategy execution failed: {e}")

        return {"success": False, "outcome": "Strategy execution failed"}

    def _update_state_after_execution(self, task: Task, report: ExecutionReport) -> None:
        if not self.state:
            return

        self.state.saturation.record_execution(
            task.family, self.config.anti_loop.max_family_repetitions
        )

        if report.success:
            self.state.saturation.record_completion(task.family)
        else:
            self.state.saturation.record_failure(task.family)

        if task.is_observation_like:
            self.state.recovery.record_observation_like()
        else:
            self.state.recovery.record_non_observation()

        if task.is_blocked:
            self.state.saturation.record_blocked(task.family)

        memory_dir = Path(self.config.project_root) / self.config.memory_dir
        self.state.save(memory_dir)
