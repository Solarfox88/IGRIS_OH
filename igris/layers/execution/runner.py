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
from igris.core.autohealing import analyze_error, build_fixed_command, format_healing_report

logger = logging.getLogger("igris.execution")

# Segnali che indicano un comando PowerShell
PS_SIGNALS = [
    "New-Item", "Set-Content", "Get-Content", "Add-Content",
    "Remove-Item", "Copy-Item", "Move-Item", "Rename-Item",
    "Write-Host", "Write-Output", "Write-Error", "Write-Warning",
    "Invoke-Expression", "Invoke-Command", "Invoke-WebRequest",
    "Start-Process", "Stop-Process", "Start-Service", "Stop-Service",
    "Start-Sleep", "Start-Job", "Wait-Job",
    "Get-Process", "Get-Service", "Get-EventLog", "Get-WinEvent",
    "Get-ADUser", "Get-ADComputer", "Get-ADGroup", "Set-ADUser",
    "Get-ChildItem", "Get-Item", "Get-ItemProperty", "Set-ItemProperty",
    "Get-NetAdapter", "Get-NetIPAddress", "Get-NetRoute",
    "Test-Path", "Test-Connection", "Test-NetConnection",
    "Split-Path", "Join-Path", "Resolve-Path",
    "Select-Object", "Where-Object", "ForEach-Object",
    "Sort-Object", "Group-Object", "Measure-Object",
    "Format-Table", "Format-List", "Out-File", "Out-Null",
    "Import-Module", "Export-Csv", "ConvertTo-Json", "ConvertFrom-Json",
    "New-Object", "Add-Type", "Register-ScheduledTask",
    "Get-BitLockerVolume", "Get-MpComputerStatus",
    "param(", "function ", "@{", '@"', "::new(",
    "[System.", "[Net.", "[IO.", "[Collections.",
    "-ExecutionPolicy", "-NoProfile", "-NonInteractive",
]


def _is_powershell(command: str) -> bool:
    """Ritorna True se il comando contiene sintassi PowerShell."""
    if command.strip().lower().startswith("powershell"):
        return True
    # Il segno $ da solo indica PS (variabili PS)
    # Ma solo se seguito da lettere (non $? o $! bash)
    import re
    if re.search(r'\$[A-Za-z_]', command):
        return True
    for sig in PS_SIGNALS:
        if sig in command:
            return True
    return False


