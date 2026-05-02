"""
Orchestratore IGRIS v4 — routing intelligente a 3 livelli.

Logica corretta:
  LOCAL   → conversazioni, task semplici (score < 40)
  API     → task medi (score 40-74) — GPT-4o-mini, veloce ed economico
  VASTAI  → task pesanti (score >= 75) — DeepSeek-R1:32b, per elaborazioni lunghe

Regole chiave:
  - Se VPS è già accesa → usala per TUTTO tranne conversazioni (già pagata, spreco non usarla)
  - Se task score >= 75 e VPS spenta → AVVIA VPS automaticamente (non mandare a API)
  - API non deve mai ricevere task da score >= 75 (non conviene ne' per qualità ne' per costo)
  - Se VPS non disponibile (no key) → API è il massimo
  - Metriche live adattano i threshold in base alle performance reali
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field


# ── Metriche adattive ──────────────────────────────────────────────────────

@dataclass
class TierMetrics:
    name: str
    latencies: deque = field(default_factory=lambda: deque(maxlen=10))
    errors: int = 0
    requests: int = 0
    last_error_ts: float = 0.0

    @property
    def avg_latency(self) -> float:
        if len(self.latencies) >= 2:
            return sum(self.latencies) / len(self.latencies)
        # Default stimati da benchmark reale
        return {"local": 30.0, "api": 5.0, "vastai": 8.0}.get(self.name, 15.0)

    @property
    def error_rate(self) -> float:
        if self.requests == 0:
            return 0.0
        return min(1.0, self.errors / max(self.requests, 1))

    @property
    def is_overloaded(self) -> bool:
        if self.error_rate > 0.4:
            return True
        max_lat = {"local": 120.0, "api": 30.0, "vastai": 60.0}.get(self.name, 60.0)
        return self.avg_latency > max_lat

    def record(self, latency: float, error: bool = False) -> None:
        self.latencies.append(latency)
        self.requests += 1
        if error:
            self.errors = min(self.errors + 1, 20)
            self.last_error_ts = time.time()
        else:
            if self.errors > 0:
                self.errors -= 1

    def summary(self) -> dict:
        return {
            "avg_latency_s": round(self.avg_latency, 1),
            "error_rate": round(self.error_rate, 2),
            "samples": len(self.latencies),
            "overloaded": self.is_overloaded,
        }


_metrics: dict[str, TierMetrics] = {
    "local":  TierMetrics("local"),
    "api":    TierMetrics("api"),
    "vastai": TierMetrics("vastai"),
}


def record_performance(tier: str, latency: float, error: bool = False) -> None:
    if tier in _metrics:
        _metrics[tier].record(latency, error)


def get_metrics() -> dict:
    return {t: m.summary() for t, m in _metrics.items()}


# ── Carico sistema ─────────────────────────────────────────────────────────

def _get_local_load() -> tuple[float, float]:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.1), psutil.virtual_memory().percent
    except Exception:
        return 0.0, 0.0


def _local_is_stressed() -> bool:
    cpu, ram = _get_local_load()
    return cpu > 80 or ram > 85


# ── Classificazione task ───────────────────────────────────────────────────

class TaskType:
    CONVERSATION  = "conversation"
    SYSADMIN      = "sysadmin"
    LINUX_SERVER  = "linux_server"
    SECURITY      = "security"
    NETWORK       = "network"
    POWERSHELL    = "powershell"
    WORDPRESS     = "wordpress"
    ANALYSIS      = "analysis"
    GENERATION    = "generation"
    CODE_COMPLEX  = "code_complex"
    CODE_SIMPLE   = "code_simple"
    DEVELOPMENT   = "development"   # NUOVO: sviluppo software complesso


_SIGNALS: dict[str, set[str]] = {
    TaskType.CONVERSATION: {
        "ciao", "salve", "hello", "hi", "hey", "buongiorno",
        "come stai", "come va", "grazie", "prego",
        "chi sei", "cosa sei", "presentati", "sei pronto",
    },
    TaskType.DEVELOPMENT: {
        # Task da VastAI: sviluppo software complesso, multi-file, architetture
        "crea un'applicazione", "crea un programma", "crea un sistema",
        "crea un agente", "crea un bot", "crea un software",
        "sviluppa un", "implementa un sistema", "progetta un",
        "architettura", "microservizi", "api rest", "backend completo",
        "frontend completo", "full stack", "database schema",
        "refactoring completo", "migrazione codice",
        "crea un clone", "simile a devin", "simile a igris",
        "multi-step", "agent loop", "autonomous",
    },
    TaskType.POWERSHELL: {
        "powershell", "script ps", ".ps1", "wpf", "datagrid", "gui",
        "ad-actionhub", "actionhub", "lib.psm1", "dry-run",
        "try/catch", "param(", "launcher", "executionpolicy",
        "task sequence", "litetouch", "bootstrap.ini", "customsettings",
    },
    TaskType.SECURITY: {
        "audit", "sicurezza", "hardening", "vulnerability", "incident",
        "triage", "forensi", "forensic", "compromiss",
        "antivirus", "bitlocker", "ntfs", "permessi smb", "rdp",
        "porte aperte", "autorun", "processi sospetti", "log accesso",
        "brute force", "phishing", "hash", "integrita file",
        "credenziali espost", "utenti admin", "sudo non autorizzat",
        "indicatori di compromissione", "endpoint potenzialmente",
    },
    TaskType.SYSADMIN: {
        "windows", "office", "microsoft 365", "mdt", "wim", "dism",
        "oobe", "autopilot", "wsus", "windows update",
        "active directory", " ad ", "domain controller", "gpo",
        "gpresult", "fsmo", "sysvol", "replica ad",
        "driver", "imaging", "deployment", "endpoint",
        "utente ad", "computer ad", " ou ", "foresta",
        "visual c++", "webview2", ".net runtime",
    },
    TaskType.LINUX_SERVER: {
        "ubuntu", "debian", "linux", "vps", "bash",
        "systemctl", "ufw", "fail2ban", "nginx", "apache",
        "docker", "container", "reverse proxy", "certbot",
        "ssh", "cron", "journalctl", "apt", "systemd", "php-fpm",
        "mariadb", "mysql", "let's encrypt",
    },
    TaskType.NETWORK: {
        "rete ", "network", "vpn", "dns", "routing", " route",
        "wireguard", "glorytun", "mlvpn", "proxy",
        "latenza", "ping", "tracert", "pathping", "iperf",
        "connettivita", "share aziendale", "unc",
        "spf", "dkim", "dmarc", " mx ", "record dns", "propagazione",
    },
    TaskType.WORDPRESS: {
        "wordpress", "wp-admin", "plugin", "wp-config",
        "migrazione sito", "permalink", "backup wordpress",
        "hosting", "relazione cliente", "manutenzione mensile",
        "piano operativo", "let's encrypt", "performance sito",
    },
    TaskType.GENERATION: {
        "crea uno script", "prepara uno script", "scrivi uno script",
        "crea una procedura", "prepara una procedura",
        "crea una checklist", "prepara una checklist",
        "crea un piano", "prepara un piano", "crea una funzione",
        "crea un modulo", "crea una gui", "crea una relazione",
        "prepara una relazione", "crea una struttura",
        "trasforma questo script", "prepara una configurazione",
    },
    TaskType.ANALYSIS: {
        "analizza", "analisi", "individua", "verifica perch",
        "segnala", "esamina", "controlla", "diagnos",
    },
    TaskType.CODE_COMPLEX: {
        "refactor", "ottimizza il codice", "rifattorizza",
        "debug complesso", "correggi tutti", "riscrive",
        "implementa la logica", "algoritmo",
    },
    TaskType.CODE_SIMPLE: {
        "snippet", "esempio breve", "una riga", "come si fa",
        "sintassi", "esempio di",
    },
}

# Score base — soglie:
#   < 40  → LOCAL
#   40-74 → API
#   >= 75 → VASTAI (task pesanti, lunghi, complessi)
_BASE_COMPLEXITY: dict[str, int] = {
    TaskType.CONVERSATION: 5,
    TaskType.CODE_SIMPLE:  20,
    TaskType.WORDPRESS:    45,
    TaskType.ANALYSIS:     50,
    TaskType.NETWORK:      55,
    TaskType.SYSADMIN:     60,
    TaskType.LINUX_SERVER: 60,
    TaskType.GENERATION:   65,
    TaskType.POWERSHELL:   65,
    TaskType.CODE_COMPLEX: 72,
    TaskType.SECURITY:     75,   # → VASTAI
    TaskType.DEVELOPMENT:  90,   # → VASTAI sempre
}


def classify_task(prompt: str) -> tuple[str, int]:
    """Classifica task e ritorna (tipo, score 0-100)."""
    lower = prompt.lower()
    tokens = len(lower.split()) * 1.3

    # Conversazione pura
    has_action = bool(re.search(
        r'\b(analizza|crea|prepara|scrivi|verifica|controlla|esegui|'
        r'genera|trasforma|aggiorna|configura|installa|individua|produci|'
        r'sviluppa|implementa|progetta|costruisci|refactor)\b',
        lower
    ))
    is_greeting = any(lower.startswith(g) or lower == g
                      for g in _SIGNALS[TaskType.CONVERSATION])
    if is_greeting and not has_action and tokens < 15:
        return TaskType.CONVERSATION, 5

    # Score per categoria
    cat_scores: dict[str, int] = {}
    for cat, signals in _SIGNALS.items():
        if cat == TaskType.CONVERSATION:
            continue
        hits = sum(1 for s in signals if s in lower)
        weight = 4 if cat in (TaskType.DEVELOPMENT, TaskType.SECURITY) else \
                 3 if cat == TaskType.POWERSHELL else 2
        cat_scores[cat] = hits * weight

    best = max(cat_scores, key=lambda k: cat_scores[k]) if cat_scores else TaskType.ANALYSIS
    if cat_scores.get(best, 0) == 0:
        best = TaskType.ANALYSIS

    base = _BASE_COMPLEXITY.get(best, 45)
    # Bonus lunghezza: prompt lungo = task complesso
    len_bonus = min(20, int(tokens / 15))
    # Bonus extra se il prompt è molto lungo (probabilmente task da VastAI)
    if tokens > 100:
        len_bonus += 10
    score = min(98, base + len_bonus)
    return best, score


# ── Routing principale ─────────────────────────────────────────────────────

# Soglie fisse
SCORE_LOCAL  = 40   # sotto → LOCAL
SCORE_VASTAI = 75   # sopra → VASTAI (non API)


def route_request(
    prompt: str,
    vps_is_ready: bool = False,
    api_available: bool = True,
    vastai_available: bool = True,
) -> tuple[str, str]:
    """
    Routing a 3 livelli con logica corretta:

    CONVERSAZIONE           → local  (sempre)
    score < 40              → local  (task semplice)
    score 40-74             → api    (task medio, GPT-4o-mini)
    score >= 75             → vastai (task pesante/lungo, DeepSeek-R1:32b)

    Override:
    - VPS già accesa → usala per tutto tranne conversazioni (già pagata)
    - VPS non disponibile → API è il massimo, anche per task score >= 75
    - Tier overloaded → scala al successivo
    """
    task_type, score = classify_task(prompt)
    m = _metrics

    # ── CONVERSAZIONE: sempre locale ─────────────────────────────────────
    if task_type == TaskType.CONVERSATION:
        return "local", "Conversazione → locale"

    # ── VPS GIA' ACCESA: usala per tutto (già pagata, spreco non usarla) ─
    if vps_is_ready and vastai_available and not m["vastai"].is_overloaded:
        if score >= SCORE_LOCAL:  # non per task semplicissimi
            return "vastai", (
                f"VPS attiva → GPU DeepSeek "
                f"[score={score}, task={task_type}, "
                f"avg={m['vastai'].avg_latency:.0f}s]"
            )

    local_stressed = _local_is_stressed()

    # ── TASK PESANTE (score >= 75): VASTAI o niente ───────────────────────
    if score >= SCORE_VASTAI:
        if vastai_available and not m["vastai"].is_overloaded:
            return "vastai", (
                f"Task pesante {task_type} (score={score}) → GPU VastAI — "
                f"API non adatta per qualita'/costo su task lunghi"
            )
        # VastAI non disponibile → API come fallback con avviso
        if api_available and not m["api"].is_overloaded:
            return "api", (
                f"Task pesante (score={score}) → API FALLBACK "
                f"[VastAI non disponibile — qualita' limitata su task lunghi]"
            )
        return "local", f"Task pesante → locale (unica opzione disponibile)"

    # ── TASK MEDIO (score 40-74): API ────────────────────────────────────
    if score >= SCORE_LOCAL:
        if api_available and not m["api"].is_overloaded:
            return "api", (
                f"Task medio {task_type} (score={score}) → API "
                f"[avg {m['api'].avg_latency:.0f}s]"
            )
        # API non disponibile → locale
        if not m["local"].is_overloaded and not local_stressed:
            return "local", f"Task medio → locale (API non disponibile)"
        return "local", f"Task medio → locale (fallback)"

    # ── TASK SEMPLICE (score < 40): LOCAL ────────────────────────────────
    if not m["local"].is_overloaded and not local_stressed:
        return "local", f"Task semplice (score={score}) → locale"

    if api_available and not m["api"].is_overloaded:
        return "api", f"Locale stressato → API"

    return "local", f"Default locale"


def explain_routing(prompt: str, vps_ready: bool = False) -> dict:
    """Debug routing completo."""
    task_type, score = classify_task(prompt)
    tier, reason = route_request(prompt, vps_ready)
    cpu, ram = _get_local_load()

    tier_label = {
        "local":  f"LOCAL (phi4-mini, ~30s)",
        "api":    f"API (GPT-4o-mini, ~5s)",
        "vastai": f"GPU (DeepSeek-R1:32b, ~5-8s, ZH interno)",
    }.get(tier, tier)

    return {
        "task_type": task_type,
        "complexity_score": score,
        "score_thresholds": {
            "local_max": SCORE_LOCAL,
            "api_range": f"{SCORE_LOCAL}-{SCORE_VASTAI-1}",
            "vastai_min": SCORE_VASTAI,
        },
        "tier_chosen": tier,
        "tier_label": tier_label,
        "reason": reason,
        "tokens_estimated": int(len(prompt.split()) * 1.3),
        "system_load": {"cpu_pct": round(cpu, 1), "ram_pct": round(ram, 1)},
        "tier_metrics": get_metrics(),
    }
