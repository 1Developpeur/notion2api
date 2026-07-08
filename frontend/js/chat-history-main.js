(() => {
  const THREADS_ENDPOINT = '/v1/chat-history/threads';
  const DELETE_ENDPOINT = '/v1/chat-history/threads/delete';
  const CLEANUP_SINGLE_ENDPOINT = '/v1/chat-history/threads/cleanup-single-message';
  const EXPORT_TWO_ENDPOINT = '/v1/chat-history/threads/export-two-message-responses';
  const CLEANUP_ERRORS_ENDPOINT = '/v1/chat-history/threads/cleanup-error-threads';
  const PAGE_SIZE = 50;
  const BULK_DELETE_SIZE = 200;
  const REMOTE_ID_PREFIX = 'remote-chat-history:';
  const HYDRATED_CACHE_KEY = 'notion_remote_chat_hydrated_cache_v1';
  const HYDRATED_CACHE_LIMIT = 1000;
  const state = {
    threads: [],
    selectedIds: new Set(),
    offset: 0,
    hasMore: true,
    loading: false,
    deleting: false,
    activeThreadId: null,
    patched: false,
    showDuplicatesOnly: false,
    providerFilter: '',
    exportFormat: 'csv',
    includeExportErrors: false,
    includeExportPrompt: true,
    includeExportResponse: true,
    deleteAfterExport: false,
    hydrating: false,
    hydrateAbortController: null,
    hydrateRunId: 0,
    hydrateStopped: false,
    sidebarMode: 'local',
    advancedOpen: false,
    resetSidebarScrollOnce: false
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

  function loadHydratedCache() {
    try {
      const parsed = JSON.parse(localStorage.getItem(HYDRATED_CACHE_KEY) || '{}');
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function saveHydratedCache(cache) {
    try {
      const entries = Object.entries(cache || {})
        .filter(([id, value]) => id && value && typeof value === 'object')
        .sort((a, b) => Number(b[1].cached_at || 0) - Number(a[1].cached_at || 0))
        .slice(0, HYDRATED_CACHE_LIMIT);
      localStorage.setItem(HYDRATED_CACHE_KEY, JSON.stringify(Object.fromEntries(entries)));
    } catch (err) {
      console.warn('Unable to save hydrated remote chat cache', err);
    }
  }

  function displayMessageCount(thread) {
    if (!thread || typeof thread !== 'object') return 0;
    if (thread.visible_message_count !== undefined && thread.visible_message_count !== null) {
      return Number(thread.visible_message_count || 0);
    }
    if (thread.message_count !== undefined && thread.message_count !== null) {
      return Number(thread.message_count || 0);
    }
    return 0;
  }

  function rawMessageCount(thread) {
    if (!thread || typeof thread !== 'object') return 0;
    if (thread.raw_message_count !== undefined && thread.raw_message_count !== null) {
      return Number(thread.raw_message_count || 0);
    }
    return Number(thread.message_count || 0);
  }

  function normalizeThreadCounts(thread) {
    if (!thread || typeof thread !== 'object') return thread;
    const visible = displayMessageCount(thread);
    const raw = rawMessageCount(thread);
    thread.visible_message_count = visible;
    thread.message_count = visible;
    thread.raw_message_count = raw || visible;
    return thread;
  }

  function isUnhydratedThread(thread) {
    return !thread?.hydrated && rawMessageCount(thread) === 0 && !thread?.hydrating;
  }

  function isSingleVisibleMessageThread(thread) {
    return displayMessageCount(thread) === 1;
  }

  function isErroredThread(thread) {
    return Number(thread?.error_message_count || 0) > 0 || Boolean(thread?.export_error_eligible);
  }

  function mergeHydratedCacheIntoThreads() {
    const cache = loadHydratedCache();
    if (!cache || !Object.keys(cache).length) return;
    for (const thread of state.threads) {
      const cached = cache[thread.id];
      if (!cached) {
        normalizeThreadCounts(thread);
        continue;
      }
      Object.assign(thread, cached, { id: thread.id, hydrating: false });
      normalizeThreadCounts(thread);
    }
  }

  function rememberHydratedThread(threadId, updates) {
    if (!threadId || !updates || typeof updates !== 'object') return;
    const cache = loadHydratedCache();
    const clean = { ...updates, cached_at: Date.now() };
    delete clean.hydrating;
    cache[threadId] = normalizeThreadCounts(clean);
    saveHydratedCache(cache);
  }

  function stopHydration() {
    state.hydrateStopped = true;
    if (state.hydrateAbortController) {
      try { state.hydrateAbortController.abort(); } catch (err) {}
    }
    state.hydrating = false;
    state.hydrateAbortController = null;
    for (const thread of state.threads) {
      if (thread.hydrating) thread.hydrating = false;
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function ensureStyles() {
    if (document.getElementById('chatHistoryMainStyles')) return;
    const style = document.createElement('style');
    style.id = 'chatHistoryMainStyles';
    style.textContent = `
      .chat-history-mode-switch{position:sticky;top:0;background:var(--bg-sidebar);z-index:20;display:flex;gap:6px;align-items:center;padding:8px 12px 6px;border-bottom:1px solid var(--border)}
      .chat-history-mode-switch button{flex:1;border:1px solid var(--border);border-radius:6px;background:transparent;color:var(--text-secondary);font-size:11px;padding:5px 6px}
      .chat-history-mode-switch button.active{background:var(--bg-hover);color:var(--text);border-color:var(--border-hover);font-weight:600}
      .chat-history-sort-row{position:sticky;top:40px;background:var(--bg-sidebar);z-index:19;display:flex;gap:6px;align-items:center;padding:6px 12px;border-bottom:1px solid var(--border)}
      .chat-history-sort-row select{flex:1;min-width:0;border:1px solid var(--border);background:var(--bg-sidebar);color:var(--text-secondary);border-radius:6px;font-size:11px;padding:4px 6px}
      .chat-history-sort-row button{border:1px solid var(--border);background:transparent;color:var(--text-secondary);border-radius:6px;font-size:11px;padding:4px 6px;white-space:nowrap}
      .chat-history-sort-row button:hover{background:var(--bg-hover);color:var(--text)}
      .chat-section-header{position:sticky;top:0;background:var(--bg-sidebar);z-index:11;padding:12px 16px 4px;line-height:1.2}
      .chat-history-main-day{font-size:10px;text-transform:uppercase;color:var(--text-tertiary);letter-spacing:.08em;padding:8px 16px 3px;display:flex;justify-content:space-between;align-items:center}
      .chat-history-main-day-hydrate{background:none;border:none;color:var(--accent,#7c3aed);font-size:9px;cursor:pointer;padding:0;text-transform:none;letter-spacing:normal}
      .chat-history-main-day-hydrate:hover:not(:disabled){text-decoration:underline}
      .chat-history-main-day-hydrate:disabled{opacity:0.5;cursor:not-allowed}
      .chat-history-main-toolbar{position:sticky;bottom:0;background:var(--bg-sidebar);z-index:70;display:flex;gap:7px;align-items:center;padding:9px 12px 10px;flex-wrap:wrap;border-top:1px solid var(--border);border-bottom:0;box-shadow:0 -10px 24px rgba(0,0,0,.28)}
      .chat-history-main-toolbar button{border:1px solid var(--border);background:transparent;color:var(--text-secondary);border-radius:4px;font-size:11px;padding:4px 6px;line-height:1.1}
      .chat-history-main-toolbar select{border:1px solid var(--border);background:var(--bg-sidebar);color:var(--text-secondary);border-radius:4px;font-size:11px;padding:3px 5px;max-width:160px}
      .chat-history-provider-bottom{display:flex;gap:6px;align-items:center;min-width:0;flex:1 1 180px}
      .chat-history-provider-bottom select{flex:1;min-width:0;border:1px solid var(--border);background:var(--bg-sidebar);color:var(--text-secondary);border-radius:6px;font-size:11px;padding:5px 6px}
      .chat-history-provider-bottom-label{font-size:10px;color:var(--text-tertiary);white-space:nowrap;text-transform:uppercase;letter-spacing:.04em}
      .chat-history-main-toolbar button:hover:not(:disabled){background:var(--bg-hover);color:var(--text)}
      .chat-history-main-toolbar button:disabled{opacity:.45;cursor:not-allowed}
      .chat-history-main-toolbar label{font-size:11px;color:var(--text-secondary);display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none}
      .chat-history-main-toolbar label input{margin:0;cursor:pointer}
      .chat-history-main-actions-wrap{position:relative;width:100%}
      .chat-history-main-actions-toggle{width:100%;border:1px solid var(--border);border-radius:6px;background:transparent;color:var(--text-secondary);font-size:11px;padding:6px 8px;text-align:left;display:flex;justify-content:space-between;align-items:center}
      .chat-history-main-actions-toggle:hover:not(:disabled){background:var(--bg-hover);color:var(--text)}
      .chat-history-main-actions-popover{position:absolute;left:0;right:0;bottom:calc(100% + 6px);z-index:80;border:1px solid var(--border);border-radius:8px;background:var(--card-bg,var(--bg-sidebar));box-shadow:0 -8px 24px rgba(0,0,0,.34);padding:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;max-height:min(60vh,420px);overflow:auto}
      .chat-history-main-actions-popover[hidden]{display:none}
      .chat-history-main-action-grid{display:flex;gap:6px;align-items:center;flex-wrap:wrap;width:100%}
      .chat-history-main-summary{width:100%;font-size:10px;color:var(--text-tertiary);padding:0 1px}
      .chat-history-main-delete{color:#a94442!important;border-color:#a94442!important}
      .chat-item.chat-history-main-item{align-items:flex-start;gap:8px;padding-top:7px;padding-bottom:7px}
      .chat-history-main-checkbox{margin-top:4px;flex-shrink:0}
      .chat-history-main-text{min-width:0;flex:1;display:flex;flex-direction:column;gap:2px}
      .chat-history-main-meta{font-size:10px;color:var(--text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .chat-history-main-dot{width:7px;height:7px;border-radius:999px;margin-top:6px;flex-shrink:0;background:var(--text-tertiary);opacity:.7}
      .chat-history-main-dot.hydrated{background:#2e7d32;opacity:1}
      .chat-history-main-dot.hydrating{background:#7c3aed;opacity:1;animation:chat-dot-pulse 1s infinite alternate}
      @keyframes chat-dot-pulse{0%{opacity:.3}100%{opacity:1}}
      .chat-history-main-empty{font-size:12px;color:var(--text-tertiary);padding:8px 12px;line-height:1.4}
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
    const value = thread.last_message_time || thread.updated_at || thread.last_edited_time || thread.created_time || '';
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

  function timeLabel(thread) {
    const ts = threadTimestamp(thread);
    if (!ts) return 'Unknown time';
    const date = new Date(ts);
    if (Number.isNaN(date.getTime())) return 'Unknown time';
    return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', hour12: true });
  }

  function providerKey(model, provider) {
    const actual = String(model || '[unknown]').trim() || '[unknown]';
    const source = String(provider || '[unknown]').trim() || '[unknown]';
    return `${actual}||${source}`;
  }

  function providerLabel(model, provider, displayModel) {
    const display = String(displayModel || '').trim();
    if (display) return display;
    const actual = String(model || '[unknown]').trim() || '[unknown]';
    const map = {
      'almond-croissant-low': 'Sonnet 4.6',
      'angel-cake-high': 'Sonnet 5',
      'avocado-froyo-medium': 'Opus 4.6',
      'apricot-sorbet-high': 'Opus 4.7',
      'ambrosia-tart-high': 'Opus 4.8',
      'anthropic-haiku-4.5': 'Haiku 4.5',
      'acai-budino': 'Fable 5',
      'oatmeal-cookie': 'GPT 5.2',
      'oval-kumquat-medium': 'GPT 5.4',
      'oregon-grape-medium': 'GPT 5.4 Mini',
      'otaheite-apple-medium': 'GPT 5.4 Nano',
      'opal-quince-medium': 'GPT 5.5',
      'gingerbread': 'Gemini 3 Flash',
      'galette-medium-thinking': 'Gemini 3.1 Pro',
      'vertex-gemini-3.5-flash': 'Gemini 3.5 Flash',
      'vertex-gemini-2.5-flash': 'Gemini 2.5 Flash',
      'xigua-mochi-medium': 'Grok 4.3',
      'xinomavro-cake': 'Grok Build 0.1',
      'fireworks-minimax-m2.5': 'MiniMax M2.5',
      'fireworks-kimi-k2.6': 'Kimi 2.6',
      'baseten-deepseek-v4-pro': 'DeepSeek V4 Pro'
    };
    return map[actual] || actual;
  }

  function threadProviderKeys(thread) {
    const stats = Array.isArray(thread?.model_stats) ? thread.model_stats : [];
    return stats.map(item => providerKey(item.actual_model, item.model_provider));
  }

  function providerOptions() {
    const seen = new Map();
    for (const thread of state.threads) {
      const stats = Array.isArray(thread?.model_stats) ? thread.model_stats : [];
      for (const item of stats) {
        const key = providerKey(item.actual_model, item.model_provider);
        if (!seen.has(key)) seen.set(key, providerLabel(item.actual_model, item.model_provider, item.display_model));
      }
    }
    return Array.from(seen.entries()).sort((a, b) => a[1].localeCompare(b[1]));
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

  async function postJson(path, body = {}, options = {}) {
    const response = await fetch(`${getBaseUrl()}${path}`, {
      method: 'POST',
      headers: { ...getHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: options.signal
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
      const modelLabel = role === 'assistant'
        ? (message.display_model || message.actual_model || 'Remote history')
        : null;
      window.NotionAI.Chat.Renderer.appendMessage(role, message.text || '', true, modelLabel, message.created_time || thread?.updated_at || null);
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

  function pruneSelectionToLoadedThreads() {
    const loadedIds = new Set(state.threads.map(thread => thread.id));
    for (const id of Array.from(state.selectedIds)) {
      if (!loadedIds.has(id)) state.selectedIds.delete(id);
    }
  }

  function getTitleCounts() {
    const counts = {};
    for (const thread of state.threads) {
      const title = String(thread.title || '').trim().toLowerCase();
      if (!title) continue;
      counts[title] = (counts[title] || 0) + 1;
    }
    return counts;
  }

  function matchesFilter(thread, titleCounts) {
    if (state.showDuplicatesOnly) {
      const title = String(thread.title || '').trim().toLowerCase();
      if (!title || (titleCounts[title] || 0) <= 1) {
        return false;
      }
    }
    if (state.providerFilter) {
      if (!threadProviderKeys(thread).includes(state.providerFilter)) {
        return false;
      }
    }
    const searchInput = document.getElementById('searchInput');
    const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
    if (!query) return true;
    const haystack = [
      thread?.id,
      thread?.title,
      thread?.first_message_preview,
      thread?.last_message_preview,
      thread?.created_time,
      thread?.last_edited_time,
      thread?.updated_at
    ].map(value => String(value || '').toLowerCase()).join('\n');
    return haystack.includes(query);
  }

  function getVisibleThreads() {
    const titleCounts = getTitleCounts();
    return state.threads.filter(t => matchesFilter(t, titleCounts));
  }

  function selectRemoteCheckbox(threadId, checked) {
    if (checked) state.selectedIds.add(threadId);
    else state.selectedIds.delete(threadId);
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  async function loadInitialRemoteThreads() {
    if (state.loading) return;
    state.loading = true;
    state.offset = 0;
    state.hasMore = true;
    state.threads = [];
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
    try {
      const data = await fetchJson(`${THREADS_ENDPOINT}?limit=${PAGE_SIZE}&offset=0`);
      const page = Array.isArray(data?.threads) ? data.threads : [];
      state.threads = page.filter(t => t?.id).map(normalizeThreadCounts);
      mergeHydratedCacheIntoThreads();
      state.offset = page.length;
      state.hasMore = page.length === PAGE_SIZE;
      pruneSelectionToLoadedThreads();
    } catch (err) {
      console.warn('Unable to load initial remote threads', err);
      renderStatus(`Unable to load remote chats: ${err?.message || String(err)}`);
    } finally {
      state.loading = false;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    }
  }

  async function loadNextBatch() {
    if (state.loading || !state.hasMore) return;
    state.loading = true;
    const chatList = document.getElementById('chatList');
    const savedScrollTop = chatList ? chatList.scrollTop : 0;
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
    try {
      const data = await fetchJson(`${THREADS_ENDPOINT}?limit=${PAGE_SIZE}&offset=${state.offset}`);
      const page = Array.isArray(data?.threads) ? data.threads : [];
      const seen = new Set(state.threads.map(t => t.id));
      const newThreads = [];
      for (const thread of page) {
        if (thread?.id && !seen.has(thread.id)) {
          newThreads.push(thread);
        }
      }
      state.threads = [...state.threads, ...newThreads.map(normalizeThreadCounts)];
      mergeHydratedCacheIntoThreads();
      state.offset += page.length;
      state.hasMore = page.length === PAGE_SIZE;
      pruneSelectionToLoadedThreads();
    } catch (err) {
      console.warn('Unable to load next batch of remote threads', err);
    } finally {
      state.loading = false;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
      if (chatList) {
        chatList.scrollTop = savedScrollTop;
      }
    }
  }

  function handleScroll(e) {
    const el = e.target;
    if (state.loading || !state.hasMore) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 50) {
      loadNextBatch();
    }
  }

  async function selectFilteredRemoteThreads() {
    if (state.loading || state.deleting) return;
    const visibleThreads = getVisibleThreads();
    for (const thread of visibleThreads) {
      if (thread?.id) state.selectedIds.add(thread.id);
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function selectOneMessageRemoteThreads() {
    if (state.loading || state.deleting) return;
    const targets = getVisibleThreads().filter(thread => displayMessageCount(thread) === 1);
    for (const thread of targets) {
      if (thread?.id) state.selectedIds.add(thread.id);
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function selectTwoMessageRemoteThreads() {
    if (state.loading || state.deleting) return;
    const targets = getVisibleThreads().filter(thread => displayMessageCount(thread) === 2);
    for (const thread of targets) {
      if (thread?.id) state.selectedIds.add(thread.id);
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function selectOneMessageRemoteThreads() {
    if (state.loading || state.deleting) return;
    const targets = getVisibleThreads().filter(thread => displayMessageCount(thread) === 1);
    for (const thread of targets) {
      if (thread?.id) state.selectedIds.add(thread.id);
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function selectTwoMessageRemoteThreads() {
    if (state.loading || state.deleting) return;
    const targets = getVisibleThreads().filter(thread => displayMessageCount(thread) === 2);
    for (const thread of targets) {
      if (thread?.id) state.selectedIds.add(thread.id);
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function clearSelectedRemoteThreads() {
    state.selectedIds.clear();
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function showConfirmDialog(message, onConfirm, options = {}) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay fade-in';
    overlay.style.zIndex = '999999';

    const content = document.createElement('div');
    content.className = 'modal-content modal-sm';

    const header = document.createElement('div');
    header.className = 'modal-header';
    const title = document.createElement('h3');
    title.textContent = options.title || 'Confirm Delete';
    header.appendChild(title);

    const body = document.createElement('div');
    body.className = 'modal-body';
    body.style.fontSize = '13px';
    body.style.lineHeight = '1.4';
    body.style.color = 'var(--text-secondary)';
    body.textContent = message;

    const footer = document.createElement('div');
    footer.className = 'modal-footer';

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn-secondary';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => {
      document.body.removeChild(overlay);
    });

    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.className = 'btn-primary';
    confirmBtn.style.backgroundColor = options.danger === false ? '' : '#a94442';
    confirmBtn.style.borderColor = options.danger === false ? '' : '#a94442';
    confirmBtn.style.color = '#ffffff';
    confirmBtn.textContent = options.confirmText || 'Delete';
    confirmBtn.addEventListener('click', () => {
      document.body.removeChild(overlay);
      onConfirm();
    });

    footer.appendChild(cancelBtn);
    footer.appendChild(confirmBtn);

    content.appendChild(header);
    content.appendChild(body);
    content.appendChild(footer);
    overlay.appendChild(content);

    document.body.appendChild(overlay);
  }

  function downloadTextFile(filename, content, contentType = 'text/csv') {
    const blob = new Blob([content || ''], { type: contentType });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename || 'notion-chat-export.csv';
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function cleanupSingleMessageThreads() {
    if (state.loading || state.deleting) return;
    const visible = getVisibleThreads().filter(thread => displayMessageCount(thread) === 1);
    if (!visible.length) {
      renderStatus('No loaded visible remote chats have exactly one message. Hydrate or adjust filters first.');
      return;
    }
    const ids = visible.map(thread => thread.id).filter(Boolean);
    showConfirmDialog(
      `Delete ${ids.length} visible remote chat(s) with exactly one message? Confirmed deletes will also be removed from the local archive.`,
      async () => {
        state.deleting = true;
        window.NotionAI?.Chat?.Manager?.renderChatList?.();
        try {
          const result = await postJson(CLEANUP_SINGLE_ENDPOINT, {
            thread_ids: ids,
            account_index: 0,
            remote: true,
            local: true
          });
          const successIds = Array.isArray(result?.results?.success) ? result.results.success : [];
          const successSet = new Set(successIds);
          state.threads = state.threads.filter(thread => !successSet.has(thread.id));
          for (const id of successIds) state.selectedIds.delete(id);
          if (state.activeThreadId && successSet.has(state.activeThreadId)) {
            clearRemoteSelection();
            renderStatus('Deleted selected one-message archived chat.');
          }
          console.info(`Deleted ${successIds.length} one-message remote chat(s).`, result);
        } catch (err) {
          console.warn('Unable to delete one-message remote chats', err);
          renderStatus(`One-message cleanup failed: ${err?.message || String(err)}`);
        } finally {
          state.deleting = false;
          window.NotionAI?.Chat?.Manager?.renderChatList?.();
        }
      }
    );
  }

  async function cleanupErroredThreads() {
    if (state.loading || state.deleting) return;
    const visible = getVisibleThreads().filter(thread => Number(thread.error_message_count || 0) > 0 && Number(thread.assistant_message_count || 0) === 0);
    if (!visible.length) {
      renderStatus('No visible errored remote chats found. Hydrate or adjust filters first.');
      return;
    }
    const ids = visible.map(thread => thread.id).filter(Boolean);
    showConfirmDialog(
      `Delete ${ids.length} visible errored remote chat(s)? This targets prompt+error threads and error-only threads, not successful assistant responses.`,
      async () => {
        state.deleting = true;
        window.NotionAI?.Chat?.Manager?.renderChatList?.();
        try {
          const result = await postJson(CLEANUP_ERRORS_ENDPOINT, {
            thread_ids: ids,
            account_index: 0,
            remote: true,
            local: true
          });
          const successIds = Array.isArray(result?.results?.success) ? result.results.success : [];
          const successSet = new Set(successIds);
          state.threads = state.threads.filter(thread => !successSet.has(thread.id));
          for (const id of successIds) state.selectedIds.delete(id);
          if (state.activeThreadId && successSet.has(state.activeThreadId)) {
            clearRemoteSelection();
            renderStatus('Deleted selected errored archived chat.');
          }
          console.info(`Deleted ${successIds.length} errored remote chat(s).`, result);
        } catch (err) {
          console.warn('Unable to delete errored remote chats', err);
          renderStatus(`Errored cleanup failed: ${err?.message || String(err)}`);
        } finally {
          state.deleting = false;
          window.NotionAI?.Chat?.Manager?.renderChatList?.();
        }
      }
    );
  }

  async function exportTwoMessageThreads() {
    if (state.loading || state.deleting) return;
    const visibleTwoMessage = getVisibleThreads().filter(thread => Boolean(thread.export_success_eligible || (state.includeExportErrors && thread.export_error_eligible)));
    const selectedTwoMessage = visibleTwoMessage.filter(thread => state.selectedIds.has(thread.id));
    const targets = selectedTwoMessage.length ? selectedTwoMessage : visibleTwoMessage;
    if (!targets.length) {
      const errorEligible = getVisibleThreads().filter(thread => Boolean(thread.export_error_eligible)).length;
      if (!state.includeExportErrors && errorEligible > 0) {
        renderStatus(`No successful two-message responses are visible. Enable Include errors to export ${errorEligible} user+error two-message record(s).`);
      } else {
        renderStatus('No loaded visible remote chats are exportable as two-message records. Hydrate or adjust filters first.');
      }
      return;
    }
    const ids = targets.map(thread => thread.id).filter(Boolean);
    const scope = selectedTwoMessage.length ? 'selected' : 'visible';
    const deleteNote = state.deleteAfterExport ? ' Then delete those exported threads from Notion history/local archive.' : ' Threads will be kept.';
    showConfirmDialog(
      `Export received messages from ${ids.length} ${scope} two-message chat(s).${deleteNote}`,
      async () => {
        state.deleting = true;
        window.NotionAI?.Chat?.Manager?.renderChatList?.();
        try {
          const format = state.exportFormat || 'csv';
          const result = await postJson(EXPORT_TWO_ENDPOINT, {
            thread_ids: ids,
            account_index: 0,
            remote: state.deleteAfterExport,
            local: state.deleteAfterExport,
            delete_after_export: state.deleteAfterExport,
            include_prompt: state.includeExportPrompt,
            include_response: state.includeExportResponse,
            include_errors: state.includeExportErrors,
            format
          });
          const exportedCount = Number(result?.exported || 0);
          const eligibleCount = Number(result?.eligible || 0);
          const content = result.content || result.csv || result.markdown || '';
          if (!exportedCount || !eligibleCount || !String(content).trim()) {
            renderStatus(`No exportable two-message chats found. Successful export requires exactly 1 user message and 1 assistant response. Enable Include errors to export 1 user + 1 error pairs. Eligible: ${eligibleCount}; exported: ${exportedCount}.`);
            return;
          }
          const defaultFilename = result.filename || `notion-two-message-responses.${format === 'md' ? 'md' : 'csv'}`;
          const filename = window.prompt('Export filename', defaultFilename);
          if (filename === null) {
            renderStatus('Export cancelled before file download. Refresh history before retrying.');
            return;
          }
          downloadTextFile(filename.trim() || defaultFilename, content, result.content_type || (format === 'md' ? 'text/markdown' : 'text/csv'));
          const successIds = Array.isArray(result?.results?.success) ? result.results.success : [];
          const successSet = new Set(successIds);
          state.threads = state.threads.filter(thread => !successSet.has(thread.id));
          for (const id of successIds) state.selectedIds.delete(id);
          if (state.activeThreadId && successSet.has(state.activeThreadId)) {
            clearRemoteSelection();
            renderStatus('Exported responses and deleted exported archived chats.');
          }
          console.info(`Exported ${Number(result?.exported || 0)} response(s), deleted ${successIds.length} thread(s).`, result);
        } catch (err) {
          console.warn('Unable to export/delete two-message remote chats', err);
          renderStatus(`Two-message export failed: ${err?.message || String(err)}`);
        } finally {
          state.deleting = false;
          window.NotionAI?.Chat?.Manager?.renderChatList?.();
        }
      },
      {
        title: state.deleteAfterExport ? 'Confirm Export + Delete' : 'Confirm Export',
        confirmText: state.deleteAfterExport ? 'Export + delete' : 'Export',
        danger: Boolean(state.deleteAfterExport)
      }
    );
  }

  async function hydrateSelectedRemoteThreads() {
    if (state.loading || state.deleting || state.hydrating) return;
    const selectedThreads = getVisibleThreads().filter(thread => state.selectedIds.has(thread.id));
    const targets = selectedThreads.filter(isUnhydratedThread);
    if (!selectedThreads.length) {
      renderStatus('Select one or more visible remote chats to hydrate.');
      return;
    }
    if (!targets.length) {
      renderStatus('All selected remote chats are already hydrated. Use Select unhydrated to target only metadata-only rows.');
      return;
    }
    await hydrateThreads(targets);
  }

  function selectUnhydratedRemoteThreads() {
    if (state.loading || state.deleting || state.hydrating) return;
    state.selectedIds.clear();
    for (const thread of getVisibleThreads().filter(isUnhydratedThread)) {
      if (thread?.id) state.selectedIds.add(thread.id);
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function isPingPongPreviewText(value) {
    const normalized = String(value || '')
      .trim()
      .toLowerCase()
      .replace(/^assistant\s*:\s*/, '')
      .replace(/^response\s*:\s*/, '')
      .replace(/[.!?。]+$/g, '')
      .trim();
    return normalized === 'ping' || normalized === 'pong';
  }

  function isRemotePingPongThread(thread) {
    const visible = displayMessageCount(thread);
    const raw = rawMessageCount(thread);
    const looksTwoMessage = visible === 2 || raw === 2 || Boolean(thread?.export_success_eligible || thread?.export_error_eligible);
    if (!looksTwoMessage) return false;
    return isPingPongPreviewText(thread?.last_message_preview)
      || isPingPongPreviewText(thread?.assistant_preview)
      || isPingPongPreviewText(thread?.response_preview);
  }

  function selectRemoteThreadsByPredicate(predicate) {
    state.selectedIds.clear();
    for (const thread of getVisibleThreads()) {
      if (thread?.id && predicate(thread)) {
        state.selectedIds.add(thread.id);
      }
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
    return state.selectedIds.size;
  }

  function selectRemoteThreadsByText(needles) {
    const lowered = Array.isArray(needles) ? needles.map(v => String(v || '').toLowerCase()) : [];
    state.selectedIds.clear();
    for (const thread of getVisibleThreads()) {
      const haystack = [thread?.title, thread?.first_message_preview, thread?.last_message_preview, thread?.id]
        .map(value => String(value || '').toLowerCase())
        .join('\n');
      if (lowered.some(needle => needle && haystack.includes(needle)) && thread?.id) {
        state.selectedIds.add(thread.id);
      }
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
    return state.selectedIds.size;
  }

  function deleteTitleGeneratorThreads() {
    const count = selectRemoteThreadsByText(['generate a title for this conversation', 'output only a thread title', 'thread title', 'title generator']);
    if (!count) {
      renderStatus('No visible title-generator remote chats found. Load more chats or adjust filters first.');
      return;
    }
    deleteSelectedRemoteThreads();
  }

  function deleteTestResponseThreads() {
    const count = selectRemoteThreadsByText(['test message response', 'test request']);
    if (!count) {
      renderStatus('No visible test-response remote chats found. Load more chats or adjust filters first.');
      return;
    }
    deleteSelectedRemoteThreads();
  }

  function backupRemoteChats() {
    const threads = Array.isArray(state.threads) ? state.threads : [];
    const visibleIds = new Set(getVisibleThreads().map(thread => thread.id).filter(Boolean));
    const selectedIds = Array.from(state.selectedIds || []);
    const exportedAt = new Date().toISOString();

    const csvEscape = value => {
      const text = value == null ? '' : String(value);
      return `"${text.replace(/"/g, '""')}"`;
    };

    const columns = [
      'exported_at',
      'id',
      'title',
      'visible',
      'selected',
      'hydrated',
      'visible_message_count',
      'raw_message_count',
      'user_message_count',
      'assistant_message_count',
      'error_message_count',
      'export_success_eligible',
      'export_error_eligible',
      'created_time',
      'last_message_time',
      'updated_at',
      'last_edited_time',
      'actual_model',
      'display_model',
      'model_provider',
      'first_message_preview',
      'last_message_preview',
      'raw_json'
    ];

    const rows = threads.map(thread => {
      const metadata = thread?.model_metadata && typeof thread.model_metadata === 'object' ? thread.model_metadata : {};
      const actualModel = thread.actual_model || thread.model || metadata.actual_model || metadata.notion_model_name || metadata.notion_step_model || '';
      const displayModel = thread.display_model || thread.model_display_name || metadata.display_model || actualModel || '';
      const provider = thread.model_provider || metadata.model_provider || '';
      const row = {
        exported_at: exportedAt,
        id: thread?.id || '',
        title: thread?.title || '',
        visible: visibleIds.has(thread?.id),
        selected: selectedIds.includes(thread?.id),
        hydrated: Boolean(thread?.hydrated || rawMessageCount(thread) > 0),
        visible_message_count: displayMessageCount(thread),
        raw_message_count: rawMessageCount(thread),
        user_message_count: Number(thread?.user_message_count || 0),
        assistant_message_count: Number(thread?.assistant_message_count || 0),
        error_message_count: Number(thread?.error_message_count || 0),
        export_success_eligible: Boolean(thread?.export_success_eligible),
        export_error_eligible: Boolean(thread?.export_error_eligible),
        created_time: thread?.created_time || '',
        last_message_time: thread?.last_message_time || '',
        updated_at: thread?.updated_at || '',
        last_edited_time: thread?.last_edited_time || '',
        actual_model: actualModel,
        display_model: displayModel,
        model_provider: provider,
        first_message_preview: thread?.first_message_preview || '',
        last_message_preview: thread?.last_message_preview || '',
        raw_json: JSON.stringify(thread || {})
      };
      return columns.map(column => csvEscape(row[column])).join(',');
    });

    const csv = [columns.map(csvEscape).join(','), ...rows].join('\r\n') + '\r\n';
    const safeStamp = exportedAt.replace(/[:.]/g, '-');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `notion-ai-remote-chat-backup-${safeStamp}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    renderStatus(`Backed up ${threads.length} loaded remote chat(s) to CSV.`);
    return { exportedAt, loadedCount: threads.length, visibleCount: visibleIds.size, selectedCount: selectedIds.length };
  }


  function deletePingPongRemoteThreads() {
    const count = selectRemoteThreadsByPredicate(isRemotePingPongThread);
    if (!count) {
      renderStatus('No visible hydrated two-message ping/pong remote chats found. Hydrate or load more chats first.');
      return;
    }
    deleteSelectedRemoteThreads();
  }

  async function deleteSelectedRemoteThreads() {
    const ids = Array.from(state.selectedIds);
    if (!ids.length || state.deleting) return;

    showConfirmDialog(
      `Delete ${ids.length} selected remote chat(s)? Confirmed deletes will also be removed from the local archive.`,
      async () => {
        state.deleting = true;
        window.NotionAI?.Chat?.Manager?.renderChatList?.();
        const successIds = [];
        const failed = [];
        try {
          for (let index = 0; index < ids.length; index += BULK_DELETE_SIZE) {
            const batch = ids.slice(index, index + BULK_DELETE_SIZE);
            const result = await postJson(DELETE_ENDPOINT, {
              thread_ids: batch,
              account_index: 0,
              remote: true,
              local: true
            });
            if (Array.isArray(result?.results?.success)) successIds.push(...result.results.success);
            if (Array.isArray(result?.results?.failed)) failed.push(...result.results.failed);
          }

          const successSet = new Set(successIds);
          state.threads = state.threads.filter(thread => !successSet.has(thread.id));
          state.selectedIds.clear();
          for (const failedItem of failed) {
            if (failedItem?.thread_id) state.selectedIds.add(failedItem.thread_id);
          }
          if (state.activeThreadId && successSet.has(state.activeThreadId)) {
            clearRemoteSelection();
            renderStatus('Deleted selected archived chat.');
          }
          const suffix = failed.length ? ` ${failed.length} failed and remain selected.` : '';
          console.info(`Deleted ${successIds.length} remote chat(s).${suffix}`, { successIds, failed });
        } catch (err) {
          console.warn('Unable to delete selected remote chats', err);
          renderStatus(`Bulk delete failed: ${err?.message || String(err)}`);
        } finally {
          state.deleting = false;
          window.NotionAI?.Chat?.Manager?.renderChatList?.();
        }
      }
    );
  }

  async function hydrateThreads(threadsToHydrate) {
    if (state.hydrating) return;
    const controller = new AbortController();
    const runId = Date.now();
    state.hydrating = true;
    state.hydrateStopped = false;
    state.hydrateAbortController = controller;
    state.hydrateRunId = runId;
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
    try {
      for (const thread of threadsToHydrate) {
        if (state.hydrateStopped || controller.signal.aborted || state.hydrateRunId !== runId) break;
        if (thread.hydrated || rawMessageCount(thread) > 0) continue;
        updateThread(thread.id, { hydrating: true });
        window.NotionAI?.Chat?.Manager?.renderChatList?.();
        try {
          const hydration = await postJson(`${THREADS_ENDPOINT}/${encodeURIComponent(thread.id)}/hydrate`, {}, { signal: controller.signal });
          if (controller.signal.aborted || state.hydrateRunId !== runId) break;
          const hydratedThread = hydration?.thread || {};
          const visibleCount = Number(hydratedThread.visible_message_count ?? hydratedThread.message_count ?? thread.message_count ?? 0);
          const rawCount = Number(hydratedThread.raw_message_count ?? thread.raw_message_count ?? visibleCount);
          const updates = normalizeThreadCounts({
            message_count: visibleCount,
            visible_message_count: visibleCount,
            raw_message_count: rawCount,
            hydrated: Boolean(hydratedThread.hydrated || rawCount > 0 || visibleCount > 0),
            hydrating: false
          });
          updateThread(thread.id, updates);
          rememberHydratedThread(thread.id, updates);
        } catch (err) {
          if (err?.name === 'AbortError') break;
          console.warn(`Failed to hydrate thread ${thread.id}`, err);
          updateThread(thread.id, { hydrating: false });
        }
      }
    } finally {
      if (state.hydrateRunId === runId) {
        state.hydrating = false;
        state.hydrateAbortController = null;
        state.hydrateStopped = false;
        for (const thread of state.threads) {
          if (thread.hydrating) thread.hydrating = false;
        }
      }
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    }
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
      const count = Number(hydration?.thread?.visible_message_count ?? hydration?.thread?.message_count ?? thread.message_count ?? 0);
      const rawCount = Number(hydration?.thread?.raw_message_count ?? thread.raw_message_count ?? count);
      const hydratedUpdate = normalizeThreadCounts({
        message_count: count,
        visible_message_count: count,
        raw_message_count: rawCount,
        hydrated: Boolean(hydration?.thread?.hydrated || rawCount > 0 || count > 0)
      });
      updateThread(thread.id, hydratedUpdate);
      rememberHydratedThread(thread.id, hydratedUpdate);
      window.NotionAI.Chat.Manager.renderChatList();
      const hydratedThread = await fetchJson(`${THREADS_ENDPOINT}/${encodeURIComponent(thread.id)}`);
      const visibleCount = Number(hydratedThread?.visible_message_count ?? hydratedThread?.message_count ?? 0);
      const detailUpdate = normalizeThreadCounts({
        message_count: visibleCount,
        visible_message_count: visibleCount,
        raw_message_count: Number(hydratedThread?.raw_message_count ?? visibleCount),
        hydrated: Boolean(hydratedThread?.hydrated || Number(hydratedThread?.raw_message_count ?? visibleCount) > 0),
        first_message_preview: hydratedThread?.first_message_preview,
        last_message_preview: hydratedThread?.last_message_preview
      });
      updateThread(thread.id, detailUpdate);
      rememberHydratedThread(thread.id, detailUpdate);
      renderMessages(hydratedThread);
    } catch (err) {
      renderStatus(err?.message || String(err));
    } finally {
      window.NotionAI.Chat.Manager.renderChatList();
    }
  }

  async function reloadSelectedRemoteThread() {
    if (!state.activeThreadId) return;
    const thread = state.threads.find(item => item.id === state.activeThreadId);
    if (!thread) return;
    await selectRemoteThread(thread);
  }
  
  function handleRemoteChatClick(e, thread) {
    if (window.NotionAI?.Core?.State?.get?.('isGenerating')) return;

    const threads = getVisibleThreads();

    if (e.ctrlKey || e.metaKey) {
      if (state.selectedIds.has(thread.id)) {
        state.selectedIds.delete(thread.id);
        if (state.activeThreadId === thread.id) {
          const loadedArray = Array.from(state.selectedIds);
          const nextActiveId = loadedArray[loadedArray.length - 1] || null;
          if (nextActiveId) {
            const nextActiveThread = state.threads.find(t => t.id === nextActiveId);
            if (nextActiveThread) selectRemoteThread(nextActiveThread);
          } else {
            clearRemoteSelection();
          }
        } else {
          window.NotionAI?.Chat?.Manager?.renderChatList?.();
        }
      } else {
        state.selectedIds.add(thread.id);
        selectRemoteThread(thread);
      }
    } else if (e.shiftKey) {
      const endIdx = threads.findIndex(t => t.id === thread.id);
      let startIdx = threads.findIndex(t => t.id === state.activeThreadId);
      if (startIdx === -1) startIdx = 0;

      const minIdx = Math.min(startIdx, endIdx);
      const maxIdx = Math.max(startIdx, endIdx);
      for (let i = minIdx; i <= maxIdx; i++) {
        state.selectedIds.add(threads[i].id);
      }
      selectRemoteThread(thread);
    } else {
      state.selectedIds.clear();
      state.selectedIds.add(thread.id);
      selectRemoteThread(thread);
    }
  }

  function setSidebarMode(mode) {
    const next = mode === 'remote' ? 'remote' : 'local';
    if (state.sidebarMode === next) return;
    state.sidebarMode = next;
    state.advancedOpen = false;
    state.resetSidebarScrollOnce = true;
    localStorage.setItem('notion_sidebar_history_mode', next);
    if (next === 'local') clearRemoteSelection();
    window.NotionAI?.Chat?.Manager?.renderChatList?.({ forceHistoryMode: next });
  }

  function renderHistoryModeControls(chatList) {
    if (!chatList) return;
    const switcher = document.createElement('div');
    switcher.className = 'chat-history-mode-switch';

    const localBtn = document.createElement('button');
    localBtn.type = 'button';
    localBtn.textContent = 'Local';
    localBtn.className = state.sidebarMode === 'local' ? 'active' : '';
    localBtn.addEventListener('click', event => {
      event.stopPropagation();
      setSidebarMode('local');
    });

    const remoteBtn = document.createElement('button');
    remoteBtn.type = 'button';
    remoteBtn.textContent = 'Remote';
    remoteBtn.className = state.sidebarMode === 'remote' ? 'active' : '';
    remoteBtn.addEventListener('click', event => {
      event.stopPropagation();
      setSidebarMode('remote');
    });

    switcher.appendChild(localBtn);
    switcher.appendChild(remoteBtn);
    chatList.insertBefore(switcher, chatList.firstChild);

    if (state.sidebarMode === 'local') {
      const sortRow = document.createElement('div');
      sortRow.className = 'chat-history-sort-row';
      const sortSelect = document.createElement('select');
      sortSelect.title = 'Sort local chat history.';
      const options = [
        ['date_desc', 'Sort: newest first'],
        ['date_asc', 'Sort: oldest first'],
        ['messages_desc', 'Sort: most messages'],
        ['messages_asc', 'Sort: fewest messages']
      ];
      const current = localStorage.getItem('notion_local_chat_sort') || 'date_desc';
      for (const [value, label] of options) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        option.selected = current === value;
        sortSelect.appendChild(option);
      }
      sortSelect.addEventListener('change', event => {
        localStorage.setItem('notion_local_chat_sort', String(event.target.value || 'date_desc'));
        window.NotionAI?.Chat?.Manager?.renderChatList?.();
      });
      const localChats = window.NotionAI?.Core?.State?.get?.('chats') || [];
      const backupLocalChatsBtn = document.createElement('button');
      backupLocalChatsBtn.type = 'button';
      backupLocalChatsBtn.textContent = `Backup chats (${localChats.length})`;
      backupLocalChatsBtn.title = 'Download a JSON backup of all browser-local chats.';
      backupLocalChatsBtn.addEventListener('click', event => {
        event.stopPropagation();
        const summary = window.NotionAI?.Chat?.Storage?.backupChats?.();
        if (summary) renderStatus(`Backed up ${summary.chatCount} local chat(s), ${summary.messageCount} message(s).`);
      });


      sortRow.appendChild(sortSelect);
      sortRow.appendChild(backupLocalChatsBtn);
      chatList.insertBefore(sortRow, switcher.nextSibling);
    }
  }

  function renderRemoteChats(chatList) {
    if (!chatList) return;
    const threads = getVisibleThreads();

    const searchInput = document.getElementById('searchInput');
    const isSearchActive = Boolean((searchInput ? searchInput.value : '').trim());

    if (!state.threads.length && !state.loading && !isSearchActive && !state.showDuplicatesOnly) return;

    const header = document.createElement('div');
    header.className = 'chat-section-header';
    header.textContent = 'REMOTE CHATS';
    chatList.appendChild(header);

    const toolbar = document.createElement('div');
    toolbar.className = 'chat-history-main-toolbar';

    const dupLabel = document.createElement('label');
    const dupCheckbox = document.createElement('input');
    dupCheckbox.type = 'checkbox';
    dupCheckbox.checked = state.showDuplicatesOnly;
    dupCheckbox.addEventListener('change', (e) => {
      state.showDuplicatesOnly = e.target.checked;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });
    dupLabel.appendChild(dupCheckbox);
    dupLabel.appendChild(document.createTextNode('Duplicates'));

    const selectedCount = state.selectedIds.size;
    const visibleCount = threads.length;
    const unhydratedCount = threads.filter(isUnhydratedThread).length;
    const selectedUnhydratedCount = threads.filter(thread => state.selectedIds.has(thread.id) && isUnhydratedThread(thread)).length;
    const hydratedCount = threads.filter(thread => Boolean(thread.hydrated || rawMessageCount(thread) > 0)).length;
    const oneMessageCount = threads.filter(isSingleVisibleMessageThread).length;
    const erroredThreadCount = threads.filter(thread => isErroredThread(thread) && Number(thread.assistant_message_count || 0) === 0).length;
    const exportSuccessCount = threads.filter(thread => Boolean(thread.export_success_eligible)).length;
    const exportErrorCount = threads.filter(thread => Boolean(thread.export_error_eligible)).length;
    const pingPongRemoteCount = threads.filter(isRemotePingPongThread).length;
    const remoteBackupCount = state.threads.length;
    const exportTotalAvailable = exportSuccessCount + exportErrorCount;
    const twoMessageCount = state.includeExportErrors ? exportTotalAvailable : exportSuccessCount;

    const providerSelect = document.createElement('select');
    providerSelect.title = 'Filter remote chats by actual response model/provider.';
    const allOption = document.createElement('option');
    allOption.value = '';
    allOption.textContent = 'All providers';
    providerSelect.appendChild(allOption);
    providerOptions().forEach(([key, label]) => {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = label;
      option.selected = state.providerFilter === key;
      providerSelect.appendChild(option);
    });
    providerSelect.value = state.providerFilter;
    providerSelect.addEventListener('change', event => {
      state.providerFilter = String(event.target.value || '');
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });

    const selectBtn = document.createElement('button');
    selectBtn.type = 'button';
    selectBtn.textContent = 'Select filtered';
    selectBtn.disabled = state.deleting || state.loading || !threads.length;
    selectBtn.title = 'Select every currently matching conversation.';
    selectBtn.addEventListener('click', event => {
      event.stopPropagation();
      selectFilteredRemoteThreads();
    });

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.textContent = 'Clear';
    clearBtn.disabled = state.deleting || (!selectedCount && !isSearchActive && !state.showDuplicatesOnly && !state.providerFilter);
    clearBtn.addEventListener('click', event => {
      event.stopPropagation();
      state.showDuplicatesOnly = false;
      state.providerFilter = '';
      if (searchInput) {
        searchInput.value = '';
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
      clearSelectedRemoteThreads();
    });

    const selectUnhydratedBtn = document.createElement('button');
    selectUnhydratedBtn.type = 'button';
    selectUnhydratedBtn.textContent = `Select unhydrated (${unhydratedCount})`;
    selectUnhydratedBtn.disabled = state.deleting || state.loading || state.hydrating || unhydratedCount === 0;
    selectUnhydratedBtn.title = 'Clear selection and select only visible metadata-only rows.';
    selectUnhydratedBtn.addEventListener('click', event => {
      event.stopPropagation();
      selectUnhydratedRemoteThreads();
    });

    const hydrateSelectedBtn = document.createElement('button');
    hydrateSelectedBtn.type = 'button';
    hydrateSelectedBtn.textContent = selectedUnhydratedCount ? `Hydrate unhydrated (${selectedUnhydratedCount})` : 'Hydrate unhydrated';
    hydrateSelectedBtn.disabled = state.deleting || state.loading || state.hydrating || selectedUnhydratedCount === 0;
    hydrateSelectedBtn.title = 'Hydrate only selected remote chats that are not already hydrated.';
    hydrateSelectedBtn.addEventListener('click', event => {
      event.stopPropagation();
      hydrateSelectedRemoteThreads();
    });

    const stopHydrateBtn = document.createElement('button');
    stopHydrateBtn.type = 'button';
    stopHydrateBtn.textContent = 'Stop hydration';
    stopHydrateBtn.disabled = !state.hydrating;
    stopHydrateBtn.title = 'Cancel the current frontend hydration loop. Any already-started server request may finish.';
    stopHydrateBtn.addEventListener('click', event => {
      event.stopPropagation();
      stopHydration();
    });

    const cleanupOneBtn = document.createElement('button');
    cleanupOneBtn.type = 'button';
    cleanupOneBtn.textContent = `Delete 1-msg (${oneMessageCount})`;
    cleanupOneBtn.disabled = state.deleting || state.loading || oneMessageCount === 0;
    cleanupOneBtn.title = 'Delete visible filtered remote chats that contain exactly one hydrated message.';
    cleanupOneBtn.addEventListener('click', event => {
      event.stopPropagation();
      cleanupSingleMessageThreads();
    });

    const cleanupErrorsBtn = document.createElement('button');
    cleanupErrorsBtn.type = 'button';
    cleanupErrorsBtn.textContent = `Delete errors (${erroredThreadCount})`;
    cleanupErrorsBtn.disabled = state.deleting || state.loading || erroredThreadCount === 0;
    cleanupErrorsBtn.title = 'Delete visible errored prompt threads: user+error or error-only, with no successful assistant response.';
    cleanupErrorsBtn.addEventListener('click', event => {
      event.stopPropagation();
      cleanupErroredThreads();
    });

    const exportFormatSelect = document.createElement('select');
    exportFormatSelect.title = 'Choose export format for two-message response export.';
    const csvOption = document.createElement('option');
    csvOption.value = 'csv';
    csvOption.textContent = 'Spreadsheet CSV';
    csvOption.selected = state.exportFormat !== 'md';
    exportFormatSelect.appendChild(csvOption);
    const mdOption = document.createElement('option');
    mdOption.value = 'md';
    mdOption.textContent = 'Markdown';
    mdOption.selected = state.exportFormat === 'md';
    exportFormatSelect.appendChild(mdOption);
    exportFormatSelect.addEventListener('change', event => {
      state.exportFormat = String(event.target.value || 'csv');
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });

    const includePromptLabel = document.createElement('label');
    includePromptLabel.title = 'Include the user prompt/sent message in the export.';
    const includePromptCheckbox = document.createElement('input');
    includePromptCheckbox.type = 'checkbox';
    includePromptCheckbox.checked = Boolean(state.includeExportPrompt);
    includePromptCheckbox.addEventListener('change', event => {
      state.includeExportPrompt = Boolean(event.target.checked);
      if (!state.includeExportPrompt && !state.includeExportResponse) state.includeExportResponse = true;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });
    includePromptLabel.appendChild(includePromptCheckbox);
    includePromptLabel.appendChild(document.createTextNode('Prompt'));

    const includeResponseLabel = document.createElement('label');
    includeResponseLabel.title = 'Include the response/error message in the export.';
    const includeResponseCheckbox = document.createElement('input');
    includeResponseCheckbox.type = 'checkbox';
    includeResponseCheckbox.checked = Boolean(state.includeExportResponse);
    includeResponseCheckbox.addEventListener('change', event => {
      state.includeExportResponse = Boolean(event.target.checked);
      if (!state.includeExportPrompt && !state.includeExportResponse) state.includeExportPrompt = true;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });
    includeResponseLabel.appendChild(includeResponseCheckbox);
    includeResponseLabel.appendChild(document.createTextNode('Response'));

    const includeErrorsLabel = document.createElement('label');
    includeErrorsLabel.title = 'Include two-message user + error threads such as failed provider responses.';
    const includeErrorsCheckbox = document.createElement('input');
    includeErrorsCheckbox.type = 'checkbox';
    includeErrorsCheckbox.checked = Boolean(state.includeExportErrors);
    includeErrorsCheckbox.addEventListener('change', event => {
      state.includeExportErrors = Boolean(event.target.checked);
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });
    includeErrorsLabel.appendChild(includeErrorsCheckbox);
    includeErrorsLabel.appendChild(document.createTextNode('Include errors'));

    const deleteAfterExportLabel = document.createElement('label');
    deleteAfterExportLabel.title = 'When checked, delete exported two-message chats after the export file is generated.';
    const deleteAfterExportCheckbox = document.createElement('input');
    deleteAfterExportCheckbox.type = 'checkbox';
    deleteAfterExportCheckbox.checked = Boolean(state.deleteAfterExport);
    deleteAfterExportCheckbox.addEventListener('change', event => {
      state.deleteAfterExport = Boolean(event.target.checked);
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });
    deleteAfterExportLabel.appendChild(deleteAfterExportCheckbox);
    deleteAfterExportLabel.appendChild(document.createTextNode('Delete after export'));

    const exportTwoBtn = document.createElement('button');
    exportTwoBtn.type = 'button';
    const errorHint = exportErrorCount ? ` + ${exportErrorCount} errors` : '';
    const exportLabelCount = state.includeExportErrors ? String(twoMessageCount) : `${exportSuccessCount}${errorHint}`;
    exportTwoBtn.textContent = state.deleteAfterExport ? `Export + delete 2-msg (${exportLabelCount})` : `Export 2-msg (${exportLabelCount})`;
    exportTwoBtn.disabled = state.deleting || state.loading || exportTotalAvailable === 0;
    exportTwoBtn.title = state.includeExportErrors
      ? 'Export successful and error two-message records according to current filters.'
      : 'Export successful two-message responses. Enable Include errors to export failed/error two-message records.';
    exportTwoBtn.addEventListener('click', event => {
      event.stopPropagation();
      exportTwoMessageThreads();
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'chat-history-main-delete';
    deleteBtn.textContent = selectedCount ? `Delete (${selectedCount})` : 'Delete';
    deleteBtn.disabled = state.deleting || !selectedCount;
    deleteBtn.addEventListener('click', event => {
      event.stopPropagation();
      deleteSelectedRemoteThreads();
    });

    const titleGenBtn = document.createElement('button');
    titleGenBtn.type = 'button';
    titleGenBtn.textContent = 'Delete title-gen';
    titleGenBtn.disabled = state.deleting || state.loading;
    titleGenBtn.title = 'Delete visible loaded chats that look like title-generator prompts.';
    titleGenBtn.addEventListener('click', event => {
      event.stopPropagation();
      deleteTitleGeneratorThreads();
    });

    const testResponseBtn = document.createElement('button');
    testResponseBtn.type = 'button';
    testResponseBtn.textContent = 'Delete test threads';
    testResponseBtn.disabled = state.deleting || state.loading;
    testResponseBtn.title = 'Delete visible loaded chats that look like test request / test response threads.';
    testResponseBtn.addEventListener('click', event => {
      event.stopPropagation();
      deleteTestResponseThreads();
    });

    const deletePingPongRemoteBtn = document.createElement('button');
    deletePingPongRemoteBtn.type = 'button';
    deletePingPongRemoteBtn.textContent = `Delete ping/pong (${pingPongRemoteCount})`;
    deletePingPongRemoteBtn.disabled = state.deleting || state.loading || pingPongRemoteCount === 0;
    deletePingPongRemoteBtn.title = 'Delete visible hydrated two-message remote chats whose assistant response is only ping or pong.';
    deletePingPongRemoteBtn.addEventListener('click', event => {
      event.stopPropagation();
      deletePingPongRemoteThreads();
    });

    const backupRemoteBtn = document.createElement('button');
    backupRemoteBtn.type = 'button';
    backupRemoteBtn.textContent = `Backup remote CSV (${remoteBackupCount})`;
    backupRemoteBtn.disabled = state.loading || remoteBackupCount === 0;
    backupRemoteBtn.title = 'Download a CSV backup of all remote chat rows currently loaded in the browser.';
    backupRemoteBtn.addEventListener('click', event => {
      event.stopPropagation();
      backupRemoteChats();
    });

    const actionsPanel = document.createElement('div');
    actionsPanel.className = 'chat-history-main-actions-wrap';

    const actionsToggle = document.createElement('button');
    actionsToggle.type = 'button';
    actionsToggle.className = 'chat-history-main-actions-toggle';
    actionsToggle.innerHTML = `<span>Advanced actions (${selectedCount} selected)</span><span>${state.advancedOpen ? '▲' : '▼'}</span>`;
    actionsToggle.addEventListener('click', event => {
      event.stopPropagation();
      state.advancedOpen = !state.advancedOpen;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    });

    const actionsGrid = document.createElement('div');
    actionsGrid.className = 'chat-history-main-actions-popover';
    if (!state.advancedOpen) actionsGrid.hidden = true;

    actionsPanel.appendChild(actionsToggle);
    actionsPanel.appendChild(actionsGrid);

    const summary = document.createElement('div');
    summary.className = 'chat-history-main-summary';
    const isFiltered = Boolean(isSearchActive || state.showDuplicatesOnly || state.providerFilter);
    const summaryParts = [`${visibleCount} ${isFiltered ? 'matched' : 'chats'}`];
    if (selectedCount) summaryParts.push(`${selectedCount} selected`);
    if (state.loading) summaryParts.push('loading');
    if (state.hydrating) summaryParts.push('hydrating');
    summary.textContent = summaryParts.join(' · ');
    const providerText = state.providerFilter ? `provider ${providerSelect.options[providerSelect.selectedIndex]?.text || 'filtered'}; ` : '';
    summary.title = `${providerText}${state.threads.length} loaded; ${hydratedCount} hydrated; ${unhydratedCount} unhydrated; ${oneMessageCount} 1-msg; ${erroredThreadCount} raw-errors; ${twoMessageCount} exportable`;

    const providerBottom = document.createElement('div');
    providerBottom.className = 'chat-history-provider-bottom';
    const providerBottomLabel = document.createElement('span');
    providerBottomLabel.className = 'chat-history-provider-bottom-label';
    providerBottomLabel.textContent = 'Provider';
    providerBottom.appendChild(providerBottomLabel);
    providerBottom.appendChild(providerSelect);

    toolbar.appendChild(dupLabel);
    toolbar.appendChild(actionsPanel);
    toolbar.appendChild(providerBottom);
    actionsGrid.appendChild(selectBtn);
    actionsGrid.appendChild(clearBtn);
    actionsGrid.appendChild(selectUnhydratedBtn);
    actionsGrid.appendChild(hydrateSelectedBtn);
    actionsGrid.appendChild(stopHydrateBtn);
    actionsGrid.appendChild(cleanupOneBtn);
    actionsGrid.appendChild(cleanupErrorsBtn);
    actionsGrid.appendChild(backupRemoteBtn);
    actionsGrid.appendChild(titleGenBtn);
    actionsGrid.appendChild(testResponseBtn);
    actionsGrid.appendChild(deletePingPongRemoteBtn);
    actionsGrid.appendChild(deleteBtn);
    actionsGrid.appendChild(exportFormatSelect);
    actionsGrid.appendChild(includePromptLabel);
    actionsGrid.appendChild(includeResponseLabel);
    actionsGrid.appendChild(includeErrorsLabel);
    actionsGrid.appendChild(deleteAfterExportLabel);
    actionsGrid.appendChild(exportTwoBtn);
    toolbar.appendChild(summary);

    if (state.loading && !state.threads.length) {
      const loading = document.createElement('div');
      loading.className = 'chat-history-main-status';
      loading.style.margin = '8px 12px';
      loading.style.padding = '0';
      loading.textContent = 'Loading remote chats...';
      chatList.appendChild(loading);
      chatList.appendChild(toolbar);
      return;
    }

    if (!threads.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-history-main-empty';
      empty.textContent = (isSearchActive || state.showDuplicatesOnly)
        ? 'No remote chats match this filter.'
        : 'No remote chats are loaded.';
      chatList.appendChild(empty);
    }

    let currentDay = '';
    threads.forEach(thread => {
      const label = dayLabel(thread);
      if (label !== currentDay) {
        currentDay = label;
        const dayThreads = threads.filter(t => dayLabel(t) === label);
        const unhydratedDayThreads = dayThreads.filter(t => !t.hydrated && rawMessageCount(t) === 0);

        const day = document.createElement('div');
        day.className = 'chat-history-main-day';
        day.style.display = 'flex';
        day.style.justifyContent = 'space-between';
        day.style.alignItems = 'center';

        const labelSpan = document.createElement('span');
        labelSpan.textContent = label;
        day.appendChild(labelSpan);

        if (unhydratedDayThreads.length > 0) {
          const hydrateAllBtn = document.createElement('button');
          hydrateAllBtn.type = 'button';
          hydrateAllBtn.className = 'chat-history-main-day-hydrate';
          hydrateAllBtn.textContent = `Hydrate all (${unhydratedDayThreads.length})`;
          if (state.hydrating) {
            hydrateAllBtn.disabled = true;
            hydrateAllBtn.style.opacity = '0.5';
            hydrateAllBtn.style.cursor = 'not-allowed';
          }
          hydrateAllBtn.onclick = (e) => {
            e.stopPropagation();
            hydrateThreads(unhydratedDayThreads);
          };
          day.appendChild(hydrateAllBtn);
        }

        chatList.appendChild(day);
      }

      const item = document.createElement('div');
      const isSelected = state.selectedIds.has(thread.id);
      item.className = `chat-item chat-history-main-item${thread.id === state.activeThreadId ? ' active' : ''}${isSelected ? ' selected' : ''}`;
      item.onclick = (e) => handleRemoteChatClick(e, thread);

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'chat-history-main-checkbox';
      checkbox.checked = state.selectedIds.has(thread.id);
      checkbox.title = 'Select for bulk delete';
      checkbox.addEventListener('click', event => {
        event.stopPropagation();
        selectRemoteCheckbox(thread.id, Boolean(event.target.checked));
      });

      const text = document.createElement('div');
      text.className = 'chat-history-main-text';

      const title = document.createElement('span');
      title.className = 'chat-item-title';
      title.textContent = thread.title || thread.id;

      const meta = document.createElement('span');
      meta.className = 'chat-history-main-meta';
      const count = displayMessageCount(thread);
      const rawCount = rawMessageCount(thread);
      const errorCount = Number(thread.error_message_count || 0);
      const countText = count > 0 ? `${count} message${count === 1 ? '' : 's'}` : 'metadata only';
      const errorText = errorCount > 0 ? `; ${errorCount} error${errorCount === 1 ? '' : 's'}` : '';
      meta.textContent = `${countText}${errorText} · Last ${timeLabel(thread)}`;

      const dot = document.createElement('span');
      if (thread.hydrating) {
        dot.className = 'chat-history-main-dot hydrating';
        dot.title = 'Hydrating...';
      } else {
        dot.className = `chat-history-main-dot${Boolean(thread.hydrated || rawCount > 0) ? ' hydrated' : ''}`;
        dot.title = rawCount > 0 ? 'Hydrated' : 'Metadata only';
      }

      text.appendChild(title);
      text.appendChild(meta);
      item.appendChild(checkbox);
      item.appendChild(text);
      item.appendChild(dot);
      chatList.appendChild(item);
    });

    if (state.loading && state.threads.length > 0) {
      const loadingIndicator = document.createElement('div');
      loadingIndicator.className = 'chat-history-main-status';
      loadingIndicator.style.margin = '8px 12px';
      loadingIndicator.style.padding = '0';
      loadingIndicator.textContent = 'Loading more chats...';
      chatList.appendChild(loadingIndicator);
    }

    chatList.appendChild(toolbar);
  }

  async function refresh() {
    await loadInitialRemoteThreads();
  }

  function patchChatManager() {
    const manager = window.NotionAI?.Chat?.Manager;
    if (!manager || state.patched) return false;
    const originalRender = manager.renderChatList.bind(manager);
    const originalStart = manager.startNewChat.bind(manager);
    const originalSelect = manager.selectChat.bind(manager);

    manager.renderChatList = function patchedRenderChatList(...args) {
      const maybeOptions = args.length && args[0] && typeof args[0] === 'object' ? args[0] : {};
      if (maybeOptions.forceHistoryMode === 'local' || maybeOptions.forceHistoryMode === 'remote') {
        state.sidebarMode = maybeOptions.forceHistoryMode;
      }

      const chatList = document.getElementById('chatList');
      const savedScrollTop = chatList ? chatList.scrollTop : 0;

      originalRender(...args);

      const newChatList = document.getElementById('chatList');
      if (state.sidebarMode === 'remote' && newChatList) {
        // Remote mode is remote-only. Clear any local rows rendered by the
        // base chat manager before adding the mode switch and remote list.
        newChatList.innerHTML = '';
      }
      if (newChatList) {
        if (!newChatList.dataset.patchedScroll) {
          newChatList.dataset.patchedScroll = 'true';
          newChatList.addEventListener('scroll', handleScroll);
        }

        const searchInput = document.getElementById('searchInput');
        if (searchInput && !searchInput.dataset.patchedSearch) {
          searchInput.dataset.patchedSearch = 'true';
          searchInput.addEventListener('input', () => {
            window.NotionAI?.Chat?.Manager?.renderChatList?.();
          });
        }
      }

      renderHistoryModeControls(newChatList);
      if (state.sidebarMode === 'remote') {
        renderRemoteChats(newChatList);
      }

      if (newChatList) {
        const nextScrollTop = state.resetSidebarScrollOnce ? 0 : savedScrollTop;
        newChatList.scrollTop = nextScrollTop;
        state.resetSidebarScrollOnce = false;
      }
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
    window.addEventListener('chat-history:updated', async (event) => {
      await refresh();
      const hydrate = Boolean(event?.detail?.hydrate);
      if (hydrate) {
        await reloadSelectedRemoteThread();
      }
    });
    refresh();
  }

  window.NotionAI = window.NotionAI || {};
  window.NotionAI.ChatHistoryMain = {
    refresh,
    reloadSelectedRemoteThread,
    clearRemoteSelection,
    setSidebarMode,
    deleteSelectedRemoteThreads,
    clearSelectedRemoteThreads,
    selectFilteredRemoteThreads,
    hydrateSelectedRemoteThreads,
    selectUnhydratedRemoteThreads,
    cleanupSingleMessageThreads,
    cleanupErroredThreads,
    exportTwoMessageThreads,
    backupRemoteChats,
    deletePingPongRemoteThreads,
    stopHydration
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
