"""
System context detection for IGRIS.

Rilevamento automatico e affidabile del contesto di sistema:
utente corrente, home directory, desktop, OS, shell, ecc.
Zero configurazione statica — tutto rilevato a runtime.
"""

from __future__ import annotations

import os
import platform
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_system_context() -> dict:
    """
    Rileva il contesto di sistema completo una sola volta e lo mette in cache.

    Returns un dizionario con tutte le info utili al LLM per usare
    percorsi corretti senza mai indovinare.
    """
    ctx: dict = {}

    # --- OS ---
    ctx["os"] = platform.system()          # "Windows", "Linux", "Darwin"
    ctx["os_version"] = platform.version()
    ctx["is_windows"] = platform.system() == "Windows"
    ctx["is_linux"]   = platform.system() == "Linux"
    ctx["is_mac"]     = platform.system() == "Darwin"

    # --- Utente corrente ---
    # Prova tutte le variabili d'ambiente in ordine di affidabilità
    username = (
        os.environ.get("USERNAME")      # Windows
        or os.environ.get("USER")       # Linux/Mac
        or os.environ.get("LOGNAME")    # fallback Unix
    )
    # Se non trovato nelle env, prova via getlogin()
    if not username:
        try:
            import getpass
            username = getpass.getuser()
        except Exception:
            username = "user"

    ctx["username"] = username

    # --- Home directory ---
    # Path.home() è cross-platform e usa le variabili d'ambiente corrette
    home = Path.home()
    ctx["home"] = _norm(home)

    # --- Desktop ---
    desktop = _detect_desktop(home, ctx["is_windows"])
    ctx["desktop"] = _norm(desktop)

    # --- Documenti ---
    documents = _detect_documents(home, ctx["is_windows"])
    ctx["documents"] = _norm(documents)

    # --- Download ---
    downloads = home / "Downloads"
    if not downloads.exists():
        downloads = home / "download"
    ctx["downloads"] = _norm(downloads)

    # --- Directory corrente (dove IGRIS è stato avviato) ---
    ctx["cwd"] = _norm(Path.cwd())

    # --- Shell disponibile ---
    if ctx["is_windows"]:
        ctx["shell"] = "cmd.exe"
        ctx["shell_alt"] = "powershell.exe"
    else:
        ctx["shell"] = os.environ.get("SHELL", "/bin/bash")
        ctx["shell_alt"] = None

    # --- Python corrente ---
    import sys
    ctx["python"] = _norm(Path(sys.executable))
    ctx["python_version"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    return ctx


def _norm(path: Path) -> str:
    """Normalizza il path con forward slash — funziona su Windows e Unix."""
    return str(path).replace("\\", "/")


def _detect_desktop(home: Path, is_windows: bool) -> Path:
    """Rileva il percorso del Desktop in modo affidabile."""

    if is_windows:
        # Metodo 1: variabile d'ambiente USERPROFILE (la più affidabile su Windows)
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidate = Path(userprofile) / "Desktop"
            if candidate.exists():
                return candidate

        # Metodo 2: registro di Windows (per Desktop personalizzati)
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            desktop_path, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            candidate = Path(desktop_path)
            if candidate.exists():
                return candidate
        except Exception:
            pass

        # Metodo 3: Path.home() / Desktop
        candidate = home / "Desktop"
        if candidate.exists():
            return candidate

        # Metodo 4: crea la cartella se non esiste (raro ma possibile)
        return home / "Desktop"

    else:
        # Linux/Mac: XDG standard
        xdg = os.environ.get("XDG_DESKTOP_DIR")
        if xdg:
            candidate = Path(xdg)
            if candidate.exists():
                return candidate

        # Fallback standard
        for name in ["Desktop", "desktop", "Scrivania"]:  # Scrivania = italiano su Mac
            candidate = home / name
            if candidate.exists():
                return candidate

        return home / "Desktop"


def _detect_documents(home: Path, is_windows: bool) -> Path:
    """Rileva il percorso Documenti."""
    if is_windows:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            docs_path, _ = winreg.QueryValueEx(key, "Personal")
            winreg.CloseKey(key)
            return Path(docs_path)
        except Exception:
            pass
        return home / "Documents"
    else:
        for name in ["Documents", "documents", "Documenti"]:
            candidate = home / name
            if candidate.exists():
                return candidate
        return home / "Documents"


def build_system_prompt_section() -> str:
    """
    Costruisce la sezione del system prompt con il contesto di sistema.
    Chiamata una sola volta per sessione (il risultato è cachato).
    """
    ctx = get_system_context()

    lines = [
        "\n## Contesto di Sistema (rilevato automaticamente)",
        f"- OS: {ctx['os']}",
        f"- Utente: {ctx['username']}",
        f"- Home: {ctx['home']}",
        f"- Desktop: {ctx['desktop']}",
        f"- Documenti: {ctx['documents']}",
        f"- Download: {ctx['downloads']}",
        f"- Directory corrente: {ctx['cwd']}",
        f"- Python: {ctx['python']} (v{ctx['python_version']})",
        "",
        "Quando devi creare file in posizioni comuni usa SEMPRE questi percorsi:",
        f"  desktop  → {ctx['desktop']}",
        f"  home     → {ctx['home']}",
        f"  documenti→ {ctx['documents']}",
        "Non indovinare i percorsi: usa quelli indicati sopra.",
    ]

    return "\n".join(lines)


def resolve_user_path(user_input: str) -> str:
    """
    Risolve alias comuni nei percorsi scritti dall'utente.

    Esempi:
      "desktop"          → "C:/Users/Admin/Desktop"
      "~/test.txt"       → "C:/Users/Admin/test.txt"
      "documenti/report" → "C:/Users/Admin/Documents/report"
    """
    ctx = get_system_context()
    p = user_input.strip().strip('"').strip("'")

    aliases = {
        "desktop":    ctx["desktop"],
        "~/desktop":  ctx["desktop"],
        "home":       ctx["home"],
        "~":          ctx["home"],
        "documenti":  ctx["documents"],
        "documents":  ctx["documents"],
        "download":   ctx["downloads"],
        "downloads":  ctx["downloads"],
    }

    p_lower = p.lower().replace("\\", "/")
    for alias, real in aliases.items():
        if p_lower == alias:
            return real
        if p_lower.startswith(alias + "/"):
            return real + p[len(alias):]

    # Espandi ~ se presente
    if p.startswith("~/") or p == "~":
        return ctx["home"] + p[1:]

    return p
