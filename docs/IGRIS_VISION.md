# IGRIS — Visione Strategica

Fonte di verità per roadmap, architettura e principi di progettazione.

Ultimo aggiornamento: 2026-05-01

---

## 1) Contesto Strategico

IGRIS è il mio sostituto personale di Devin.ai per uso personale: un AI engineering agent
locale, controllabile, economico, estendibile, repo-aware, anti-loop e orientato al
forward progress reale. Non è un semplice chatbot che “lancia comandi”, ma un
operatore autonomo di sviluppo capace di:

- leggere e comprendere una codebase;  
- mantenere contesto operativo persistente;  
- pianificare il lavoro;  
- proporre ed eseguire task;  
- aggiornare stato e report;  
- fare patch locali;  
- lavorare con Git/GitHub;  
- usare loop autonomi;  
- fermarsi, diagnosticare e correggersi;  
- cambiare strategia se bloccato;  
- evitare loop improduttivi;  
- aumentare autonomia con l’esperienza (memoria/teacher).

Predefinito modello LLM locale: phi4-mini (Ollama).  
Altre opzioni locali sono consentite come alternative, ma il default non va cambiato.

---

## 2) Obiettivi Architetturali e Layer

L’architettura di IGRIS è stratificata e orientata a responsabilità chiare.

1. Project Context Layer  
   - Lettura repo; stato progetto; task attivi/bloccati/completati;  
   - Report/logs; memoria operativa; decisioni precedenti;  
   - Esporta “riassunti” coerenti per i livelli superiori.

2. Task Intelligence Layer  
   - Classificazione task in famiglie; deduplica semantica;  
   - Saturation/family counting; gestione “blocked”;  
   - Selezione del “best next task” coerente con governance anti‑loop.

3. Advisory Layer  
   - Richiesta advisory a modello/API; parsing/validazione robusti;  
   - Priorità al best next task; rispetto di segnali chiari (es. next_task_file).  

4. Teacher Layer  
   - Costruzione payload diagnostico; repo context notes; recovery pattern;  
   - Fallback policy; assignment generation; escalation policy;  
   - Capacità di “rompere” loop improduttivi e forzare strategy shift.

5. Execution Layer  
   - Command runner locale; safe-first; cattura stdout/stderr/rc;  
   - Log comandi locali; blocco comandi rischiosi quando richiesto.

6. Validation Layer  
   - Self-test post-esecuzione; grading; diagnostica;  
   - Report generation; verifica obiettivi step.

7. Git Layer  
   - Commit sensati; pull --rebase prima del push;  
   - Push; awareness dei conflitti; rollback/checkpoint.

---

## 3) Requisiti Chiave (Linee Guida)

- Forward progress reale e misurabile;  
- Anti‑loop (family saturation, semantic dedup, observation‑loop detection);  
- Best‑task fidelity e forced strategy shift;  
- Teacher recovery forte e blocked‑task handling;  
- Candidate materialization;  
- Outcome‑/cost‑aware routing;  
- Self‑test dopo ogni esecuzione, con report JSON/Markdown;  
- Git workflow robusto;  
- Local‑first, safe‑first, repo‑aware;  
- Default locale: phi4‑mini (non sovrascrivere con mistral).

---

## 4) Principi Operativi

- “Do the work”: non solo descrivere, ma produrre patch/commit verificabili.  
- Anti‑loop by design: preferire azioni che sbloccano il progresso.  
- Separazione dei ruoli: advisory ≠ decisione; teacher ≠ advisor; execution ≠ planning.  
- Report e trasparenza: ogni azione lascia tracce (log, report, stato).  
- Sicurezza pragmatica: default permissivo in locale, opt‑in sandbox dove serve.  
- Coerenza di configurazione/test/documentazione.

---

## 5) Roadmap ad Alto Livello (Guida)

- Fase 1 — MVP robusto  
  Stabilità base, coerenza config/test/docs, self‑test, safety minima, git workflow,
  router funzionante, report chiari.

- Fase 2 — Autonomia matura  
  Family saturation completa, semantic dedup solida, best‑task fidelity, escalation
  dei blocked, candidate materialization robusta, teacher payload potenziato.

- Fase 3 — Sostituto personale di Devin  
  Pianificazione multi‑step, branch/PR planning, review/rollback governance,
  autodidattica operativa, vera gestione strategica del progetto.

---

## 6) Default LLM Locale

- Provider: Ollama  
- Modello: phi4‑mini (default)  
- Alternative: Mistral, Qwen2.5‑Coder, ecc. (su richiesta/contesto)  
- Nota: se la documentazione o i test indicano “mistral” come default, vanno aggiornati.

---

## 7) Metriche di Successo

- % di cicli con forward progress (self‑test/diagnostica positivi).  
- Riduzione loop/ri‑tentativi inutili; aumento “task completati”/cicli.  
- Tempo medio a completamento step; costo medio per richiesta.  
- Stabilità git (conflitti rari e correttamente gestiti).  
- Qualità dei report: chiari, azionabili, ripetibili.

---

## 8) Glossario

- Forward progress: cambiamenti tangibili verso l’obiettivo (file modificati, test che passano, commit).  
- Saturation: limite di ripetizioni per famiglia di task per prevenire loop.  
- Best‑task fidelity: rispetto del task migliore suggerito (se valido).  
- Candidate materialization: generazione esplicita dei candidati (file/patch/step) prima dell’esecuzione.  
- Outcome‑aware routing: scelta tier LLM in base a costo/tempo/risultati attesi e reali.

---

> Questo documento è la fonte di verità per la roadmap e l’evoluzione di IGRIS.
> Ogni modifica sostanziale a obiettivi o principi deve essere riflessa qui.
