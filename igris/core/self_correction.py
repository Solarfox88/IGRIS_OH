"""
IGRIS Self-Correction Engine.

Quando IGRIS esegue comandi e ottiene errori, questo modulo:
1. Analizza il pattern di errore
2. Capisce COSA sta sbagliando (approccio, non solo sintassi)
3. Si auto-corregge e riprova automaticamente
4. Se non riesce, si auto-implementa la capacita' mancante

Principio: IGRIS non deve mai restituire una lista di errori all'utente
senza prima aver tentato di risolverli autonomamente.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("igris.self_correction")


@dataclass
class ErrorContext:
    """Contesto completo di un errore per l'analisi."""
    command: str
    stderr: str
    stdout: str
    return_code: int
    attempt: int = 1
    history: list[dict] = field(default_factory=list)  # tentativi precedenti


@dataclass
class CorrectionPlan:
    """Piano di auto-correzione generato dall'analisi."""
    strategy: str
    fixed_command: str | None
    explanation: str
    confidence: float  # 0.0 - 1.0
    needs_auth: bool = False
    auto_apply: bool = True  # se False, chiede all'utente


# ── Riconoscimento pattern di errore ad alto livello ──────────────────────

def diagnose(ctx: ErrorContext) -> CorrectionPlan:
    """
    Analizza il contesto dell'errore e produce un piano di correzione.
    Ordine: dal pattern piu' specifico al piu' generico.
    """
    err = (ctx.stderr + " " + ctx.stdout).lower()
    cmd = ctx.command.strip()

    # 1. RIGA-PER-RIGA: il sintomo piu' comune — comandi PS eseguiti in CMD
    #    Segnali: molti errori "non riconosciuto", tutti sulla stessa sessione
    if _is_line_by_line_ps_error(err, cmd):
        return _fix_line_by_line(cmd)

    # 2. SCRIPT MULTI-RIGA dentro [CMD] — salvalo e rieseguilo come file
    if _is_multiline_in_cmd(cmd):
        return _fix_multiline_as_file(cmd)

    # 3. CARTELLA GIA' ESISTENTE — non e' un errore vero
    if re.search(r"gi.* esistente|already exists|sottodirectory.*esiste", err, re.I):
        return CorrectionPlan(
            strategy="ignore_existing",
            fixed_command=None,
            explanation="Risorsa gia' esistente — non e' un errore",
            confidence=0.99,
            auto_apply=True,
        )

    # 4. PERCORSO NULL / variabile non espansa
    if re.search(r"null.*path|path.*null|impossibile.*null|binding.*null", err, re.I):
        return _fix_null_path(cmd)

    # 5. TIPO NON TROVATO (System.Windows.Forms, System.Drawing)
    if re.search(r"impossibile trovare il tipo|cannot find type|type.*not.*found", err, re.I):
        return _fix_missing_type(cmd)

    # 6. TERMINATORE STRINGA MANCANTE (here-string @" spezzata)
    if re.search(r"terminatore.*mancante|terminator.*expected|TerminatorExpectedAtEnd", err, re.I):
        return _fix_broken_herestring(cmd)

    # 7. PARENTESI/BLOCCO MANCANTE
    if re.search(r"parentesi.*mancante|curly.*mancante|MissingEndCurlyBrace|ParseError", err, re.I):
        return _fix_incomplete_block(cmd)

    # 8. ACCESSO NEGATO
    if re.search(r"accesso.*negato|access.*denied|permission denied", err, re.I):
        return CorrectionPlan(
            strategy="access_denied",
            fixed_command=None,
            explanation="Accesso negato — potrebbe richiedere privilegi admin",
            confidence=0.7,
            needs_auth=True,
            auto_apply=False,
        )

    # 9. EXECUTION POLICY
    if re.search(r"execution.?policy|script.*disab", err, re.I):
        return _fix_execution_policy(cmd)

    # 10. COMANDO NON TROVATO in CMD (PS eseguito come CMD)
    if re.search(r"non .* riconosciuto come comando|not recognized as.*command", err, re.I):
        return _fix_wrong_shell(cmd)

    # Fallback: prova a wrappare in PS se sembra PS
    from igris.layers.execution.runner import _is_powershell
    if _is_powershell(cmd) and return_code_is_bad(ctx):
        return _fix_wrap_powershell(cmd)

    return CorrectionPlan(
        strategy="unknown",
        fixed_command=None,
        explanation=f"Errore non classificato (rc={ctx.return_code}): {ctx.stderr[:80]}",
        confidence=0.0,
        auto_apply=False,
    )


