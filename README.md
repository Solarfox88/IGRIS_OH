# IGRIS - AI Engineering Agent

**Il tuo sostituto personale di Devin.ai** — locale, economico, trasparente, controllabile.

IGRIS è un agente AI autonomo di ingegneria software che gira sul tuo PC. Può leggere, capire e modificare qualsiasi codebase, pianificare ed eseguire task, gestire Git/GitHub, e portare avanti progetti in modo affidabile.

---

## Caratteristiche Principali

- **LLM Locale** (Ollama + phi4-mini di default; Mistral/Qwen2.5-Coder come alternative) — veloce, gratuito, privato
- **LLM API** (OpenAI) — fallback per task complessi
- **GPU On-Demand** (Vast.ai RTX 4090 ~€0.30/h) — per computazione pesante
- **Loop Autonomo** con anti-loop governance e teacher recovery
- **Task Engine** con classificazione in famiglie, deduplicazione semantica, saturazione
- **Esecuzione Sicura** — comandi validati, path bloccati, safety checks
- **Git Robusto** — commit, push, rebase, conflict awareness automatici
- **Self-Test** — verifica automatica dopo ogni esecuzione
- **Diagnostica** — identifica pattern problematici e blocchi
- **Web UI** — interfaccia chat stile ChatGPT con progetti e conversazioni
- **CLI** — gestione completa da terminale

---

## Requisiti Hardware (Testato)

- **CPU:** Intel Core i5-1035G1 @ 1.00GHz (o superiore)
- **RAM:** 16 GB (minimo 8 GB)
- **Storage:** ~10 GB liberi per modelli LLM
- **OS:** Windows 10/11, Linux, macOS

---

## Installazione Rapida

### 1. Prerequisiti

```bash
# Python 3.10+
python --version

# Git
git --version
```

### 2. Installa Ollama (LLM Locale)

```bash
# Windows: scarica da https://ollama.com/download/windows
# oppure:
winget install Ollama.Ollama

# Linux:
curl -fsSL https://ollama.com/install.sh | sh

# macOS:
brew install ollama
```

### 3. Scarica i modelli consigliati

```bash
# Avvia Ollama
ollama serve

# In un altro terminale, scarica i modelli:
ollama pull phi4-mini         # default leggero e buon ragionamento
ollama pull mistral           # alternativa bilanciata (4.1 GB)
ollama pull qwen2.5-coder:7b  # alternativa ottima per codice (4.7 GB)
```

### 4. Installa IGRIS

```bash
# Clona il repository
git clone https://github.com/Solarfox88/IGRIS_DEVIN.git
cd IGRIS_DEVIN

# Crea virtual environment
python -m venv .venv

# Attiva (Windows)
.venv\Scripts\activate

# Attiva (Linux/Mac)
source .venv/bin/activate

# Installa
pip install -e ".[dev]"
```

### 5. Configurazione

```bash
# Inizializza IGRIS nel tuo progetto
cd /percorso/del/tuo/progetto
igris init

# Modifica .igris/config.json per personalizzare:
# - Modello LLM locale
# - API key OpenAI (fallback)
# - API key Vast.ai (GPU)
```

---

## Utilizzo

### Web UI (Consigliata)

```bash
# Avvia l'interfaccia web
igris web

# Apri nel browser: http://localhost:7777
```

L'interfaccia web offre:
- **Sidebar** con progetti e conversazioni
- **Chat** con IGRIS (identità propria, non LLM generico)
- **Nuova chat / nuovo progetto** con un click
- **Metadati** (modello usato, costo, latenza) per ogni risposta
- **Temi scuri** stile ChatGPT

### CLI

```bash
# Stato del progetto
igris status

# Chat rapida
igris chat "Crea un API REST con FastAPI per gestire utenti"

# Loop autonomo (max 10 cicli)
igris run -n 10

# Diagnostica
igris diagnose

# Configurazione
igris config
```

### Loop Autonomo

```bash
# Avvia il loop autonomo sul progetto corrente
igris run --max-cycles 20
```

Il loop autonomo:
1. Legge il contesto del progetto
2. Identifica il prossimo task utile
3. Esegue in sicurezza
4. Verifica con self-test
5. Fa commit automatico
6. Rivaluta e riparte

---

## Architettura

