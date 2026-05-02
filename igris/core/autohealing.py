"""
Auto-healing engine per IGRIS.

Quando un comando fallisce, analizza l'errore e propone/esegue una correzione
automatica senza richiedere intervento dell'utente (se l'errore è noto),
oppure chiede autorizzazione per correzioni più invasive.

Pattern gestiti:
- Comando PS eseguito come CMD -> rilancia con powershell.exe
- Cartella già esistente -> ignora e continua
- File non trovato -> crea percorso mancante
- Permessi negati -> suggerisce run-as-admin
- Encoding errato -> riprova con encoding diverso
- Comando non trovato -> suggerisce alternativa
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("igris.autohealing")


@dataclass
class HealingResult:
    healed: bool
    strategy: str
    fixed_command: str | None = None
    message: str = ""
    needs_auth: bool = False  # True = chiede autorizzazione prima di eseguire


# ── Pattern di errore e relative strategie ────────────────────────────────

ERROR_PATTERNS = [
    # Comando PS eseguito in CMD (il più comune)
    {
        "match": [
            r"non .* riconosciuto come comando interno",
            r"is not recognized as",
            r"non è riconosciuto come",
        ],
        "strategy": "wrap_powershell",
        "needs_auth": False,
        "description": "Comando PowerShell eseguito in CMD — rilancio con powershell.exe",
    },
    # Cartella già esistente
    {
        "match": [
            r"sottodirectory o file .* gi.* esistente",
            r"already exists",
            r"esiste già",
            r"mkdir.*already",
        ],
        "strategy": "ignore_already_exists",
        "needs_auth": False,
        "description": "Cartella/file già esistente — ignoro e continuo",
    },
    # File o percorso non trovato
    {
        "match": [
            r"il percorso specificato non è stato trovato",
            r"cannot find path",
            r"path not found",
            r"no such file or directory",
            r"percorso.*non.*trovato",
        ],
        "strategy": "create_missing_path",
        "needs_auth": False,
        "description": "Percorso mancante — creo le cartelle intermedie",
    },
    # Permessi negati
    {
        "match": [
            r"access is denied",
            r"accesso negato",
            r"permission denied",
            r"privilegio non.*assegnato",
            r"PermissionError",
        ],
        "strategy": "suggest_admin",
        "needs_auth": True,
        "description": "Permessi insufficienti — suggerisco esecuzione come amministratore",
    },
    # ExecutionPolicy PowerShell
    {
        "match": [
            r"execution policy",
            r"executionpolicy",
            r"script.*disabled",
            r"non.*abilitato.*eseguire script",
        ],
        "strategy": "bypass_execution_policy",
        "needs_auth": False,
        "description": "ExecutionPolicy blocca lo script — aggiungo -ExecutionPolicy Bypass",
    },
    # Modulo non trovato
    {
        "match": [
            r"module.*not.*found",
            r"modulo.*non.*trovato",
            r"import-module.*error",
            r"The term.*is not recognized",
        ],
        "strategy": "install_module",
        "needs_auth": True,
        "description": "Modulo PowerShell mancante — propongo installazione",
    },
    # Timeout
    {
        "match": [
            r"TIMEOUT after",
            r"timed out",
            r"timeout",
        ],
        "strategy": "increase_timeout",
        "needs_auth": False,
        "description": "Timeout — riprovo con timeout maggiore",
    },
    # Encoding
    {
        "match": [
            r"UnicodeDecodeError",
            r"UnicodeEncodeError",
            r"codec.*encode",
            r"charmap.*undefined",
        ],
        "strategy": "fix_encoding",
        "needs_auth": False,
        "description": "Problema encoding — aggiungo -Encoding UTF8",
    },
]


def analyze_error(command: str, stderr: str, stdout: str, return_code: int) -> HealingResult:
    """
    Analizza un errore di comando e ritorna la strategia di healing.
    """
    error_text = (stderr + " " + stdout).lower()

    for pattern in ERROR_PATTERNS:
        for regex in pattern["match"]:
            if re.search(regex, error_text, re.IGNORECASE):
                return HealingResult(
                    healed=False,  # non ancora eseguito
                    strategy=pattern["strategy"],
                    needs_auth=pattern["needs_auth"],
                    message=pattern["description"],
                )

    # Errore non riconosciuto
    return HealingResult(
        healed=False,
        strategy="unknown",
        needs_auth=False,
        message=f"Errore non classificato (rc={return_code}): {stderr[:100]}",
    )


def build_fixed_command(
    original_command: str,
    strategy: str,
    stderr: str = "",
) -> str | None:
    """
    Costruisce il comando corretto in base alla strategia.
    Ritorna None se la strategia non produce un comando alternativo.
    """
    import base64

    if strategy == "wrap_powershell":
        # Rilancia con powershell.exe -EncodedCommand
        encoded = base64.b64encode(original_command.encode("utf-16-le")).decode("ascii")
        return f"powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"

    elif strategy == "bypass_execution_policy":
        # Aggiungi bypass se non c'è già
        if "-ExecutionPolicy" not in original_command:
            cmd = original_command.strip()
            if cmd.lower().startswith("powershell"):
                return cmd.replace("powershell", "powershell -ExecutionPolicy Bypass", 1)
            encoded = base64.b64encode(cmd.encode("utf-16-le")).decode("ascii")
            return f"powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"
        return original_command

    elif strategy == "create_missing_path":
        # Estrai il percorso dal comando e crea le cartelle prima
        path_match = re.search(r'["\']?(C:[\\\/][^"\'\\s,;]+)["\']?', original_command)
        if path_match:
            path = path_match.group(1)
            import os
            parent = os.path.dirname(path)
            if parent:
                mkdir_cmd = f'powershell.exe -Command "New-Item -ItemType Directory -Path \'{parent}\' -Force"'
                return f"{mkdir_cmd} && {original_command}"
        return original_command

    elif strategy == "fix_encoding":
        # Aggiungi -Encoding UTF8
        if "-Encoding" not in original_command:
            return original_command.rstrip() + " -Encoding UTF8"
        return original_command

    elif strategy == "increase_timeout":
        # Non modifica il comando, solo il timeout (gestito dal chiamante)
        return original_command

    elif strategy == "ignore_already_exists":
        # Il comando è già andato "bene" (la risorsa esiste)
        return None  # nessun retry necessario

    elif strategy == "suggest_admin":
        # Suggerisce run-as-admin ma non esegue automaticamente
        return None

    return None


def format_healing_report(
    command: str,
    original_error: str,
    result: HealingResult,
    fixed_command: str | None,
    retry_success: bool | None,
) -> str:
    """Genera un report human-readable dell'auto-healing."""
    lines = [f"\n⚙️ **Auto-healing attivato**"]
    lines.append(f"- Strategia: {result.message}")

    if result.strategy == "ignore_already_exists":
        lines.append("- La risorsa esiste già — continuo senza errori")
        return "\n".join(lines)

    if result.needs_auth:
        lines.append(f"- ⚠️ Richiede autorizzazione: {result.message}")
        lines.append("- Vuoi che proceda? Rispondi 'sì' per autorizzare")
        return "\n".join(lines)

    if fixed_command:
        lines.append(f"- Comando corretto applicato")
        if retry_success is True:
            lines.append("- ✅ Retry riuscito")
        elif retry_success is False:
            lines.append("- ❌ Retry fallito anche con il fix")

    return "\n".join(lines)
