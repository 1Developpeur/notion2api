(() => {
  const THREADS_ENDPOINT = '/v1/chat-history/threads';
  const PAGE_SIZE = 50;
  const REMOTE_ID_PREFIX = 'remote-chat-history:';
  const state = {
    threads: [],
    offset: 0,
    hasMore: false,
    loading: false,
    activeThreadId: null,
    patched: false
  };

  function getBaseUrl() {
    if (window.NotionAI?.Core?.State?.get) {
      return window.NotionAI.Core.State.get('baseUrl') || window.location.origin;
    }
    return localStorage.getItem('claude_base_url') || window.location.origin;
  }

  function getApiKey() {
    if (window.NotionAI?.Core?.State?.get) {
      return window.NotionAI.Core.State.get('apiKey') || '';
    }
    return localStorage.getItem('claude_api_key') || sessionStorage.getItem('claude_api_key') || '';
  }

  function getHeaders() {
    const headers = { 'Accept': 'application/json', 'X-Client-Type': 'Web' };
    const key = getApiKey();
    if (key) headers.Authorization = `Bearer ${key}`;
    return headers;
  }

  function esc(value) {
    const node = document.createElement('div');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

  function ensureStyles() {
    if (document.getElementById('chatHistoryMainStyles')) return;
    const style = document.createElement('style');
    style.id = 'chatHistoryMainStyles';
    style.textContent = `
      .chat-history-main-day{font-size:10px;text-transform:uppercase;color:var(--text-tertiary);letter-spacing:.08em;padding:8px 16px 3px}
      .chat-item.chat-history-main-item{align-items:flex-start;gap:8px;padding-top:7px;padding-bottom:7px}
      .chat-history-main-text{min-width:0;flex:1;display:flex;flex-direction:column;gap:2px}
      .chat-history-main-meta{font-size:10px;color:var(--text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .chat-history-main-dot{width:7px;height:7px;border-radius:999px;margin-top:6px;flex-shrink:0;background:var(--text-tertiary);opacity:.7}
      .chat-history-main-dot.hydrated{background:#2e7d32;opacity:1}
      .chat-history-main-load{width:calc(100% - 24px);margin:6px 12px;padding:6px 8px;border-radius:4px;font-size:12px;color:var(--text-secondary);background:transparent;text-align:left}
      .chat-history-main-load:hover{background:var(--bg-hover);color:var(--text)}
      .chat-history-main-status{max-width:720px;margin:32px auto;padding:0 24px;color:var(--text-secondary);font-size:14px;line-height:1.6}
      .chat-history-steps{max-width:720px;margin:18px auto;color:var(--text-secondary);font-size:13px}
      .chat-history-steps summary{cursor:pointer;display:flex;align-items:center;gap:8px;width:max-content;list-style:none}
      .chat-history-steps summary::-webkit-details-marker{display:none}
      .chat-history-steps summary::after{content:'›';font-size:20px;line-height:1;transform:translateY(-1px)}
      .chat-history-steps[open] summary::after{transform:rotate(90deg)}
      .chat-history-step-list{margin-top:10px;border-left:1px solid var(--border);padding-left:14px;display:flex;flex-direction:column;gap:8px}
      .chat-history-step-item{color:var(--text-tertiary);font-size:12px;line-height:1.4}
      .chat-history-step-item strong{color:var(--text-secondary);font-weight:500}
    `;
    document.head.appendChild(style);
  }

  function threadTimestamp(thread) {
    const value = thread.updated_at || thread.last_edited_time || thread.created_time || '';
    if (typeof value === 'number') return value;
    const text = String(value || '').trim();
    if (/^\d+$/.test(text)) return Number(text);
    const parsed = Date.parse(text);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function dayLabel(thread) {
    const ts = threadTimestamp(thread);
    if (!ts) return 'Unknown date';
    const date = new Date(ts);
    if (Number.isNaN(date.getTime())) return 'Unknown date';
    const today = new Date();
    const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
    const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    const diffDays = Math.round((startToday - startDate) / 86400000);
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function setInputArchivedMode(enabled) {
    const input = document.getElementById('chatInput');
    const send = document.getElementById('sendBtn');
    if (input) {
      if (!input.dataset.localPlaceholder) input.dataset.localPlaceholder = input.placeholder || '';
      input.disabled = enabled;
      input.placeholder = enabled ? 'Archived chat selected' : input.dataset.localPlaceholder;
    }
    if (send) send.disabled = enabled;
  }

  function clearRemoteSelection() {
    state.activeThreadId = null;
    setInputArchivedMode(false);
  }

  async function fetchJson(path) {
    const response = await fetch(`${getBaseUrl()}${path}`, { headers: getHeaders() });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const message = data?.detail || data?.error?.message || `HTTP ${response.status}`;
      throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
    }
    return data;
  }

  async function postJson(path, body = {}) {
    const response = await fetch(`${getBaseUrl()}${path}`, {
      method: 'POST',
      headers: { ...getHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const message = data?.detail || data?.error?.message || `HTTP ${response.status}`;
      throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
    }
    return data || {};
  }

  function renderStatus(message) {
    document.getElementById('welcomeScreen')?.classList.add('hidden');
    const container = document.getElementById('chatContainer');
    if (!container) return;
    container.innerHTML = `<div class="chat-history-main-status">${esc(message)}</div>`;
  }

  function renderMessages(thread) {
    const container = document.getElementById('chatContainer');
    if (!container) return;
    container.innerHTML = '';
    const messages = Array.isArray(thread?.messages) ? thread.messages : [];
    if (!messages.length) {
      renderStatus('This archived thread has no hydrated messages yet.');
      return;
    }
    const appendSteps = () => {
      const steps = Array.isArray(thread?.steps) ? thread.steps : [];
      if (!steps.length) return;
      const details = document.createElement('details');
      details.className = 'chat-history-steps';
      const summary = document.createElement('summary');
      summary.textContent = `${steps.length} step${steps.length === 1 ? '' : 's'}`;
      const list = document.createElement('div');
      list.className = 'chat-history-step-list';
      steps.forEach(step => {
        const item = document.createElement('div');
        item.className = 'chat-history-step-item';
        const label = document.createElement('strong');
        label.textContent = step.label || step.type || 'Step';
        item.appendChild(label);
        if (step.detail) item.appendChild(document.createTextNode(` · ${step.detail}`));
        list.appendChild(item);
      });
      details.appendChild(summary);
      details.appendChild(list);
      container.appendChild(details);
    };
    let insertedSteps = false;
    messages.forEach((message, index) => {
      const role = String(message.role || '').toLowerCase() === 'user' ? 'user' : 'assistant';
      window.NotionAI.Chat.Renderer.appendMessage(role, message.text || '', true, 'Remote history');
      if (!insertedSteps && (role === 'user' || index === messages.length - 1)) {
        appendSteps();
        insertedSteps = true;
      }
    });
    window.NotionAI.Utils.DOM.scrollToBottom();
  }

  function updateThread(threadId, updates) {
    const thread = state.threads.find(item => item.id === threadId);
    if (thread) Object.assign(thread, updates);
  }

  async function selectRemoteThread(thread) {
    if (window.NotionAI?.Core?.State?.get?.('isGenerating')) return;
    state.activeThreadId = thread.id;
    window.NotionAI.Core.State.set('currentChatId', `${REMOTE_ID_PREFIX}${thread.id}`);
    setInputArchivedMode(true);
    document.getElementById('welcomeScreen')?.classList.add('hidden');
    const header = document.getElementById('headerTitle');
    if (header) {
      header.textContent = thread.title || thread.id;
      header.classList.remove('hidden');
    }
    renderStatus(`Loading ${thread.title || thread.id}...`);
    if (window.innerWidth < 768) window.NotionAI.UI.Sidebar.close();
    window.NotionAI.Chat.Manager.renderChatList();

    try {
      const hydration = await postJson(`${THREADS_ENDPOINT}/${encodeURIComponent(thread.id)}/hydrate`);
      const count = Number(hydration?.thread?.message_count ?? thread.message_count ?? 0);
      updateThread(thread.id, { message_count: count, hydrated: Boolean(hydration?.thread?.hydrated || count > 0) });
      window.NotionAI.Chat.Manager.renderChatList();
      const hydratedThread = await fetchJson(`${THREADS_ENDPOINT}/${encodeURIComponent(thread.id)}`);
      updateThread(thread.id, {
        message_count: Number(hydratedThread?.message_count || 0),
        hydrated: Boolean(hydratedThread?.hydrated || Number(hydratedThread?.message_count || 0) > 0),
        first_message_preview: hydratedThread?.first_message_preview,
        last_message_preview: hydratedThread?.last_message_preview
      });
      renderMessages(hydratedThread);
    } catch (err) {
      renderStatus(err?.message || String(err));
    } finally {
      window.NotionAI.Chat.Manager.renderChatList();
    }
  }

  function renderRemoteChats(chatList) {
    if (!chatList) return;
    const searchValue = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
    const threads = searchValue
      ? state.threads.filter(thread => String(thread.title || thread.id).toLowerCase().includes(searchValue))
      : state.threads;

    if (!threads.length && !state.loading) return;

    const header = document.createElement('div');
    header.className = 'chat-section-header';
    header.textContent = 'REMOTE CHATS';
    chatList.appendChild(header);

    if (state.loading && !state.threads.length) {
      const loading = document.createElement('div');
      loading.className = 'chat-history-main-status';
      loading.style.margin = '8px 12px';
      loading.style.padding = '0';
      loading.textContent = 'Loading...';
      chatList.appendChild(loading);
      return;
    }

    let currentDay = '';
    threads.forEach(thread => {
      const label = dayLabel(thread);
      if (label !== currentDay) {
        currentDay = label;
        const day = document.createElement('div');
        day.className = 'chat-history-main-day';
        day.textContent = label;
        chatList.appendChild(day);
      }

      const item = document.createElement('div');
      item.className = `chat-item chat-history-main-item${thread.id === state.activeThreadId ? ' active' : ''}`;
      item.onclick = () => selectRemoteThread(thread);

      const text = document.createElement('div');
      text.className = 'chat-history-main-text';

      const title = document.createElement('span');
      title.className = 'chat-item-title';
      title.textContent = thread.title || thread.id;

      const meta = document.createElement('span');
      meta.className = 'chat-history-main-meta';
      const count = Number(thread.message_count || 0);
      meta.textContent = count > 0 ? `${count} messages` : 'metadata only';

      const dot = document.createElement('span');
      dot.className = `chat-history-main-dot${Boolean(thread.hydrated || count > 0) ? ' hydrated' : ''}`;
      dot.title = count > 0 ? 'Hydrated' : 'Metadata only';

      text.appendChild(title);
      text.appendChild(meta);
      item.appendChild(text);
      item.appendChild(dot);
      chatList.appendChild(item);
    });

    if (state.hasMore && !searchValue) {
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'chat-history-main-load';
      more.textContent = state.loading ? 'Loading...' : 'Load more remote chats';
      more.disabled = state.loading;
      more.addEventListener('click', event => {
        event.stopPropagation();
        refresh({ append: true });
      });
      chatList.appendChild(more);
    }
  }

  async function refresh(options = {}) {
    const append = Boolean(options.append);
    if (state.loading) return;
    state.loading = true;
    if (!append) {
      state.threads = [];
      state.offset = 0;
      state.hasMore = false;
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
    try {
      const data = await fetchJson(`${THREADS_ENDPOINT}?limit=${PAGE_SIZE}&offset=${state.offset}`);
      const page = Array.isArray(data?.threads) ? data.threads : [];
      state.threads = append ? state.threads.concat(page) : page;
      state.offset += page.length;
      state.hasMore = page.length === PAGE_SIZE;
    } catch (err) {
      console.warn('Unable to load remote chat history', err);
      if (!append) state.threads = [];
    } finally {
      state.loading = false;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    }
  }

  function patchChatManager() {
    const manager = window.NotionAI?.Chat?.Manager;
    if (!manager || state.patched) return false;
    const originalRender = manager.renderChatList.bind(manager);
    const originalStart = manager.startNewChat.bind(manager);
    const originalSelect = manager.selectChat.bind(manager);

    manager.renderChatList = function patchedRenderChatList(...args) {
      originalRender(...args);
      renderRemoteChats(document.getElementById('chatList'));
    };
    manager.startNewChat = function patchedStartNewChat(...args) {
      clearRemoteSelection();
      return originalStart(...args);
    };
    manager.selectChat = function patchedSelectChat(...args) {
      clearRemoteSelection();
      return originalSelect(...args);
    };

    state.patched = true;
    return true;
  }

  function init() {
    ensureStyles();
    if (!patchChatManager()) {
      setTimeout(init, 100);
      return;
    }
    refresh();
  }

  window.NotionAI = window.NotionAI || {};
  window.NotionAI.ChatHistoryMain = {
    refresh,
    clearRemoteSelection
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