```
igris/
├── core/
│   ├── identity.py          # Identità e personalità IGRIS
│   ├── autonomous_loop.py   # Loop di esecuzione autonomo
│   └── chat_engine.py       # Motore conversazione
├── layers/
│   ├── context/             # Project Context Layer
│   │   └── project_reader.py
│   ├── task/                # Task Intelligence Layer
│   │   ├── selector.py      # Selezione task con anti-loop
│   │   └── deduplicator.py  # Deduplicazione semantica
│   ├── advisory/            # Advisory Layer (LLM routing)
│   │   ├── router.py        # Router LLM locale/API/Vast.ai
│   │   └── advisor.py       # Generazione advisory
│   ├── teacher/             # Teacher Layer (recovery)
│   │   └── teacher.py       # Diagnosi e remediation
│   ├── execution/           # Execution Layer
│   │   └── runner.py        # Esecuzione comandi sicura
│   ├── validation/          # Validation Layer
│   │   ├── self_test.py     # Self-test automatici
│   │   └── diagnostics.py   # Diagnostica sistema
│   └── git_layer/           # Git Layer
│       └── git_ops.py       # Operazioni Git robuste
├── models/                  # Data models (Pydantic)
│   ├── task.py              # Task, TaskFamily, TaskStatus
│   ├── report.py            # ExecutionReport, SelfTestReport
│   ├── config.py            # IgrisConfig
│   └── state.py             # ProjectState, Saturation
├── web/                     # Web UI
│   ├── server.py            # FastAPI server
│   ├── templates/           # HTML templates
│   └── static/              # CSS + JS
├── cli/                     # CLI (Click)
│   └── main.py
└── scripts/                 # Setup scripts
    ├── setup_ollama.py
    └── setup_vastai.py
```

---

## Gerarchia LLM (Costo Ottimizzato)

| Tier | Provider | Modello | Quando | Costo |
|------|----------|---------|--------|-------|
| **Locale** | Ollama | phi4-mini | Task routine, chat, analisi semplici | **Gratis** |
| **API** | OpenAI | GPT-4o-mini | Ragionamento complesso, prompt lunghi | ~$0.15/1M tokens |
| **GPU** | Vast.ai | RTX 4090 | Computazione pesante, modelli grandi | ~€0.30/h |

IGRIS sceglie automaticamente il tier più economico basandosi sulla complessità della richiesta.

---

## Anti-Loop Governance

IGRIS implementa governance anti-loop rigorosa:

- **Family Saturation**: dopo 3 ripetizioni di una famiglia di task, viene bloccata
- **Semantic Dedup**: rileva task semanticamente equivalenti anche con titoli diversi
- **Observation Loop Detection**: limita task osservative consecutive
- **Forced Strategy Shift**: dopo 3 ripetizioni, cambio famiglia obbligatorio
- **Teacher Recovery**: quando bloccato, un modulo "docente" diagnostica e assegna remediation
- **Best-Task Fidelity**: se l'advisory suggerisce un task chiaro, il sistema lo rispetta

---

## Configurazione Dettagliata

Il file `.igris/config.json` controlla tutto:

```json
{
  "project_name": "mio-progetto",
  "local_llm": {
    "provider": "ollama",
    "model": "phi4-mini",
    "base_url": "http://localhost:11434",
    "temperature": 0.3
  },
  "fallback_llm": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "api_key": "sk-..."
  },
  "vastai": {
    "api_key": "...",
    "gpu_type": "RTX_4090",
    "max_cost_per_hour": 0.50
  },
  "safety": {
    "sandbox_mode": false,
    "max_command_duration_seconds": 300
  },
  "anti_loop": {
    "max_family_repetitions": 3,
    "max_total_cycles": 50,
    "semantic_similarity_threshold": 0.85
  },
  "auto_commit": true,
  "auto_push": false
}
```

---

## Sviluppo

```bash
# Installa dipendenze dev
pip install -e ".[dev]"

# Test
pytest

# Lint
ruff check igris/

# Type check
mypy igris/
```

---

## Roadmap

### Fase 1 — MVP (Attuale)
- [x] Loop autonomo locale
- [x] Selezione task con anti-loop
- [x] Self-test e commit robusti
- [x] Teacher recovery
- [x] Web UI chat
- [x] CLI completa

### Fase 2 — Autonomia Matura
- [ ] Family saturation avanzata con cooldown intelligente
- [ ] Semantic dedup con embeddings (sentence-transformers)
- [ ] Candidate materialization robusta
- [ ] Blocked-task escalation automatica
- [ ] Integrazione Vast.ai completa con auto-provisioning GPU

### Fase 3 — Sostituto Completo di Devin
- [ ] Pianificazione multi-step
- [ ] Branch/PR planning automatico
- [ ] Review/rollback governance
- [ ] Autodidattica operativa
- [ ] Plugin system per estensioni custom
- [ ] Multi-progetto simultaneo

---

## Licenza

MIT License — vedi [LICENSE](LICENSE)
