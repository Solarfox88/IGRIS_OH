// IGRIS Chat UI - Main Application

const API_BASE = '';
let currentSessionId = null;
let isLoading = false;

// DOM Elements
const sidebar = document.getElementById('sidebar');
const sidebarNav = document.getElementById('sidebar-nav');
const welcomeScreen = document.getElementById('welcome-screen');
const chatArea = document.getElementById('chat-area');
const messagesContainer = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const btnNewProject = document.getElementById('btn-new-project');
const btnToggleSidebar = document.getElementById('btn-toggle-sidebar');
const chatTitle = document.getElementById('chat-title');
const chatMeta = document.getElementById('chat-meta');
const modelInfo = document.getElementById('model-info');
const costDisplay = document.getElementById('cost-display');
const statusDot = document.querySelector('.status-dot');
const statusText = document.querySelector('.status-text');
const tierSelect = document.getElementById('tier-select');
const modalOverlay = document.getElementById('modal-overlay');
const projectNameInput = document.getElementById('project-name-input');
const btnModalCancel = document.getElementById('btn-modal-cancel');
const btnModalCreate = document.getElementById('btn-modal-create');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
    loadStatus();
    setupEventListeners();
    autoResizeTextarea();
});

function setupEventListeners() {
    btnSend.addEventListener('click', sendMessage);
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    messageInput.addEventListener('input', autoResizeTextarea);
    btnNewChat.addEventListener('click', () => createNewSession());
    btnNewProject.addEventListener('click', showNewProjectModal);
    btnToggleSidebar.addEventListener('click', toggleSidebar);
    btnModalCancel.addEventListener('click', hideModal);
    btnModalCreate.addEventListener('click', createProject);
    projectNameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') createProject();
    });
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) hideModal();
    });
    tierSelect.addEventListener('change', onTierChange);
}

function autoResizeTextarea() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + 'px';
}

// API calls
async function apiCall(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${path}`, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'API error');
    }
    return res.json();
}

// Projects
async function loadProjects() {
    try {
        const data = await apiCall('GET', '/api/projects');
        renderSidebar(data.projects);
    } catch (err) {
        console.error('Failed to load projects:', err);
    }
}

function renderSidebar(projects) {
    sidebarNav.innerHTML = '';
    if (!projects || projects.length === 0) {
        sidebarNav.innerHTML = '<div style="padding: 16px; color: var(--text-muted); font-size: 13px;">Nessun progetto. Inizia una nuova chat!</div>';
        return;
    }
    projects.forEach(project => {
        const group = document.createElement('div');
        group.className = 'project-group';

        const header = document.createElement('div');
        header.className = 'project-header';
        header.innerHTML = `
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M6 9l6 6 6-6"/>
            </svg>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            ${escapeHtml(project.name)}
        `;

        const sessions = document.createElement('div');
        sessions.className = 'project-sessions';

        header.addEventListener('click', () => {
            header.classList.toggle('collapsed');
            sessions.classList.toggle('hidden');
        });

        if (project.sessions && project.sessions.length > 0) {
            project.sessions.forEach(session => {
                const item = document.createElement('div');
                item.className = 'session-item' + (session.id === currentSessionId ? ' active' : '');
                item.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                    </svg>
                    <span>${escapeHtml(session.title || 'New Chat')}</span>
                    <button class="delete-btn" title="Elimina">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 6L6 18M6 6l12 12"/>
                        </svg>
                    </button>
                `;
                item.querySelector('span').addEventListener('click', () => loadSession(session.id));
                item.querySelector('.delete-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    deleteSession(session.id);
                });
                sessions.appendChild(item);
            });
        }

        group.appendChild(header);
        group.appendChild(sessions);
        sidebarNav.appendChild(group);
    });
}

// Sessions
async function createNewSession(projectName = '') {
    try {
        const session = await apiCall('POST', '/api/sessions', { project_name: projectName });
        currentSessionId = session.id;
        showChatArea();
        clearMessages();
        chatTitle.textContent = session.title || 'Nuova Chat';
        loadProjects();
        messageInput.focus();
    } catch (err) {
        console.error('Failed to create session:', err);
        alert('Errore nella creazione della chat: ' + err.message);
    }
}

async function loadSession(sessionId) {
    try {
        const data = await apiCall('GET', `/api/sessions/${sessionId}`);
        currentSessionId = sessionId;
        showChatArea();
        clearMessages();
        chatTitle.textContent = data.title || 'Chat';
        tierSelect.value = data.llm_tier || 'auto';
        if (data.messages) {
            data.messages.forEach(msg => appendMessage(msg));
        }
        loadProjects();
        scrollToBottom();
        messageInput.focus();
    } catch (err) {
        console.error('Failed to load session:', err);
    }
}

