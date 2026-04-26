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
    showTyping();
    setLoading(true);

    try {
        const response = await apiCall('POST', `/api/sessions/${currentSessionId}/messages`, { content });
        hideTyping();
        appendMessage(response);
        if (response.metadata?.cost) {
            updateCost(response.metadata.cost);
        }
        loadProjects();
    } catch (err) {
        hideTyping();
        appendMessage({
            role: 'assistant',
            content: `Errore: ${err.message}. Controlla che Ollama sia in esecuzione.`,
            timestamp: Date.now() / 1000,
            metadata: { error: true }
        });
    }

    setLoading(false);
    scrollToBottom();
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
        metaHtml = `
            <div class="message-meta">
                ${tierLabel ? `<span class="${tierClass}">${tierLabel}</span>` : ''}
                ${msg.metadata.model ? `<span>${msg.metadata.model}</span>` : ''}
                ${tokens ? `<span>${tokens} tokens</span>` : ''}
                ${cost ? `<span>${cost}</span>` : ''}
                ${latency ? `<span>${latency}</span>` : ''}
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
    // Escape HTML
    let html = escapeHtml(text);
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
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

// UI State
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

// Modal
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

// Status
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

// Example messages
function sendExample(text) {
    messageInput.value = text;
    sendMessage();
}

// Utility
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Refresh status every 30s
setInterval(loadStatus, 30000);