def return_code_is_bad(ctx: ErrorContext) -> bool:
    return ctx.return_code not in (0,)


# ── Strategie di correzione ────────────────────────────────────────────────

def _is_line_by_line_ps_error(err: str, cmd: str) -> bool:
    """Rileva se l'errore e' causato da un singolo comando PS passato a CMD."""
    # Molti "non riconosciuto" sulla stessa riga = eseguito riga per riga
    hits = len(re.findall(r"non .* riconosciuto|not recognized", err, re.I))
    from igris.layers.execution.runner import _is_powershell
    return hits > 0 and _is_powershell(cmd)


def _is_multiline_in_cmd(cmd: str) -> bool:
    """Il comando contiene newline — e' uno script intero passato come comando."""
    lines = [l for l in cmd.splitlines() if l.strip()]
    return len(lines) >= 3


def _fix_line_by_line(cmd: str) -> CorrectionPlan:
    """Fix: wrappa in powershell.exe -EncodedCommand."""
    import base64
    encoded = base64.b64encode(cmd.encode("utf-16-le")).decode("ascii")
    fixed = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}'
    return CorrectionPlan(
        strategy="wrap_powershell_encoded",
        fixed_command=fixed,
        explanation="Comando PS eseguito in CMD — rilancio con powershell.exe -EncodedCommand",
        confidence=0.92,
        auto_apply=True,
    )


def _fix_multiline_as_file(cmd: str) -> CorrectionPlan:
    """Fix: salva script in file temporaneo ed esegui con -File."""
    # Non possiamo creare il file qui — segnaliamo al chiamante
    return CorrectionPlan(
        strategy="save_as_temp_file",
        fixed_command=cmd,  # il chiamante lo gestisce
        explanation="Script multi-riga — salvo in file .ps1 temporaneo ed eseguo con -File",
        confidence=0.95,
        auto_apply=True,
    )


def _fix_null_path(cmd: str) -> CorrectionPlan:
    """Fix: la variabile path era null — usa path letterale."""
    # Cerca percorsi hardcoded nel comando
    path_match = re.search(r'["\']?(C:[\\\/][^"\'\\s]+)["\']?', cmd)
    if path_match:
        path = path_match.group(1).replace('/', '\\')
        fixed = f'powershell.exe -Command "New-Item -ItemType Directory -Path \'{path}\' -Force"'
        return CorrectionPlan(
            strategy="fix_null_path",
            fixed_command=fixed,
            explanation=f"Variabile path era null — uso path letterale: {path}",
            confidence=0.75,
            auto_apply=True,
        )
    return CorrectionPlan(
        strategy="fix_null_path",
        fixed_command=None,
        explanation="Variabile path null — non riesco a estrarre il path",
        confidence=0.0,
        auto_apply=False,
    )


def _fix_missing_type(cmd: str) -> CorrectionPlan:
    """Fix: tipo .NET non trovato — aggiunge Add-Type prima del comando."""
    assemblies = []
    if "windows.forms" in cmd.lower():
        assemblies.append("System.Windows.Forms")
    if "system.drawing" in cmd.lower() or "drawing.size" in cmd.lower() or "drawing.point" in cmd.lower():
        assemblies.append("System.Drawing")
    if "system.net" in cmd.lower():
        assemblies.append("System.Net")

    if assemblies:
        prefix = "\n".join(f'Add-Type -AssemblyName "{a}"' for a in assemblies)
        fixed_script = prefix + "\n\n" + cmd
        import base64
        encoded = base64.b64encode(fixed_script.encode("utf-16-le")).decode("ascii")
        fixed = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}'
        return CorrectionPlan(
            strategy="add_missing_type",
            fixed_command=fixed,
            explanation=f"Assembly .NET mancanti — aggiungo: {', '.join(assemblies)}",
            confidence=0.88,
            auto_apply=True,
        )
    return CorrectionPlan(
        strategy="add_missing_type",
        fixed_command=None,
        explanation="Tipo .NET non trovato — assembly sconosciuto",
        confidence=0.0,
        auto_apply=False,
    )


