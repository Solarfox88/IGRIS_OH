"""Safe command execution engine."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
from pathlib import Path

from igris.models.config import IgrisConfig
from igris.models.report import CommandLog

logger = logging.getLogger("igris.execution")


class CommandRunner:
    """Executes commands safely with logging and constraints."""

    def __init__(self, config: IgrisConfig):
        self.config = config
        self.safety = config.safety
        self.project_root = Path(config.project_root).resolve()
        self.logs: list[CommandLog] = []
        self.is_windows = platform.system() == "Windows"

    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandLog:
        if not self._is_command_safe(command):
            log = CommandLog(
                command=command,
                return_code=-1,
                stderr="BLOCKED: Command failed safety check",
                safe=False,
            )
            self.logs.append(log)
            logger.warning(f"Blocked unsafe command: {command}")
            return log

        work_dir = cwd or str(self.project_root)
        actual_timeout = timeout or self.safety.max_command_duration_seconds

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        logger.info(f"Executing: {command}")
        start = time.time()

        # On Windows, normalize shell-builtin commands that need cmd /c
        if self.is_windows:
            command = self._normalize_windows_command(command)

        try:
            if self.is_windows:
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=actual_timeout,
                    env=run_env,
                )
            else:
                result = subprocess.run(
                    ["bash", "-c", command],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=actual_timeout,
                    env=run_env,
                )

            duration = time.time() - start
            log = CommandLog(
                command=command,
                return_code=result.returncode,
                stdout=result.stdout[:10000],
                stderr=result.stderr[:10000],
                duration_seconds=round(duration, 2),
                safe=True,
            )

            if result.returncode != 0:
                logger.warning(
                    f"Command failed (rc={result.returncode}): {command}\n"
                    f"stderr: {result.stderr[:500]}"
                )
            else:
                logger.info(f"Command succeeded in {duration:.1f}s: {command}")

        except subprocess.TimeoutExpired:
            duration = time.time() - start
            log = CommandLog(
                command=command,
                return_code=-2,
                stderr=f"TIMEOUT after {actual_timeout}s",
                duration_seconds=round(duration, 2),
                safe=True,
            )
            logger.error(f"Command timed out: {command}")

        except Exception as e:
            duration = time.time() - start
            log = CommandLog(
                command=command,
                return_code=-3,
                stderr=str(e),
                duration_seconds=round(duration, 2),
                safe=True,
            )
            logger.error(f"Command error: {command} -> {e}")

        self.logs.append(log)
        return log

    def execute_sequence(
        self,
        commands: list[str],
        cwd: str | None = None,
        stop_on_error: bool = True,
    ) -> list[CommandLog]:
        results = []
        for cmd in commands:
            log = self.execute(cmd, cwd=cwd)
            results.append(log)
            if stop_on_error and log.return_code != 0:
                logger.warning(f"Stopping sequence after failed command: {cmd}")
                break
        return results

    def _normalize_windows_command(self, command: str) -> str:
        """Normalize commands for Windows cmd.exe compatibility.

        Some commands are shell builtins that only work via cmd /c on Windows.
        Also handles common cross-platform command translations.
        """
        cmd_stripped = command.strip()

        # Already wrapped — don't double-wrap
        if cmd_stripped.lower().startswith('cmd /c') or cmd_stripped.lower().startswith('cmd.exe'):
            return cmd_stripped

        # Commands that are cmd.exe builtins and need explicit shell invocation
        CMD_BUILTINS = {
            'echo', 'dir', 'type', 'copy', 'move', 'del', 'rd', 'md',
            'mkdir', 'rmdir', 'set', 'cls', 'color', 'title', 'ver',
            'cd', 'pushd', 'popd', 'ren', 'rename', 'attrib', 'find',
        }

        base_cmd = cmd_stripped.split()[0].lower().split('/')[-1].split('\\')[-1]

        # Cross-platform translations: Unix -> Windows
        UNIX_TO_WIN = {
            'ls':    'dir',
            'cat':   'type',
            'rm':    'del',
            'cp':    'copy',
            'mv':    'move',
            'touch': 'type nul >>',
            'pwd':   'cd',
            'clear': 'cls',
            'which': 'where',
        }

        if base_cmd in UNIX_TO_WIN:
            rest = cmd_stripped[len(base_cmd):].strip()
            win_cmd = UNIX_TO_WIN[base_cmd]
            command = f'{win_cmd} {rest}'.strip()
            cmd_stripped = command
            base_cmd = win_cmd.split()[0]

        # Wrap builtins with cmd /c so they work correctly
        if base_cmd in CMD_BUILTINS:
            return f'cmd /c {cmd_stripped}'

        return cmd_stripped

    def _is_command_safe(self, command: str) -> bool:
        cmd_lower = command.lower().strip()

        for blocked in self.safety.blocked_commands:
            if blocked.lower() in cmd_lower:
                logger.warning(f"Command matches blocked pattern: {blocked}")
                return False

        for blocked_path in self.safety.blocked_paths:
            if blocked_path.lower() in cmd_lower:
                logger.warning(f"Command references blocked path: {blocked_path}")
                return False

        if self.safety.sandbox_mode:
            base_cmd = cmd_lower.split()[0] if cmd_lower.split() else ""
            base_cmd = base_cmd.split("/")[-1].split("\\")[-1]
            if base_cmd not in [c.lower() for c in self.safety.allowed_commands]:
                logger.warning(f"Command not in allowed list (sandbox mode): {base_cmd}")
                return False

        return True

    def execute_python(
        self,
        script_path: str,
        args: list[str] | None = None,
        cwd: str | None = None,
    ) -> CommandLog:
        python_cmd = "python" if self.is_windows else "python3"
        cmd_parts = [python_cmd, script_path]
        if args:
            cmd_parts.extend(args)
        return self.execute(" ".join(cmd_parts), cwd=cwd)

    def get_logs_summary(self) -> dict:
        total = len(self.logs)
        succeeded = sum(1 for entry in self.logs if entry.return_code == 0)
        failed = sum(1 for entry in self.logs if entry.return_code != 0)
        blocked = sum(1 for entry in self.logs if not entry.safe)
        return {
            "total_commands": total,
            "succeeded": succeeded,
            "failed": failed,
            "blocked": blocked,
        }