async function deleteSession(sessionId) {
    if (!confirm('Eliminare questa chat?')) return;
    try {
        await apiCall('DELETE', `/api/sessions/${sessionId}`);
        if (currentSessionId === sessionId) {
            currentSessionId = null;
            showWelcome();
        }
        loadProjects();
    } catch (err) {
        console.error('Failed to delete session:', err);
    }
}

// Messages
async function sendMessage() {
    const content = messageInput.value.trim();
    if (!content || isLoading) return;

    if (!currentSessionId) {
        await createNewSession();
    }

    appendMessage({ role: 'user', content, timestamp: Date.now() / 1000 });
    messageInput.value = '';
    autoResizeTextarea();
    setLoading(true);

    const assistantDiv = createAssistantMessageDiv();
    messagesContainer.appendChild(assistantDiv);
    const contentEl = assistantDiv.querySelector('.message-content');
    const metaContainer = assistantDiv.querySelector('.message-meta-slot');
    let fullText = '';
    let thinkingStarted = false;
    scrollToBottom();

    // Avvia il thinking widget nel contenuto del messaggio
    startThinkingWidget(contentEl);

    try {
        const res = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/messages/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'API error');
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6).trim();
                if (!jsonStr) continue;

                try {
                    const chunk = JSON.parse(jsonStr);
                    if (chunk.type === 'token') {
                        // Primo token: rimuovi thinking widget
                        if (!thinkingStarted) {
                            stopThinkingWidget();
                            thinkingStarted = true;
                        }
                        fullText += chunk.content;
                        contentEl.innerHTML = formatContent(fullText);
                        scrollToBottom();
                    } else if (chunk.type === 'replace') {
                        stopThinkingWidget();
                        thinkingStarted = true;
                        fullText = chunk.content;
                        contentEl.innerHTML = formatContent(fullText);
                        scrollToBottom();
                    } else if (chunk.type === 'meta') {
                        stopThinkingWidget();
                        const tierLabel = chunk.tier === 'local' ? 'Locale' : chunk.tier === 'api' ? 'API' : chunk.tier === 'vastai' ? 'GPU' : '';
                        metaContainer.innerHTML = `
                            <div class="message-meta">
                                ${tierLabel ? `<span class="tier-${chunk.tier}">${tierLabel}</span>` : ''}
                                ${chunk.model ? `<span>${chunk.model}</span>` : ''}
                                ${chunk.tokens ? `<span>${chunk.tokens} tokens</span>` : ''}
                                ${chunk.cost ? `<span>${chunk.cost.toFixed(4)}</span>` : ''}
                                ${chunk.latency ? `<span>${chunk.latency}s</span>` : ''}
                            </div>
                        `;
                        if (chunk.cost) updateCost(chunk.cost);
                        if (chunk.tier === 'vastai') checkVPSStatus();
                    } else if (chunk.type === 'error') {
                        stopThinkingWidget();
                        fullText = chunk.content;
                        contentEl.innerHTML = formatContent(fullText);
                    }
                } catch (parseErr) {
                    console.warn('Failed to parse SSE chunk:', jsonStr, parseErr);
                }
            }
        }
        loadProjects();
    } catch (err) {
        stopThinkingWidget();
        contentEl.innerHTML = formatContent(`Errore: ${err.message}. Controlla che Ollama sia in esecuzione.`);
    }

    stopThinkingWidget(); // safety net
    setLoading(false);
    scrollToBottom();
}

function createAssistantMessageDiv() {
    const div = document.createElement('div');
    div.className = 'message';
    const time = new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
    div.innerHTML = `
        <div class="message-header">
            <div class="message-avatar assistant">I</div>
            <span class="message-name">IGRIS</span>
            <span class="message-time">${time}</span>
        </div>
        <div class="message-content"><span class="streaming-cursor"></span></div>
        <div class="message-meta-slot"></div>
    `;
    return div;
}

