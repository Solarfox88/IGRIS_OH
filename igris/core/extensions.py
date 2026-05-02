"""
IGRIS Self-Extension Engine.

Permette a IGRIS di implementare nuove capacità in autonomia
quando necessario per completare un task, previa autorizzazione
dell'utente per azioni con impatto sul sistema.

Capacità auto-implementabili:
- Controllo mouse/tastiera (pyautogui)
- Interazione browser (playwright/selenium)
- Cattura schermo (screenshot)
- OCR su immagini
- Monitoraggio file system (watchdog)
- Client HTTP personalizzati
- Qualsiasi libreria Python installabile via pip

Flusso:
1. IGRIS rileva che manca una capacità per completare il task
2. Chiede autorizzazione all'utente
3. Installa la dipendenza (pip)
4. Genera il codice dell'estensione
5. Lo salva come modulo in igris/extensions/
6. Lo attiva immediatamente
"""

from __future__ import annotations

import importlib
import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("igris.extensions")

EXTENSIONS_DIR = Path(__file__).parent.parent / "extensions"
REGISTRY_PATH  = EXTENSIONS_DIR / "registry.json"


# ── Registro delle capacità disponibili ────────────────────────────────────

KNOWN_CAPABILITIES = {
    "mouse_control": {
        "name": "Controllo mouse e tastiera",
        "description": "Muove il mouse, clicca, digita testo, tasti speciali",
        "pip_packages": ["pyautogui", "pygetwindow"],
        "module": "igris.extensions.mouse_control",
        "risk": "medium",
        "risk_note": "Può controllare mouse e tastiera — tieni il controllo fisico del PC",
    },
    "browser_control": {
        "name": "Controllo browser (Playwright)",
        "description": "Apre URL, clicca elementi, compila form, cattura screenshot pagine",
        "pip_packages": ["playwright"],
        "post_install": ["python -m playwright install chromium"],
        "module": "igris.extensions.browser_control",
        "risk": "medium",
        "risk_note": "Controlla il browser e può navigare qualsiasi sito",
    },
    "screen_capture": {
        "name": "Cattura schermo e OCR",
        "description": "Screenshot, registrazione schermo, lettura testo da immagini",
        "pip_packages": ["pillow", "pytesseract", "mss"],
        "module": "igris.extensions.screen_capture",
        "risk": "low",
        "risk_note": "Legge solo lo schermo, non interagisce",
    },
    "file_watcher": {
        "name": "Monitoraggio file system",
        "description": "Osserva cartelle in tempo reale, trigger su modifiche",
        "pip_packages": ["watchdog"],
        "module": "igris.extensions.file_watcher",
        "risk": "low",
        "risk_note": "Solo lettura del filesystem",
    },
    "network_tools": {
        "name": "Strumenti di rete avanzati",
        "description": "Scansione porte, SNMP, SSH client, packet capture",
        "pip_packages": ["scapy", "paramiko", "netmiko"],
        "module": "igris.extensions.network_tools",
        "risk": "medium",
        "risk_note": "Può inviare pacchetti di rete",
    },
    "windows_api": {
        "name": "Windows API dirette",
        "description": "Accesso a Win32 API, registry, servizi, WMI avanzato",
        "pip_packages": ["pywin32", "wmi"],
        "module": "igris.extensions.windows_api",
        "risk": "high",
        "risk_note": "Accesso diretto alle API di sistema Windows",
    },
}


