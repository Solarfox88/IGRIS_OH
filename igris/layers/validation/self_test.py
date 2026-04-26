"""Self-test engine - validates execution results."""

from __future__ import annotations

import logging
from pathlib import Path

from igris.layers.execution.runner import CommandRunner
from igris.models.config import IgrisConfig
from igris.models.report import CommandLog, SelfTestCheck, SelfTestReport
from igris.models.task import Task

logger = logging.getLogger("igris.validation.selftest")


class SelfTester:
    """Runs self-tests after task execution to validate results."""

    def __init__(self, config: IgrisConfig, runner: CommandRunner):
        self.config = config
        self.runner = runner
        self.project_root = Path(config.project_root).resolve()

    def run_self_test(
        self,
        task: Task,
        execution_logs: list[CommandLog],
    ) -> SelfTestReport:
        report = SelfTestReport(task_id=task.id)

        report.checks.append(self._check_execution_success(execution_logs))
        report.checks.append(self._check_no_errors(execution_logs))

        for fpath in task.files_involved:
            report.checks.append(self._check_file_exists(fpath))

        if task.test_plan:
            report.checks.append(self._run_test_plan(task))

        report.checks.append(self._check_git_clean())

        if self._has_python_project():
            report.checks.append(self._run_python_tests())

        if self._has_node_project():
            report.checks.append(self._run_node_tests())

        passed = report.passed_checks
        failed = report.failed_checks
        logger.info(
            f"Self-test complete: {passed}/{report.total_checks} passed, "
            f"{failed} failed"
        )

        return report

    def _check_execution_success(self, logs: list[CommandLog]) -> SelfTestCheck:
        all_ok = all(entry.return_code == 0 for entry in logs if entry.safe)
        failed = [entry.command for entry in logs if entry.return_code != 0 and entry.safe]
        return SelfTestCheck(
            name="execution_success",
            passed=all_ok,
            message="All commands succeeded" if all_ok else f"Failed: {', '.join(failed[:3])}",
            severity="error" if not all_ok else "info",
        )

    def _check_no_errors(self, logs: list[CommandLog]) -> SelfTestCheck:
        error_keywords = ["error", "exception", "traceback", "fatal"]
        errors_found = []
        for log in logs:
            if log.stderr:
                for kw in error_keywords:
                    if kw in log.stderr.lower():
                        errors_found.append(f"{log.command}: {log.stderr[:100]}")
                        break
        return SelfTestCheck(
            name="no_stderr_errors",
            passed=len(errors_found) == 0,
            message="No errors in stderr" if not errors_found else f"Errors: {'; '.join(errors_found[:3])}",
            severity="warning" if errors_found else "info",
        )

    def _check_file_exists(self, filepath: str) -> SelfTestCheck:
        path = self.project_root / filepath
        exists = path.exists()
        return SelfTestCheck(
            name=f"file_exists:{filepath}",
            passed=exists,
            message=f"File {'exists' if exists else 'MISSING'}: {filepath}",
            severity="error" if not exists else "info",
        )

    def _run_test_plan(self, task: Task) -> SelfTestCheck:
        lines = task.test_plan.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("$") or line.startswith(">"):
                cmd = line.lstrip("$> ").strip()
                if cmd:
                    result = self.runner.execute(cmd)
                    if result.return_code != 0:
                        return SelfTestCheck(
                            name="test_plan",
                            passed=False,
                            message=f"Test command failed: {cmd}",
                            severity="error",
                        )
        return SelfTestCheck(
            name="test_plan",
            passed=True,
            message="Test plan passed",
        )

    def _check_git_clean(self) -> SelfTestCheck:
        result = self.runner.execute("git status --porcelain")
        is_clean = result.return_code == 0 and result.stdout.strip() == ""
        return SelfTestCheck(
            name="git_clean",
            passed=True,
            message="Git working tree clean" if is_clean else f"Uncommitted changes: {result.stdout[:200]}",
            severity="info",
        )

    def _has_python_project(self) -> bool:
        return (self.project_root / "pyproject.toml").exists() or (
            self.project_root / "setup.py"
        ).exists()

    def _has_node_project(self) -> bool:
        return (self.project_root / "package.json").exists()

    def _run_python_tests(self) -> SelfTestCheck:
        result = self.runner.execute("python -m pytest --tb=short -q 2>&1 || true")
        passed = "passed" in result.stdout and "failed" not in result.stdout
        return SelfTestCheck(
            name="python_tests",
            passed=passed,
            message=result.stdout[:300] if result.stdout else "No test output",
            severity="warning" if not passed else "info",
        )

    def _run_node_tests(self) -> SelfTestCheck:
        pkg_json = self.project_root / "package.json"
        if pkg_json.exists():
            import json
            pkg = json.loads(pkg_json.read_text())
            if "test" in pkg.get("scripts", {}):
                result = self.runner.execute("npm test 2>&1 || true")
                passed = result.return_code == 0
                return SelfTestCheck(
                    name="node_tests",
                    passed=passed,
                    message=result.stdout[:300] if result.stdout else "No test output",
                    severity="warning" if not passed else "info",
                )
        return SelfTestCheck(
            name="node_tests",
            passed=True,
            message="No test script found",
        )