function appendMessage(msg) {
    const div = document.createElement('div');
    div.className = 'message';

    const isUser = msg.role === 'user';
    const name = isUser ? 'Tu' : 'IGRIS';
    const avatarClass = isUser ? 'user' : 'assistant';
    const avatarLetter = isUser ? 'C' : 'I';
    const time = msg.timestamp ? new Date(msg.timestamp * 1000).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : '';

    let metaHtml = '';
    if (msg.metadata && !isUser) {
        const tier = msg.metadata.tier || '';
        const tierClass = `tier-${tier}`;
        const tierLabel = tier === 'local' ? 'Locale' : tier === 'api' ? 'API' : tier === 'vastai' ? 'GPU' : '';
        const tokens = msg.metadata.tokens || '';
        const cost = msg.metadata.cost ? `$${msg.metadata.cost.toFixed(4)}` : '';
        const latency = msg.metadata.latency ? `${msg.metadata.latency}s` : '';
        const actions = msg.metadata.actions_executed || 0;
        metaHtml = `
            <div class="message-meta">
                ${tierLabel ? `<span class="${tierClass}">${tierLabel}</span>` : ''}
                ${msg.metadata.model ? `<span>${msg.metadata.model}</span>` : ''}
                ${tokens ? `<span>${tokens} tokens</span>` : ''}
                ${cost ? `<span>${cost}</span>` : ''}
                ${latency ? `<span>${latency}</span>` : ''}
                ${actions > 0 ? `<span class="actions-badge">${actions} azioni eseguite</span>` : ''}
            </div>
        `;
    }

    div.innerHTML = `
        <div class="message-header">
            <div class="message-avatar ${avatarClass}">${avatarLetter}</div>
            <span class="message-name">${name}</span>
            <span class="message-time">${time}</span>
        </div>
        <div class="message-content">${formatContent(msg.content)}</div>
        ${metaHtml}
    `;

    messagesContainer.appendChild(div);
    scrollToBottom();
}