def _fix_broken_herestring(cmd: str) -> CorrectionPlan:
    """Fix: here-string PS spezzata — il comando era stato tagliato a meta'."""
    # Il comando e' incompleto — non possiamo ripararlo, segnaliamo
    return CorrectionPlan(
        strategy="broken_herestring",
        fixed_command=None,
        explanation="Script PS incompleto (here-string @\" spezzata) — lo script deve essere eseguito come file completo",
        confidence=0.0,
        auto_apply=False,
    )


def _fix_incomplete_block(cmd: str) -> CorrectionPlan:
    """Fix: blocco {} incompleto — aggiunge parentesi mancanti."""
    opens = cmd.count('{')
    closes = cmd.count('}')
    if opens > closes:
        fixed = cmd + "\n}" * (opens - closes)
        import base64
        encoded = base64.b64encode(fixed.encode("utf-16-le")).decode("ascii")
        return CorrectionPlan(
            strategy="close_blocks",
            fixed_command=f'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}',
            explanation=f"Aggiungo {opens - closes} parentesi graffe mancanti",
            confidence=0.65,
            auto_apply=True,
        )
    return CorrectionPlan(
        strategy="incomplete_block",
        fixed_command=None,
        explanation="Blocco PS incompleto — impossibile riparare automaticamente",
        confidence=0.0,
        auto_apply=False,
    )


def _fix_execution_policy(cmd: str) -> CorrectionPlan:
    """Fix: ExecutionPolicy blocca lo script."""
    if "powershell" in cmd.lower():
        fixed = re.sub(r'powershell(\.exe)?', r'powershell.exe -ExecutionPolicy Bypass', cmd, count=1, flags=re.I)
    else:
        import base64
        encoded = base64.b64encode(cmd.encode("utf-16-le")).decode("ascii")
        fixed = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}'
    return CorrectionPlan(
        strategy="bypass_execution_policy",
        fixed_command=fixed,
        explanation="ExecutionPolicy blocca lo script — aggiungo -ExecutionPolicy Bypass",
        confidence=0.9,
        auto_apply=True,
    )


def _fix_wrong_shell(cmd: str) -> CorrectionPlan:
    """Fix: comando eseguito nel shell sbagliato."""
    from igris.layers.execution.runner import _is_powershell
    if _is_powershell(cmd):
        return _fix_wrap_powershell(cmd)
    return CorrectionPlan(
        strategy="wrong_shell",
        fixed_command=f'cmd /c {cmd}',
        explanation="Comando eseguito nel shell sbagliato — provo con cmd /c",
        confidence=0.5,
        auto_apply=True,
    )


def _fix_wrap_powershell(cmd: str) -> CorrectionPlan:
    import base64
    encoded = base64.b64encode(cmd.encode("utf-16-le")).decode("ascii")
    return CorrectionPlan(
        strategy="wrap_powershell",
        fixed_command=f'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}',
        explanation="Wrapping in PowerShell",
        confidence=0.8,
        auto_apply=True,
    )


# ── Loop di auto-correzione ────────────────────────────────────────────────

MAX_RETRIES = 3

