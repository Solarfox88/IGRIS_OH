"""
VastAI Manager per IGRIS.

Flusso testato e funzionante:
1. POST /bundles/ -> cerca GPU con VRAM >= 16GB
2. PUT /asks/{id}/ -> crea istanza ssh_direct (senza 'ports', no env dict)
3. Polling GET /instances/{id}/ -> attende actual_status == "running"
4. Legge direct_port_start (porta pubblica assegnata da Vast.ai)
5. SSH -> installa Ollama, avvialo su 0.0.0.0 sulla direct port
6. Polling HTTP su host:direct_port -> attende Ollama pronto
7. Query OpenAI-compatible su http://host:direct_port/v1
8. DELETE /instances/{id}/ -> distrugge dopo uso (on-demand) o lascia (persistent)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger("igris.vastai")

VAST_API_BASE = "https://console.vast.ai/api/v0"

VASTAI_ACCEPTED_GPUS = [
    "A100 SXM4", "A100 PCIe", "RTX A6000", "A40",
    "RTX 4090", "RTX 3090", "RTX 4080",
]
VASTAI_MIN_VRAM_GB = 16
VASTAI_IMAGE = "vastai/ollama:0.21.2"  # immagine ufficiale Vast.ai con Ollama preinstallato
VASTAI_OLLAMA_PORT = 11434
# Su GPU 24GB usiamo DeepSeek-R1:32b
# - Reasoning integrato (pensa step-by-step prima di rispondere)
# - 18GB VRAM a Q4_K_M - entra in RTX 3090 con margine
# - Batte GPT-4 su coding e math nei benchmark
# - Open source, zero costi per token
VASTAI_OLLAMA_MODEL = "deepseek-r1:32b"
VASTAI_MODEL_NAME = "deepseek-r1:32b"


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


class VastAIMode:
    ON_DEMAND  = "on_demand"
    PERSISTENT = "persistent"


class VastAIState:
    def __init__(self, state_path: Path):
        self.path = state_path
        self.instance_id: int | None = None
        self.host: str | None = None
        self.ssh_port: int | None = None
        self.ollama_port: int | None = None
        self.status: str = "offline"
        self.created_at: float = 0.0
        self.last_used: float = 0.0
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.instance_id = d.get("instance_id")
                self.host        = d.get("host")
                self.ssh_port    = d.get("ssh_port")
                self.ollama_port = d.get("ollama_port")
                self.status      = d.get("status", "offline")
                self.created_at  = d.get("created_at", 0.0)
                self.last_used   = d.get("last_used", 0.0)
            except Exception as e:
                logger.warning(f"VastAI state load error: {e}")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "instance_id": self.instance_id,
            "host":        self.host,
            "ssh_port":    self.ssh_port,
            "ollama_port": self.ollama_port,
            "status":      self.status,
            "created_at":  self.created_at,
            "last_used":   self.last_used,
        }, indent=2), encoding="utf-8")

    def reset(self) -> None:
        self.instance_id = None
        self.host = self.ssh_port = self.ollama_port = None
        self.status = "offline"
        self.created_at = self.last_used = 0.0
        self.save()

    @property
    def api_base(self) -> str | None:
        if self.host and self.ollama_port:
            return f"http://{self.host}:{self.ollama_port}/v1"
        return None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready" and bool(self.host) and bool(self.ollama_port)

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.created_at) / 60 if self.created_at else 0.0


class VastAIManager:

    def __init__(self, api_key: str, state_path: Path, max_cost_per_hour: float = 0.50):
        self.api_key = api_key
        self.max_cost_per_hour = max_cost_per_hour
        self.state = VastAIState(state_path)
        self.mode  = VastAIMode.ON_DEMAND

    def set_persistent(self, enabled: bool) -> None:
        self.mode = VastAIMode.PERSISTENT if enabled else VastAIMode.ON_DEMAND
        logger.info(f"VastAI mode: {self.mode}")

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    async def ensure_ready(self) -> str:
        """
        Garantisce che ci sia UNA SOLA istanza attiva.
        Se ne esiste gia' una (locale o remota), la riusa senza crearne un'altra.
        """
        # STEP 1: controlla stato locale
        if self.state.instance_id and self.state.status in ("provisioning", "running", "ready"):
            if self.state.is_ready and await self._is_ollama_responsive():
                logger.info(f"VastAI: riuso istanza locale {self.state.instance_id}")
                self.state.last_used = time.time()
                self.state.save()
                return self.state.api_base
            elif self.state.status == "provisioning":
                logger.warning("VastAI: provisioning gia' in corso — attendo senza creare")
                raise RuntimeError("__PROVISIONING__")  # segnale speciale: gia' in corso

        # STEP 2: verifica su Vast.ai se esistono istanze attive (guard anti-duplicazione)
        existing = await self._fetch_active_instance()
        if existing:
            iid  = existing["id"]
            host = existing.get("public_ipaddr") or existing.get("ssh_host", "")
            ports = existing.get("ports", {})
            tcp = ports.get("11434/tcp", []) if isinstance(ports, dict) else []
            ollama_port = int(tcp[0]["HostPort"]) if tcp else int(existing.get("direct_port_start", 11434))
            ssh_port    = int(existing.get("ssh_port", 22))
            logger.info(f"VastAI: istanza remota gia' attiva {iid} @ {host}:{ollama_port} — la riuso")
            # Sincronizza stato locale con l'istanza remota
            self.state.instance_id = iid
            self.state.host        = host
            self.state.ssh_port    = ssh_port
            self.state.ollama_port = ollama_port
            self.state.created_at  = self.state.created_at or time.time()
            # Controlla se Ollama e' gia' pronto
            if host and await self._is_ollama_responsive():
                self.state.status   = "ready"
                self.state.last_used = time.time()
                self.state.save()
                return self.state.api_base
            else:
                self.state.status = "running"
                self.state.save()
                # Aspetta Ollama
                if not await self._wait_for_ollama(host, ollama_port):
                    await self.destroy()
                    raise RuntimeError("Ollama non risponde sull'istanza esistente.")
                self.state.status    = "ready"
                self.state.last_used = time.time()
                self.state.save()
                return self.state.api_base

        # STEP 3: nessuna istanza esistente — resetta e crea nuova
        if self.state.instance_id:
            self.state.reset()

        # 1. Cerca offerta GPU
        offer = await self._find_best_offer()
        if not offer:
            raise RuntimeError(
                f"Nessuna GPU >=16GB disponibile sotto ${self.max_cost_per_hour}/h"
            )
        logger.info(
            f"VastAI: {offer.get('gpu_name')} id={offer['id']} "
            f"${offer.get('dph_total',0):.3f}/h @ {offer.get('geolocation','?')}"
        )

        # 2. Crea istanza ssh_direct (no env dict, no ports - funziona!)
        instance_id = await self._create_instance(offer)
        self.state.instance_id = instance_id
        self.state.status = "provisioning"
        self.state.created_at = time.time()
        self.state.save()

        # 3. Attendi running e leggi host + direct_port
        info = await self._wait_for_running(instance_id)
        if not info:
            await self.destroy()
            raise RuntimeError("Timeout: istanza non diventata running entro 12 minuti.")

        host, ssh_port, direct_port = info
        self.state.host = host
        self.state.ssh_port = ssh_port
        self.state.ollama_port = direct_port
        self.state.status = "running"
        self.state.save()
        logger.info(f"VastAI: running su {host} ollama_port={direct_port}")

        # Con vastai/ollama Ollama parte automaticamente + onstart fa il pull
        # Aspetta solo che risponda HTTP
        if not await self._wait_for_ollama(host, direct_port):
            await self.destroy()
            raise RuntimeError("Ollama non risponde entro 12 minuti.")

        self.state.status = "ready"
        self.state.last_used = time.time()
        self.state.save()
        logger.info(f"VastAI pronta: {self.state.api_base}")
        return self.state.api_base

    async def destroy(self) -> bool:
        if not self.state.instance_id:
            return False
        iid = self.state.instance_id
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.delete(f"{VAST_API_BASE}/instances/{iid}/", headers=_headers(self.api_key))
                r.raise_for_status()
            logger.info(f"VastAI: istanza {iid} distrutta")
            self.state.reset()
            return True
        except Exception as e:
            logger.error(f"VastAI destroy error: {e}")
            self.state.reset()
            return False

    async def get_status(self) -> dict:
        if not self.state.instance_id:
            return {"status": "offline", "message": "Nessuna istanza attiva"}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{VAST_API_BASE}/instances/{self.state.instance_id}/", headers=_headers(self.api_key))
                data = r.json()
            inst = self._parse_instance(data)
            return {
                "status": self.state.status,
                "instance_id": self.state.instance_id,
                "api_base": self.state.api_base,
                "model": VASTAI_MODEL_NAME,
                "age_minutes": round(self.state.age_minutes, 1),
                "vast_status": inst.get("actual_status", "unknown") if inst else "unknown",
                "cost_per_hour": inst.get("dph_total", "?") if inst else "?",
            }
        except Exception as e:
            return {"status": self.state.status, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Private                                                             #
    # ------------------------------------------------------------------ #

    def _parse_instance(self, data: dict) -> dict | None:
        """Estrae il dict istanza dalla risposta API (lista o dict)."""
        instances = data.get("instances", [])
        if isinstance(instances, dict):
            return instances
        if isinstance(instances, list) and instances:
            return instances[0]
        return None

    async def _find_best_offer(self) -> dict | None:
        SLOW = {"CN", "HK", "TW", "SG"}
        payload: dict = {
            "gpu_name":    {"in": VASTAI_ACCEPTED_GPUS},
            "num_gpus":    {"gte": 1},
            "gpu_ram":     {"gte": VASTAI_MIN_VRAM_GB * 1024},
            "reliability2":{"gte": 0.97},   # alta reliability (esclude host con proxy rotti)
            "inet_up":     {"gte": 200},     # almeno 200 Mbps upload (pull immagini Docker)
            "verified":    {"eq": True},
            "rentable":    {"eq": True},
            "type":        "ondemand",
            "limit":       20,
            "order":       [["dph_total", "asc"]],
        }
        if self.max_cost_per_hour < 999:
            payload["dph_total"] = {"lte": self.max_cost_per_hour}

        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{VAST_API_BASE}/bundles/", headers=_headers(self.api_key), json=payload)
            r.raise_for_status()
            offers = r.json().get("offers", [])

        if not offers:
            return None

        preferred, fallback = [], []
        for o in offers:
            country = o.get("geolocation", "").split(", ")[-1].strip()
            (fallback if country in SLOW or not country else preferred).append(o)

        best = (preferred or fallback)[0]
        logger.info(f"GPU scelta: {best.get('gpu_name')} ${best.get('dph_total',0):.3f}/h @ {best.get('geolocation','?')}")
        return best

    async def _create_instance(self, offer: dict) -> int:
        """
        Crea istanza con vastai/ollama in modalita' SSH.
        - runtype 'ssh': Vast.ai sostituisce entrypoint e onstart e' uno script bash
        - onstart installa e avvia Ollama + pull modello
        - env espone porta 11434 pubblicamente
        - VAST_TCP_PORT_11434 = porta pubblica assegnata (letta dopo running)
        """
        onstart = (
            # vastai/ollama ha gia' ollama installato, lo avviamo e facciamo pull
            f"ollama serve &\n"
            f"sleep 5\n"
            f"ollama pull {VASTAI_OLLAMA_MODEL}\n"
            f"echo OLLAMA_READY"
        )
        payload = {
            "image":          VASTAI_IMAGE,
            "label":          "igris-gpu",
            "disk":           40,
            "runtype":        "ssh",        # SSH mode: onstart e' script bash
            "target_state":   "running",
            "cancel_unavail": True,
            "env":            {"11434/tcp": [{"HostIp": "0.0.0.0", "HostPort": "11434"}]},
            "onstart":        onstart,
        }
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.put(
                f"{VAST_API_BASE}/asks/{offer['id']}/",
                headers=_headers(self.api_key),
                json=payload,
            )
            logger.debug(f"VastAI create: {r.status_code} {r.text[:200]}")
            r.raise_for_status()
            data = r.json()

        iid = data.get("new_contract")
        if not iid:
            raise RuntimeError(f"Nessun instance_id: {data}")
        logger.info(f"VastAI: istanza {iid} creata")
        return int(iid)

    async def _wait_for_running(
        self, instance_id: int, timeout_minutes: int = 12
    ) -> tuple[str, int, int] | None:
        """Ritorna (host, ssh_port, direct_port) quando running."""
        deadline = time.time() + timeout_minutes * 60
        elapsed  = 0
        while time.time() < deadline:
            await asyncio.sleep(15)
            elapsed += 15
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.get(
                        f"{VAST_API_BASE}/instances/{instance_id}/",
                        headers=_headers(self.api_key),
                    )
                    inst = self._parse_instance(r.json())

                if not inst:
                    continue

                status = inst.get("actual_status", "")
                logger.info(f"VastAI instance {instance_id}: {status} ({elapsed}s)")

                if status != "running":
                    continue

                host = inst.get("public_ipaddr") or inst.get("ssh_host", "")
                ssh_port_val = int(inst.get("ssh_port", 22))

                # VAST_TCP_PORT_11434 = porta pubblica mappata a 11434 interna
                # Disponibile nelle ports dict dopo running
                ports = inst.get("ports", {})
                tcp_11434 = ports.get("11434/tcp", []) if isinstance(ports, dict) else []
                if tcp_11434:
                    ollama_port = int(tcp_11434[0].get("HostPort", 11434))
                else:
                    # Fallback: direct_port_start
                    direct = inst.get("direct_port_start")
                    ollama_port = int(direct) if direct and int(direct) > 0 else VASTAI_OLLAMA_PORT

                if host:
                    logger.info(f"VastAI: host={host} ssh={ssh_port_val} ollama={ollama_port}")
                    return host, ssh_port_val, ollama_port

            except Exception as e:
                logger.debug(f"VastAI polling error: {e}")

        return None

    async def _setup_ollama_ssh(self, host: str, ssh_port: int, ollama_port: int) -> None:
        """
        Installa Ollama via SSH (paramiko) e lo avvia sulla direct port.
        Gira in un thread separato per non bloccare l'event loop.
        """
        script = (
            f"curl -fsSL https://ollama.com/install.sh | sh && "
            f"OLLAMA_HOST=0.0.0.0 OLLAMA_PORT={ollama_port} "
            f"nohup ollama serve > /tmp/ollama.log 2>&1 & "
            f"sleep 20 && ollama pull {VASTAI_OLLAMA_MODEL} && "
            f"echo OLLAMA_READY"
        )
        logger.info(f"VastAI: SSH setup Ollama su {host}:{ssh_port} porta={ollama_port}")

        def _run_ssh():
            try:
                import paramiko
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    hostname=host,
                    port=ssh_port,
                    username="root",
                    timeout=30,
                    look_for_keys=False,
                    allow_agent=False,
                )
                stdin, stdout, stderr = client.exec_command(script, timeout=900)
                out = stdout.read().decode()[:500]
                err = stderr.read().decode()[:200]
                client.close()
                if "OLLAMA_READY" in out:
                    logger.info(f"VastAI SSH: Ollama pronto! {out[-100:]}")
                else:
                    logger.warning(f"VastAI SSH: output={out[-200:]} err={err[-100:]}")
            except Exception as e:
                logger.error(f"VastAI SSH error: {e}")

        # Esegui in thread per non bloccare l'event loop asyncio
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _run_ssh)

    async def _log_proc(self, proc) -> None:
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=900)
            if out: logger.info(f"VastAI SSH: {out.decode()[:300]}")
            if err: logger.debug(f"VastAI SSH err: {err.decode()[:200]}")
        except asyncio.TimeoutError:
            pass

    async def _wait_for_ollama(self, host: str, port: int, timeout_minutes: int = 12) -> bool:
        """Polling HTTP su host:port/api/tags fino a risposta 200, poi pull modello."""
        deadline = time.time() + timeout_minutes * 60
        while time.time() < deadline:
            await asyncio.sleep(20)
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(f"http://{host}:{port}/api/tags")
                    if r.status_code == 200:
                        logger.info(f"VastAI: Ollama pronto su {host}:{port} - avvio pull {VASTAI_OLLAMA_MODEL}")
                        # Pull del modello via API HTTP
                        await self._pull_model(host, port)
                        return True
            except Exception:
                logger.debug(f"VastAI: {host}:{port} non risponde ancora...")
        return False

    async def _pull_model(self, host: str, port: int) -> None:
        """Scarica il modello via API Ollama."""
        try:
            async with httpx.AsyncClient(timeout=600) as c:
                logger.info(f"VastAI: pull {VASTAI_OLLAMA_MODEL} su {host}:{port}...")
                r = await c.post(
                    f"http://{host}:{port}/api/pull",
                    json={"name": VASTAI_OLLAMA_MODEL, "stream": False},
                    timeout=600,
                )
                if r.status_code == 200:
                    logger.info(f"VastAI: modello {VASTAI_OLLAMA_MODEL} scaricato!")
                else:
                    logger.warning(f"VastAI: pull risposta {r.status_code}: {r.text[:100]}")
        except Exception as e:
            logger.error(f"VastAI: pull error: {e}")

    async def _is_ollama_responsive(self) -> bool:
        if not self.state.host or not self.state.ollama_port:
            return False
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"http://{self.state.host}:{self.state.ollama_port}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def _fetch_active_instance(self) -> dict | None:
        """Interroga Vast.ai e ritorna la prima istanza running/loading dell'account (se esiste)."""
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{VAST_API_BASE}/instances/?owner=me", headers=_headers(self.api_key))
                r.raise_for_status()
                data = r.json()
            instances = data.get("instances", [])
            if isinstance(instances, dict):
                instances = list(instances.values())
            for inst in instances:
                status = inst.get("actual_status", "")
                if status in ("running", "loading", "provisioning"):
                    logger.info(f"VastAI: trovata istanza remota {inst.get('id')} status={status}")
                    return inst
            return None
        except Exception as e:
            logger.warning(f"VastAI: impossibile verificare istanze remote: {e}")
            return None