class CommandRunner:
    """Esegue comandi in modo sicuro, rilevando automaticamente PS vs CMD."""

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
            return log

        work_dir = cwd or str(self.project_root)
        actual_timeout = timeout or self.safety.max_command_duration_seconds

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        logger.info(f"Executing: {command[:120]}")
        start = time.time()

        # Costruisci il comando corretto per la piattaforma
        if self.is_windows:
            final_cmd = self._build_windows_command(command)
        else:
            # Linux/Mac: bash diretto
            final_cmd = command

        try:
            if self.is_windows:
                result = subprocess.run(
                    final_cmd,
                    shell=True,
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=actual_timeout,
                    env=run_env,
                    encoding="utf-8",
                    errors="replace",
                )
            else:
                result = subprocess.run(
                    ["bash", "-c", final_cmd],
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
                logger.warning(f"Command failed (rc={result.returncode}): {command[:80]}")

                # ── AUTO-HEALING ──────────────────────────────────────
                healing = analyze_error(command, result.stderr, result.stdout, result.returncode)

                if healing.strategy == "ignore_already_exists":
                    # Non è un vero errore — risorsa già esistente
                    log.return_code = 0
                    log.stdout += "\n[auto-healing] Risorsa già esistente — ignorato"
                    log.healed = True

                elif not healing.needs_auth:
                    fixed = build_fixed_command(command, healing.strategy, result.stderr)
                    if fixed and fixed != command:
                        logger.info(f"Auto-healing: {healing.message} — retry con fix")
                        try:
                            retry = subprocess.run(
                                self._build_windows_command(fixed) if self.is_windows else fixed,
                                shell=True,
                                cwd=work_dir,
                                capture_output=True,
                                text=True,
                                timeout=actual_timeout,
                                env=run_env,
                                encoding="utf-8",
                                errors="replace",
                            )
                            if retry.returncode == 0:
                                log.return_code = 0
                                log.stdout = retry.stdout[:10000]
                                log.stderr = ""
                                log.healed = True
                                log.healing_note = format_healing_report(
                                    command, result.stderr, healing, fixed, True)
                                logger.info(f"Auto-healing RIUSCITO: {healing.message}")
                            else:
                                log.healing_note = format_healing_report(
                                    command, result.stderr, healing, fixed, False)
                        except Exception as heal_err:
                            logger.error(f"Auto-healing retry error: {heal_err}")
                else:
                    log.healing_note = format_healing_report(
                        command, result.stderr, healing, None, None)
                    log.needs_auth = True
                # ── /AUTO-HEALING ─────────────────────────────────────

            else:
                logger.info(f"Command succeeded in {duration:.1f}s: {command[:80]}")

        except subprocess.TimeoutExpired:
            duration = time.time() - start
            log = CommandLog(
                command=command,
                return_code=-2,
                stderr=f"TIMEOUT after {actual_timeout}s",
                duration_seconds=round(duration, 2),
                safe=True,
            )

        except Exception as e:
            duration = time.time() - start
            log = CommandLog(
                command=command,
                return_code=-3,
                stderr=str(e),
                duration_seconds=round(duration, 2),
                safe=True,
            )

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
                logger.warning(f"Stopping sequence after failed command: {cmd[:80]}")
                break
        return results

    def _build_windows_command(self, command: str) -> str:
        """
        Costruisce il comando Windows corretto:
        - Se e' PowerShell -> powershell.exe -Command "..."
        - Se e' CMD builtin -> cmd /c ...
        - Altrimenti -> diretto
        """
        cmd = command.strip()

        # Gia' wrappato esplicitamente
        if cmd.lower().startswith("powershell"):
            return cmd
        if cmd.lower().startswith("cmd /c") or cmd.lower().startswith("cmd.exe"):
            return cmd

        # Rilevamento PowerShell
        if _is_powershell(cmd):
            logger.debug(f"Detected PowerShell command, wrapping with powershell.exe")
            # Per comandi multi-riga o con virgolette complesse, usa -EncodedCommand
            import base64
            encoded = base64.b64encode(cmd.encode("utf-16-le")).decode("ascii")
            return f"powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"

        # CMD builtins
        CMD_BUILTINS = {
            "echo", "dir", "type", "copy", "move", "del", "rd", "md",
            "mkdir", "rmdir", "set", "cls", "color", "title", "ver",
            "cd", "pushd", "popd", "ren", "rename", "attrib", "find",
        }
        UNIX_TO_WIN = {
            "ls": "dir", "cat": "type", "rm": "del", "cp": "copy",
            "mv": "move", "touch": "type nul >>", "pwd": "cd",
            "clear": "cls", "which": "where",
        }

        base = cmd.split()[0].lower().split("/")[-1].split("\\")[-1]

        if base in UNIX_TO_WIN:
            rest = cmd[len(base):].strip()
            cmd = f"{UNIX_TO_WIN[base]} {rest}".strip()
            base = cmd.split()[0].lower()

        if base in CMD_BUILTINS:
            # Normalizza slash per cmd.exe
            cmd = cmd.replace('/', '\\')
            return f"cmd /c {cmd}"

        return cmd

    def _is_command_safe(self, command: str) -> bool:
        """Safety minima: blocca solo comandi distruttivi o accessi sensibili evidenti."""
        cmd_lower = command.lower().strip()

        hard_block_patterns = [
            "rm -rf /",
            "rm -fr /",
            "cat /etc/shadow",
            "type c:\windows\system32\config\sam",
            "format ",
            "mkfs",
            "dd if=",
            ":(){ :|:& };:",
        ]

        for pattern in hard_block_patterns:
            if pattern in cmd_lower:
                logger.warning(f"Command blocked by hard safety pattern: {pattern}")
                return False

        for blocked in self.safety.blocked_commands:
            if blocked and blocked.lower() in cmd_lower:
                logger.warning(f"Command matches blocked pattern: {blocked}")
                return False

        for blocked_path in self.safety.blocked_paths:
            if blocked_path and blocked_path.lower() in cmd_lower:
                logger.warning(f"Command references blocked path: {blocked_path}")
                return False

        if self.safety.sandbox_mode:
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
        succeeded = sum(1 for e in self.logs if e.return_code == 0)
        failed = sum(1 for e in self.logs if e.return_code != 0)
        blocked = sum(1 for e in self.logs if not e.safe)
        return {
            "total_commands": total,
            "succeeded": succeeded,
            "failed": failed,
            "blocked": blocked,
        }