def auto_correct_and_execute(
    command: str,
    runner_execute_fn,
    cwd: str,
    workspace_root: str = ".",
) -> dict:
    """
    Esegue un comando con loop di auto-correzione integrato.

    Flusso:
    1. Esegui comando
    2. Se fallisce, diagnosi l'errore
    3. Se c'e' un fix automatico applicabile, applicalo e riprova
    4. Dopo MAX_RETRIES fallimenti, ritorna il miglior risultato ottenuto
    5. Mostra all'utente cosa ha fatto (trasparenza)
    """
    import subprocess

    original_command = command
    attempts = []
    last_log = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"[AutoCorrect] Tentativo {attempt}/{MAX_RETRIES}: {command[:80]}")

        # Gestisci script multi-riga — salvali sempre come file temporaneo
        actual_cmd = command
        is_multiline = "\n" in command and len([l for l in command.splitlines() if l.strip()]) >= 3

        if is_multiline:
            from igris.layers.execution.runner import _is_powershell
            if _is_powershell(command):
                actual_cmd, cleanup = _save_temp_script(command, workspace_root, ".ps1")
                if actual_cmd:
                    actual_cmd = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{actual_cmd}"'
            else:
                actual_cmd, cleanup = _save_temp_script(command, workspace_root, ".sh")
                if actual_cmd:
                    actual_cmd = f'bash "{actual_cmd}"'
        else:
            cleanup = None

        # Esegui
        log = runner_execute_fn(actual_cmd, cwd=cwd)
        if cleanup:
            try: Path(cleanup).unlink()
            except: pass

        attempts.append({
            "attempt": attempt,
            "command": command[:120],
            "return_code": log.return_code,
            "stdout": (log.stdout or "")[:500],
            "stderr": (log.stderr or "")[:300],
        })
        last_log = log

        # Successo!
        if log.return_code == 0:
            note = ""
            if attempt > 1:
                note = f"\n⚙️ Auto-corretto al tentativo {attempt}/{MAX_RETRIES}"
            return _build_result(log, original_command, note, attempts, healed=(attempt > 1))

        # Analizza l'errore e pianifica correzione
        ctx = ErrorContext(
            command=command,
            stderr=log.stderr or "",
            stdout=log.stdout or "",
            return_code=log.return_code,
            attempt=attempt,
            history=attempts,
        )
        plan = diagnose(ctx)
        logger.info(f"[AutoCorrect] Diagnosi: {plan.strategy} (confidence={plan.confidence:.2f}) — {plan.explanation}")

        # Caso speciale: "ignore_existing" = successo mascherato
        if plan.strategy == "ignore_existing":
            log.return_code = 0
            return _build_result(log, original_command,
                "\n✅ Risorsa gia' esistente — continuo", attempts, healed=True)

        # Nessun fix disponibile o non auto-applicabile
        if not plan.auto_apply or not plan.fixed_command or plan.confidence < 0.5:
            break

        # Applica il fix e riprova
        logger.info(f"[AutoCorrect] Applico fix '{plan.strategy}' per tentativo {attempt + 1}")
        command = plan.fixed_command

    # Tutti i tentativi falliti
    healing_note = f"\n⚙️ Auto-correzione fallita dopo {len(attempts)} tentativi"
    if attempts:
        healing_note += f"\nUltimo errore: {(last_log.stderr or '')[:150]}"

    return _build_result(last_log, original_command, healing_note, attempts, healed=False)


def _save_temp_script(script: str, workspace_root: str, ext: str) -> tuple[str | None, str | None]:
    """Salva lo script in un file temporaneo. Ritorna (path, path_da_cancellare)."""
    try:
        tmp_dir = Path(workspace_root) / ".igris" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        path = tmp_dir / f"igris_autocorrect_{int(time.time() * 1000)}{ext}"
        path.write_text(script, encoding="utf-8")
        logger.info(f"[AutoCorrect] Script salvato: {path}")
        return str(path), str(path)
    except Exception as e:
        logger.error(f"[AutoCorrect] Errore salvataggio script temp: {e}")
        return None, None


def _build_result(log, original_command: str, note: str, attempts: list, healed: bool) -> dict:
    """Costruisce il dict risultato standard."""
    success = log.return_code == 0
    output = (log.stdout or "").strip()
    error = (log.stderr or "").strip()

    msg = f"$ {original_command[:80]}\n{output[:2000]}"
    if error and not success:
        msg += f"\nERRORE: {error[:500]}"
    if note:
        msg += note

    return {
        "type": "command",
        "command": original_command[:80],
        "success": success,
        "return_code": log.return_code,
        "stdout": output[:5000],
        "stderr": error[:2000],
        "duration": getattr(log, "duration_seconds", 0),
        "healed": healed,
        "healing_note": note,
        "attempts": len(attempts),
        "message": msg,
    }