function formatContent(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    html = html.replace(/\[CMD\](.*?)\[\/CMD\]/gs, function(match, cmd) {
        return '<div class="execution-block pending"><div class="exec-header">$ ' + cmd.trim() + '</div><div class="exec-output pending-output">in esecuzione...</div></div>';
    });
    html = html.replace(/\[WRITE_FILE\s+path=["']([^"']+)["']\][\s\S]*?\[\/WRITE_FILE\]/g, function(match, path) {
        return '<div class="execution-block pending"><div class="exec-header">WRITE ' + path + '</div><div class="exec-output pending-output">scrittura in corso...</div></div>';
    });
    html = html.replace(/```\n\$ (.*?)\n([\s\S]*?)```/g, function(match, cmd, output) {
        return '<div class="execution-block"><div class="exec-header">$ ' + cmd + '</div><pre class="exec-output">' + output.trim() + '</pre></div>';
    });
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function showTyping() {
    const div = document.createElement('div');
    div.className = 'message';
    div.id = 'typing-indicator';
    div.innerHTML = `
        <div class="message-header">
            <div class="message-avatar assistant">I</div>
            <span class="message-name">IGRIS</span>
        </div>
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    messagesContainer.appendChild(div);
    scrollToBottom();
}

function hideTyping() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

function showChatArea() {
    welcomeScreen.style.display = 'none';
    chatArea.style.display = 'flex';
}

function showWelcome() {
    welcomeScreen.style.display = 'flex';
    chatArea.style.display = 'none';
}

function clearMessages() {
    messagesContainer.innerHTML = '';
}

function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function setLoading(loading) {
    isLoading = loading;
    btnSend.disabled = loading;
}

function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
}

function showNewProjectModal() {
    modalOverlay.style.display = 'flex';
    projectNameInput.value = '';
    projectNameInput.focus();
}

function hideModal() {
    modalOverlay.style.display = 'none';
}

async function createProject() {
    const name = projectNameInput.value.trim();
    if (!name) return;
    try {
        await apiCall('POST', '/api/projects', { name });
        hideModal();
        loadProjects();
        createNewSession(name);
    } catch (err) {
        alert('Errore: ' + err.message);
    }
}

async function loadStatus() {
    try {
        const data = await apiCall('GET', '/api/status');
        statusDot.classList.remove('offline');
        statusText.textContent = 'Connesso';
        modelInfo.textContent = `LLM: ${data.llm_local.provider}/${data.llm_local.model}`;
        if (data.cost) {
            costDisplay.textContent = `Costo sessione: $${data.cost.total_cost.toFixed(4)}`;
        }
    } catch (err) {
        statusDot.classList.add('offline');
        statusText.textContent = 'Disconnesso';
        modelInfo.textContent = 'LLM non raggiungibile';
    }
}

function updateCost(additionalCost) {
    const current = parseFloat(costDisplay.textContent.replace(/[^0-9.]/g, '') || '0');
    costDisplay.textContent = `Costo sessione: $${(current + additionalCost).toFixed(4)}`;
}

function sendExample(text) {
    messageInput.value = text;
    sendMessage();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Thinking widget ─────────────────────────────────────────────────────

const THINKING_PHRASES = [
    "Analizzo la richiesta...",
    "Elaboro una risposta...",
    "Consulto la memoria di contesto...",
    "Ragiono sul problema...",
    "Verifico le opzioni disponibili...",
    "Costruisco il piano di esecuzione...",
    "Preparo i comandi necessari...",
    "Valuto l'approccio migliore...",
    "Processo le informazioni...",
    "Sto pensando...",
];

const TIER_LABELS = {
    local:  { label: 'Ollama/phi4-mini',    cls: 'tier-local'  },
    api:    { label: 'OpenAI API',     cls: 'tier-api'    },
    vastai: { label: 'GPU DeepSeek',   cls: 'tier-vastai' },
    auto:   { label: 'Auto',           cls: 'tier-local'  },
};

function createThinkingWidget() {
    const tier = document.getElementById('tier-select')?.value || 'auto';
    const tierInfo = TIER_LABELS[tier] || TIER_LABELS.auto;
    const phrase = THINKING_PHRASES[Math.floor(Math.random() * THINKING_PHRASES.length)];

    const el = document.createElement('div');
    el.className = 'igris-thinking';
    el.id = 'igris-thinking-widget';
    el.innerHTML = `
        <div class="igris-thinking-top">
            <div class="igris-orbs">
                <div class="igris-orb"></div>
                <div class="igris-orb"></div>
                <div class="igris-orb"></div>
            </div>
            <div class="igris-tier-badge ${tierInfo.cls}">
                <div class="tier-dot"></div>
                ${tierInfo.label}
            </div>
        </div>
        <div class="igris-thinking-text" id="igris-thinking-text">${phrase}</div>
        <div class="igris-thinking-bar"><div class="igris-thinking-bar-fill"></div></div>
    `;
    return el;
}

function startThinkingWidget(container) {
    // Rimuovi eventuale widget precedente
    stopThinkingWidget();
    const widget = createThinkingWidget();
    container.appendChild(widget);

    // Rotazione frasi ogni 2.5s
    window._thinkingInterval = setInterval(() => {
        const textEl = document.getElementById('igris-thinking-text');
        if (!textEl) return;
        const next = THINKING_PHRASES[Math.floor(Math.random() * THINKING_PHRASES.length)];
        textEl.style.animation = 'none';
        textEl.offsetHeight; // reflow
        textEl.style.animation = '';
        textEl.textContent = next;
    }, 2500);
}

function stopThinkingWidget() {
    clearInterval(window._thinkingInterval);
    const w = document.getElementById('igris-thinking-widget');
    if (w) w.remove();
}

// Aggiorna il tier badge nel widget mentre arrivano i token
function updateThinkingTier(tier) {
    const badge = document.querySelector('#igris-thinking-widget .igris-tier-badge');
    if (!badge) return;
    const tierInfo = TIER_LABELS[tier] || TIER_LABELS.auto;
    badge.className = `igris-tier-badge ${tierInfo.cls}`;
    badge.innerHTML = `<div class="tier-dot"></div>${tierInfo.label}`;
}

// ============================================================
// VPS GPU — gestione centralizzata, guard anti-duplicazione
// ============================================================
let vpsActive = false;
let vpsPollInterval = null;

// Stato VPS globale — unica fonte di verita'
const VPS = { status: 'offline', instanceId: null, model: null };

// Aggiorna pulsanti VPS (homepage + chat header) e label tier-select
function updateVPSButtons(state, labelText) {
    vpsActive = (state === 'active' || state === 'provisioning');

    ['vps-btn', 'vps-btn-chat'].forEach(id => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.classList.remove('active', 'provisioning');
        if (state === 'active')      btn.classList.add('active');
        if (state === 'provisioning') btn.classList.add('provisioning');
        btn.disabled = (state === 'loading');
    });
    ['vps-label', 'vps-label-chat'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = labelText;
    });

    // Aggiorna label opzione GPU nel tier-select
    const ts = document.getElementById('tier-select');
    if (ts) {
        const opt = ts.querySelector('option[value="vastai"]');
        if (opt) {
            if (state === 'active')       opt.textContent = 'GPU (Vast.ai) — PRONTA';
            else if (state === 'provisioning') opt.textContent = 'GPU (Vast.ai) — avvio...';
            else                           opt.textContent = 'GPU (Vast.ai)';
        }
    }
}

async function toggleVPS() {
    if (!vpsActive) {
        // --- Attiva VPS ---
        // Prima controlla se esiste gia' un'istanza (guard anti-duplicazione)
        updateVPSButtons('loading', 'Controllo istanze...');
        try {
            const resp = await apiCall('POST', '/api/vastai/vps/start');
            if (resp.synced) {
                // Istanza gia' esistente — sincronizzata, nessuna duplicazione
                console.log('[VPS] istanza esistente sincronizzata:', resp.instance_id, resp.status);
            }
            vpsActive = true;
            if (resp.status === 'ready') {
                updateVPSButtons('active', 'VPS ON');
            } else {
                updateVPSButtons('provisioning', 'VPS in avvio...');
            }
            startVPSPolling();
        } catch (err) {
            updateVPSButtons('off', 'Attiva VPS GPU');
            alert('Errore avvio VPS: ' + err.message);
        }
    } else {
        // --- Spegni VPS ---
        if (!confirm('Spegnere il server GPU?\nL\'istanza verra\' distrutta e non ci saranno piu\' costi.')) return;
        updateVPSButtons('loading', 'Spegnimento...');
        stopVPSPolling();
        try {
            await apiCall('POST', '/api/vastai/vps/stop');
        } catch (err) {
            console.error('VPS stop error:', err);
        }
        vpsActive = false;
        VPS.status = 'offline';
        updateVPSButtons('off', 'Attiva VPS GPU');
    }
}

function startVPSPolling() {
    stopVPSPolling();
    vpsPollInterval = setInterval(checkVPSStatus, 10000);
    checkVPSStatus();
}

function stopVPSPolling() {
    if (vpsPollInterval) {
        clearInterval(vpsPollInterval);
        vpsPollInterval = null;
    }
}

async function checkVPSStatus() {
    try {
        const s = await apiCall('GET', '/api/vastai/vps/status');
        VPS.status     = s.status;
        VPS.instanceId = s.instance_id;
        VPS.model      = s.model;

        if (s.status === 'ready') {
            vpsActive = true;
            const gpu  = s.model || 'DeepSeek-R1';
            const cost = s.cost_per_hour ? ` ~$${parseFloat(s.cost_per_hour).toFixed(3)}/h` : '';
            const age  = s.age_minutes   ? ` (${Math.round(s.age_minutes)}min)` : '';
            updateVPSButtons('active', `VPS ON \u2022 ${gpu}${cost}${age}`);
            stopVPSPolling();
            vpsPollInterval = setInterval(checkVPSStatus, 60000); // polling lento

        } else if (s.status === 'provisioning' || s.status === 'running') {
            vpsActive = true;
            const elapsed = s.age_minutes ? `${Math.round(s.age_minutes * 60)}s` : '';
            updateVPSButtons('provisioning', `VPS in avvio... ${elapsed}`);

        } else if (s.status === 'error') {
            vpsActive = false;
            updateVPSButtons('off', 'VPS errore \u2014 riprova');
            stopVPSPolling();

        } else {
            // offline
            if (!s.persistent) {
                vpsActive = false;
                updateVPSButtons('off', 'Attiva VPS GPU');
                stopVPSPolling();
            }
        }
    } catch (err) {
        console.warn('VPS status check failed:', err);
    }
}

// Tier-select: se si seleziona GPU, avvia VPS automaticamente se non attiva
async function onTierChange() {
    if (!currentSessionId) return;
    const tier = tierSelect.value;
    try {
        await apiCall('PUT', `/api/sessions/${currentSessionId}/tier`, { tier });
        const labels = { auto: 'Auto', local: 'Ollama locale', api: 'OpenAI API', vastai: 'GPU (Vast.ai)' };
        modelInfo.textContent = `Modalita': ${labels[tier] || tier}`;

        if (tier === 'vastai') {
            if (!vpsActive) {
                // VPS non attiva — chiedi conferma e avvia
                const ok = confirm(
                    'Per usare la GPU devo avviare il server Vast.ai.\n' +
                    'Costo stimato: ~$0.15/h — Procedo?'
                );
                if (ok) {
                    await toggleVPS(); // avvia VPS e aggiorna pulsante
                } else {
                    // Annulla: torna ad auto
                    tierSelect.value = 'auto';
                    await apiCall('PUT', `/api/sessions/${currentSessionId}/tier`, { tier: 'auto' });
                    modelInfo.textContent = 'Modalita\': Auto';
                }
            } else {
                // VPS gia' attiva — aggiorna pulsante con stato corrente
                checkVPSStatus();
            }
        }
    } catch (err) {
        console.error('Failed to set tier:', err);
    }
}

// All'avvio: controlla se VPS era gia' accesa e ripristina il pulsante
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(checkVPSStatus, 2000);
});
