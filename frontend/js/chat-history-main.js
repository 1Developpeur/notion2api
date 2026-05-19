(() => {
  const THREADS_ENDPOINT = '/v1/chat-history/threads';
  const DELETE_ENDPOINT = '/v1/chat-history/threads/delete';
  const PAGE_SIZE = 200;
  const BULK_DELETE_SIZE = 200;
  const REMOTE_ID_PREFIX = 'remote-chat-history:';
  const state = {
    threads: [],
    selectedIds: new Set(),
    filterText: '',
    offset: 0,
    hasMore: false,
    loading: false,
    deleting: false,
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
      .chat-history-main-toolbar{display:flex;gap:6px;align-items:center;padding:3px 12px 7px;flex-wrap:wrap}
      .chat-history-main-toolbar button{border:1px solid var(--border);background:transparent;color:var(--text-secondary);border-radius:4px;font-size:11px;padding:4px 6px;line-height:1.1}
      .chat-history-main-toolbar button:hover:not(:disabled){background:var(--bg-hover);color:var(--text)}
      .chat-history-main-toolbar button:disabled{opacity:.45;cursor:not-allowed}
      .chat-history-main-filter{width:100%;box-sizing:border-box;border:1px solid var(--border);border-radius:4px;background:transparent;color:var(--text);font-size:12px;padding:6px 8px;outline:none}
      .chat-history-main-filter:focus{border-color:var(--accent,#7c3aed)}
      .chat-history-main-summary{width:100%;font-size:10px;color:var(--text-tertiary);padding:0 1px}
      .chat-history-main-delete{color:#a94442!important;border-color:#a94442!important}
      .chat-item.chat-history-main-item{align-items:flex-start;gap:8px;padding-top:7px;padding-bottom:7px}
      .chat-history-main-checkbox{margin-top:4px;flex-shrink:0}
      .chat-history-main-text{min-width:0;flex:1;display:flex;flex-direction:column;gap:2px}
      .chat-history-main-meta{font-size:10px;color:var(--text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .chat-history-main-dot{width:7px;height:7px;border-radius:999px;margin-top:6px;flex-shrink:0;background:var(--text-tertiary);opacity:.7}
      .chat-history-main-dot.hydrated{background:#2e7d32;opacity:1}
      .chat-history-main-load{width:calc(100% - 24px);margin:6px 12px;padding:6px 8px;border-radius:4px;font-size:12px;color:var(--text-secondary);background:transparent;text-align:left}
      .chat-history-main-load:hover{background:var(--bg-hover);color:var(--text)}
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

  function pruneSelectionToLoadedThreads() {
    const loadedIds = new Set(state.threads.map(thread => thread.id));
    for (const id of Array.from(state.selectedIds)) {
      if (!loadedIds.has(id)) state.selectedIds.delete(id);
    }
  }

  function matchesFilter(thread) {
    const query = state.filterText.trim().toLowerCase();
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
    return state.threads.filter(matchesFilter);
  }

  function selectRemoteCheckbox(threadId, checked) {
    if (checked) state.selectedIds.add(threadId);
    else state.selectedIds.delete(threadId);
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  async function loadAllRemoteThreads() {
    if (state.loading) return;
    state.loading = true;
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
    try {
      const allThreads = [];
      const seen = new Set();
      let offset = 0;
      while (true) {
        const data = await fetchJson(`${THREADS_ENDPOINT}?limit=${PAGE_SIZE}&offset=${offset}`);
        const page = Array.isArray(data?.threads) ? data.threads : [];
        for (const thread of page) {
          if (!thread?.id || seen.has(thread.id)) continue;
          seen.add(thread.id);
          allThreads.push(thread);
        }
        offset += page.length;
        if (page.length < PAGE_SIZE) break;
      }
      state.threads = allThreads;
      state.offset = allThreads.length;
      state.hasMore = false;
      pruneSelectionToLoadedThreads();
    } catch (err) {
      console.warn('Unable to load all remote chat history', err);
      renderStatus(`Unable to load all remote chats: ${err?.message || String(err)}`);
    } finally {
      state.loading = false;
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
    }
  }

  async function selectFilteredRemoteThreads() {
    if (state.loading || state.deleting) return;
    if (state.hasMore) await loadAllRemoteThreads();
    const visibleThreads = getVisibleThreads();
    for (const thread of visibleThreads) {
      if (thread?.id) state.selectedIds.add(thread.id);
    }
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  function clearSelectedRemoteThreads() {
    state.selectedIds.clear();
    window.NotionAI?.Chat?.Manager?.renderChatList?.();
  }

  async function deleteSelectedRemoteThreads() {
    const ids = Array.from(state.selectedIds);
    if (!ids.length || state.deleting) return;
    const confirmed = window.confirm(`Delete ${ids.length} selected remote chat(s)? Confirmed deletes will also be removed from the local archive.`);
    if (!confirmed) return;

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
    const threads = getVisibleThreads();

    if (!state.threads.length && !state.loading && !state.filterText) return;

    const header = document.createElement('div');
    header.className = 'chat-section-header';
    header.textContent = 'REMOTE CHATS';
    chatList.appendChild(header);

    const toolbar = document.createElement('div');
    toolbar.className = 'chat-history-main-toolbar';

    const filter = document.createElement('input');
    filter.type = 'search';
    filter.className = 'chat-history-main-filter';
    filter.placeholder = 'Filter remote chat history by title, id, preview, or date';
    filter.value = state.filterText;
    filter.addEventListener('click', event => event.stopPropagation());
    filter.addEventListener('input', event => {
      state.filterText = String(event.target.value || '');
      window.NotionAI?.Chat?.Manager?.renderChatList?.();
      const nextFilter = document.querySelector('.chat-history-main-filter');
      if (nextFilter) {
        nextFilter.focus();
        nextFilter.setSelectionRange(nextFilter.value.length, nextFilter.value.length);
      }
    });

    const selectedCount = state.selectedIds.size;
    const visibleCount = threads.length;

    const summary = document.createElement('div');
    summary.className = 'chat-history-main-summary';
    const loadedText = state.hasMore ? `${state.threads.length}+ loaded` : `${state.threads.length} loaded`;
    const filterText = state.filterText.trim() ? `${visibleCount} matched` : `${visibleCount} visible`;
    summary.textContent = `${filterText}; ${loadedText}; ${selectedCount} selected`;

    const selectBtn = document.createElement('button');
    selectBtn.type = 'button';
    selectBtn.textContent = state.filterText.trim() ? 'Select filtered' : 'Select all';
    selectBtn.disabled = state.deleting || state.loading || (!state.threads.length && !state.hasMore);
    selectBtn.title = state.hasMore ? 'Loads all archived pages first, then selects every matching conversation.' : 'Select every currently matching conversation.';
    selectBtn.addEventListener('click', event => {
      event.stopPropagation();
      selectFilteredRemoteThreads();
    });

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.textContent = 'Clear';
    clearBtn.disabled = state.deleting || (!selectedCount && !state.filterText);
    clearBtn.addEventListener('click', event => {
      event.stopPropagation();
      if (state.filterText) state.filterText = '';
      clearSelectedRemoteThreads();
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

    toolbar.appendChild(filter);
    toolbar.appendChild(summary);
    toolbar.appendChild(selectBtn);
    toolbar.appendChild(clearBtn);
    toolbar.appendChild(deleteBtn);
    chatList.appendChild(toolbar);

    if (state.loading && !state.threads.length) {
      const loading = document.createElement('div');
      loading.className = 'chat-history-main-status';
      loading.style.margin = '8px 12px';
      loading.style.padding = '0';
      loading.textContent = 'Loading...';
      chatList.appendChild(loading);
      return;
    }

    if (!threads.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-history-main-empty';
      empty.textContent = state.filterText.trim()
        ? 'No loaded remote chats match this filter. Use “Load more” or “Select filtered” to search older loaded pages before selecting.'
        : 'No remote chats are loaded.';
      chatList.appendChild(empty);
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
      const count = Number(thread.message_count || 0);
      meta.textContent = count > 0 ? `${count} messages` : 'metadata only';

      const dot = document.createElement('span');
      dot.className = `chat-history-main-dot${Boolean(thread.hydrated || count > 0) ? ' hydrated' : ''}`;
      dot.title = count > 0 ? 'Hydrated' : 'Metadata only';

      text.appendChild(title);
      text.appendChild(meta);
      item.appendChild(checkbox);
      item.appendChild(text);
      item.appendChild(dot);
      chatList.appendChild(item);
    });

    if (state.hasMore) {
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'chat-history-main-load';
      more.textContent = state.loading
        ? 'Loading...'
        : state.filterText.trim()
          ? 'Load more to search older remote chats'
          : 'Load more remote chats';
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
      pruneSelectionToLoadedThreads();
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
    clearRemoteSelection,
    deleteSelectedRemoteThreads,
    clearSelectedRemoteThreads,
    selectFilteredRemoteThreads
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