class ExtensionManager:
    """Gestisce l'installazione e l'attivazione di estensioni IGRIS."""

    def __init__(self, workspace_root: str = "."):
        self.workspace_root = Path(workspace_root)
        self.extensions_dir = self.workspace_root / "igris_extensions"
        self.extensions_dir.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, object] = {}
        self._load_registry()

    def _load_registry(self) -> dict:
        reg = self.extensions_dir / "registry.json"
        if reg.exists():
            try:
                return json.loads(reg.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_registry(self, data: dict) -> None:
        reg = self.extensions_dir / "registry.json"
        reg.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_available(self) -> list[dict]:
        """Lista le capacità disponibili con stato installazione."""
        result = []
        for key, cap in KNOWN_CAPABILITIES.items():
            installed = self._is_installed(cap["pip_packages"])
            result.append({
                "id": key,
                "name": cap["name"],
                "description": cap["description"],
                "installed": installed,
                "risk": cap["risk"],
                "risk_note": cap["risk_note"],
                "packages": cap["pip_packages"],
            })
        return result

    def _is_installed(self, packages: list[str]) -> bool:
        for pkg in packages:
            try:
                importlib.import_module(pkg.replace("-", "_"))
            except ImportError:
                return False
        return True

    def needs_auth(self, capability_id: str) -> bool:
        """Ritorna True se questa capacità richiede autorizzazione utente."""
        cap = KNOWN_CAPABILITIES.get(capability_id, {})
        return cap.get("risk", "low") in ("medium", "high")

    def install(self, capability_id: str) -> dict:
        """
        Installa una capacità (pip install + codice modulo).
        Ritorna {"ok": bool, "message": str, "capability": dict}
        """
        cap = KNOWN_CAPABILITIES.get(capability_id)
        if not cap:
            return {"ok": False, "message": f"Capacità '{capability_id}' non trovata"}

        logger.info(f"Installazione capacità: {cap['name']}")
        results = []

        # Installa pacchetti pip
        for pkg in cap["pip_packages"]:
            try:
                logger.info(f"pip install {pkg}...")
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install", pkg,
                     "--break-system-packages", "--quiet"],
                    capture_output=True, text=True, timeout=120,
                )
                if r.returncode == 0:
                    results.append(f"✅ {pkg} installato")
                else:
                    # Prova senza --break-system-packages
                    r2 = subprocess.run(
                        [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                        capture_output=True, text=True, timeout=120,
                    )
                    if r2.returncode == 0:
                        results.append(f"✅ {pkg} installato")
                    else:
                        results.append(f"❌ {pkg}: {r2.stderr[:100]}")
            except Exception as e:
                results.append(f"❌ {pkg}: {e}")

        # Comandi post-install
        for cmd in cap.get("post_install", []):
            try:
                subprocess.run(cmd.split(), capture_output=True, timeout=180)
            except Exception:
                pass

        # Genera e salva il modulo dell'estensione
        module_code = _generate_extension_code(capability_id, cap)
        if module_code:
            mod_path = self.extensions_dir / f"{capability_id}.py"
            mod_path.write_text(module_code, encoding="utf-8")
            results.append(f"📄 Modulo creato: {mod_path}")

        # Aggiorna registry
        reg = self._load_registry()
        reg[capability_id] = {
            "installed": True,
            "packages": cap["pip_packages"],
        }
        self._save_registry(reg)

        success = all("✅" in r for r in results)
        return {
            "ok": success,
            "message": "\n".join(results),
            "capability": cap,
        }

    def generate_request_message(self, capability_id: str, reason: str) -> str:
        """
        Genera il messaggio che IGRIS mostra all'utente prima di installare.
        """
        cap = KNOWN_CAPABILITIES.get(capability_id, {})
        risk = cap.get("risk", "low")
        risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")

        return (
            f"## Richiesta auto-implementazione\n\n"
            f"Per completare il task ho bisogno di una nuova capacità:\n\n"
            f"**{cap.get('name', capability_id)}**\n"
            f"{cap.get('description', '')}\n\n"
            f"**Pacchetti da installare:** `{', '.join(cap.get('pip_packages', []))}`\n"
            f"**Rischio:** {risk_icon} {cap.get('risk', 'basso').upper()}\n"
            f"**Nota:** {cap.get('risk_note', '')}\n\n"
            f"**Motivo:** {reason}\n\n"
            f"Vuoi che proceda con l'installazione? Rispondi **sì** per autorizzare."
        )


def _generate_extension_code(capability_id: str, cap: dict) -> str | None:
    """Genera il codice Python per il modulo dell'estensione."""

    if capability_id == "mouse_control":
        return '''"""Controllo mouse e tastiera per IGRIS."""
import pyautogui
import time

pyautogui.FAILSAFE = True  # muovi mouse in alto-sinistra per fermare

def move_to(x, y, duration=0.3):
    """Sposta il mouse alle coordinate x, y."""
    pyautogui.moveTo(x, y, duration=duration)

def click(x=None, y=None, button="left", clicks=1):
    """Clicca (opzionalmente a x, y)."""
    if x is not None:
        pyautogui.click(x, y, button=button, clicks=clicks)
    else:
        pyautogui.click(button=button, clicks=clicks)

def double_click(x=None, y=None):
    click(x, y, clicks=2)

def right_click(x=None, y=None):
    click(x, y, button="right")

def type_text(text, interval=0.02):
    """Digita testo."""
    pyautogui.typewrite(text, interval=interval)

def hotkey(*keys):
    """Combinazione di tasti. Es: hotkey('ctrl', 'c')"""
    pyautogui.hotkey(*keys)

def press(key):
    """Premi un tasto. Es: press('enter')"""
    pyautogui.press(key)

def screenshot(path=None):
    """Cattura schermo."""
    img = pyautogui.screenshot()
    if path:
        img.save(path)
    return img

def get_mouse_pos():
    return pyautogui.position()

def drag_to(x, y, duration=0.5):
    pyautogui.dragTo(x, y, duration=duration)

def scroll(amount, x=None, y=None):
    """Scrolla. Positivo = su, Negativo = giu."""
    if x is not None:
        pyautogui.scroll(amount, x=x, y=y)
    else:
        pyautogui.scroll(amount)
'''

    if capability_id == "browser_control":
        return '''"""Controllo browser via Playwright per IGRIS."""
from playwright.sync_api import sync_playwright
import time

_pw = None
_browser = None
_page = None

def _ensure_browser(headless=False):
    global _pw, _browser, _page
    if _page is None:
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=headless)
        _page = _browser.new_page()
    return _page

def navigate(url, wait_until="domcontentloaded"):
    page = _ensure_browser()
    page.goto(url, wait_until=wait_until)
    return page.title()

def click_element(selector):
    page = _ensure_browser()
    page.click(selector)

def fill_input(selector, value):
    page = _ensure_browser()
    page.fill(selector, value)

def get_text(selector):
    page = _ensure_browser()
    return page.inner_text(selector)

def get_page_content():
    page = _ensure_browser()
    return page.content()

def screenshot(path):
    page = _ensure_browser()
    page.screenshot(path=path)

def close():
    global _pw, _browser, _page
    if _browser: _browser.close()
    if _pw: _pw.stop()
    _pw = _browser = _page = None

def evaluate_js(script):
    page = _ensure_browser()
    return page.evaluate(script)

def wait_for(selector, timeout=5000):
    page = _ensure_browser()
    page.wait_for_selector(selector, timeout=timeout)
'''

    if capability_id == "screen_capture":
        return '''"""Cattura schermo e OCR per IGRIS."""
import mss
import mss.tools
from PIL import Image
import io

def screenshot(path=None, monitor=1):
    """Cattura lo schermo. monitor=1 = primo monitor."""
    with mss.mss() as sct:
        img = sct.grab(sct.monitors[monitor])
        if path:
            mss.tools.to_png(img.rgb, img.size, output=path)
        return Image.frombytes("RGB", img.size, img.rgb)

def screenshot_region(left, top, width, height, path=None):
    """Cattura una regione specifica dello schermo."""
    with mss.mss() as sct:
        region = {"left": left, "top": top, "width": width, "height": height}
        img = sct.grab(region)
        pil_img = Image.frombytes("RGB", img.size, img.rgb)
        if path:
            pil_img.save(path)
        return pil_img

def ocr_image(image_path):
    """Estrae testo da un\'immagine."""
    try:
        import pytesseract
        img = Image.open(image_path)
        return pytesseract.image_to_string(img, lang="ita+eng")
    except ImportError:
        return "pytesseract non installato"

def ocr_screenshot():
    """Screenshot + OCR in un passo."""
    img = screenshot()
    try:
        import pytesseract
        return pytesseract.image_to_string(img, lang="ita+eng")
    except ImportError:
        return "pytesseract non installato"
'''

    return None
