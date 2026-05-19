(() => {
  const THREADS_ENDPOINT = '/v1/chat-history/threads';

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

  function esc(text) {
    const node = document.createElement('div');
    node.textContent = text == null ? '' : String(text);
    return node.innerHTML;
  }

  function ensureStyles() {
    if (document.getElementById('chatHistoryBrowserStyles')) return;
    const style = document.createElement('style');
    style.id = 'chatHistoryBrowserStyles';
    style.textContent = `
      .chat-history-browser-modal .modal-content{width:min(1180px,92vw);height:min(760px,86vh);display:flex;flex-direction:column}
      .chat-history-browser-modal .modal-body{flex:1;min-height:0;display:flex;flex-direction:column;padding:0}
      .chat-history-browser-summary{padding:12px 20px;border-bottom:1px solid var(--border);font-size:12px;color:var(--text-secondary);display:flex;gap:14px;flex-wrap:wrap}
      .chat-history-browser-layout{flex:1;min-height:0;display:grid;grid-template-columns:340px 1fr}
      .chat-history-browser-list{border-right:1px solid var(--border);overflow:auto;padding:12px}
      .chat-history-browser-preview{overflow:auto;padding:24px}
      .chat-history-browser-item{width:100%;text-align:left;border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px;background:var(--card-bg);color:var(--text);display:block}
      .chat-history-browser-item:hover{border-color:var(--border-hover);background:var(--bg-hover)}
      .chat-history-browser-item.active{border-color:var(--border-active)}
      .chat-history-browser-title{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:4px}
      .chat-history-browser-meta{font-size:11px;color:var(--text-tertiary);line-height:1.5}
      .chat-history-hydrated-yes{color:#2e7d32}
      .chat-history-hydrated-no{color:#a94442}
      .chat-history-empty-warning{border:1px solid #f0ad4e;background:rgba(240,173,78,.12);border-radius:8px;padding:10px 12px;margin:12px 0;color:var(--text-secondary);font-size:13px;line-height:1.5}
      .chat-history-browser-markdown{font-size:14px;line-height:1.65;color:var(--text);white-space:normal}
      .chat-history-browser-markdown pre{white-space:pre-wrap;word-break:break-word;background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px}
      .chat-history-browser-markdown code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
      @media(max-width:768px){.chat-history-browser-layout{grid-template-columns:1fr}.chat-history-browser-list{border-right:0;border-bottom:1px solid var(--border);max-height:260px}.chat-history-browser-preview{padding:16px}}
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    let modal = document.getElementById('chatHistoryBrowserModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'chatHistoryBrowserModal';
    modal.className = 'modal-overlay hidden chat-history-browser-modal';
    modal.innerHTML = `
      <div class="modal-content">
        <div class="modal-header">
          <h3>Remote chat history</h3>
          <div style="display:flex;align-items:center;gap:8px">
            <button id="refreshChatHistoryBrowserBtn" class="btn-secondary" type="button">Refresh</button>
            <button id="closeChatHistoryBrowserBtn" class="modal-close-btn" type="button" aria-label="Close">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
          </div>
        </div>
        <div class="modal-body">
          <div id="chatHistoryBrowserSummary" class="chat-history-browser-summary">Loading synced threads...</div>
          <div class="chat-history-browser-layout">
            <div id="chatHistoryBrowserList" class="chat-history-browser-list"></div>
            <div id="chatHistoryBrowserPreview" class="chat-history-browser-preview">
              <div class="chat-history-browser-markdown">Select a synced thread.</div>
            </div>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    document.getElementById('closeChatHistoryBrowserBtn').addEventListener('click', closeModal);
    document.getElementById('refreshChatHistoryBrowserBtn').addEventListener('click', loadThreads);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });
    return modal;
  }

  function setSummary(text) {
    const el = document.getElementById('chatHistoryBrowserSummary');
    if (el) el.textContent = text;
  }

  function renderMarkdown(markdown) {
    if (window.NotionAI?.Utils?.Markdown?.renderToSafeHtml) {
      return window.NotionAI.Utils.Markdown.renderToSafeHtml(markdown || '');
    }
    if (window.marked && window.DOMPurify) {
      return DOMPurify.sanitize(marked.parse(markdown || ''));
    }
    return `<pre>${esc(markdown || '')}</pre>`;
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

  async function fetchText(path) {
    const response = await fetch(`${getBaseUrl()}${path}`, { headers: getHeaders() });
    const text = await response.text();
    if (!response.ok) throw new Error(text || `HTTP ${response.status}`);
    return text;
  }

  function renderThreadList(threads) {
    const list = document.getElementById('chatHistoryBrowserList');
    if (!list) return;
    list.innerHTML = '';
    if (!threads.length) {
      list.innerHTML = '<div class="chat-history-empty-warning">No synced threads found. Use Import chats → Pull from Notion first.</div>';
      return;
    }
    for (const thread of threads) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chat-history-browser-item';
      btn.dataset.threadId = thread.id;
      const count = Number(thread.message_count || 0);
      const hydrated = Boolean(thread.hydrated || count > 0);
      btn.innerHTML = `
        <div class="chat-history-browser-title">${esc(thread.title || thread.id)}</div>
        <div class="chat-history-browser-meta">
          Messages: ${count} · Hydrated: <span class="${hydrated ? 'chat-history-hydrated-yes' : 'chat-history-hydrated-no'}">${hydrated ? 'yes' : 'no'}</span><br>
          Updated: ${esc(thread.updated_at || thread.last_edited_time || thread.created_time || 'Unknown date')}<br>
          ${esc(thread.first_message_preview || thread.last_message_preview || '')}
        </div>
      `;
      btn.addEventListener('click', () => selectThread(thread, threads));
      list.appendChild(btn);
    }
  }

  async function selectThread(thread, threads) {
    const list = document.getElementById('chatHistoryBrowserList');
    list?.querySelectorAll('.chat-history-browser-item').forEach(el => el.classList.toggle('active', el.dataset.threadId === thread.id));
    const preview = document.getElementById('chatHistoryBrowserPreview');
    if (!preview) return;
    const count = Number(thread.message_count || 0);
    const hydrated = Boolean(thread.hydrated || count > 0);
    preview.innerHTML = `<div class="chat-history-browser-markdown">Loading ${esc(thread.title || thread.id)}...</div>`;
    try {
      const markdown = await fetchText(`${THREADS_ENDPOINT}/${encodeURIComponent(thread.id)}/markdown`);
      const warning = count === 0
        ? '<div class="chat-history-empty-warning"><strong>Empty hydrated message set.</strong><br>This thread record exists, but no message rows are attached yet. Run a larger sync, then check the debug endpoint for raw message fields.</div>'
        : '';
      preview.innerHTML = `
        <div class="chat-history-browser-summary" style="padding:0 0 12px;border-bottom:0">
          <span>Total synced threads: ${threads.length}</span>
          <span>Selected messages: ${count}</span>
          <span>Hydrated: ${hydrated ? 'yes' : 'no'}</span>
        </div>
        ${warning}
        <div class="chat-history-browser-markdown">${renderMarkdown(markdown)}</div>
      `;
    } catch (err) {
      preview.innerHTML = `<div class="chat-history-empty-warning">${esc(err?.message || String(err))}</div>`;
    }
  }

  async function loadThreads() {
    const list = document.getElementById('chatHistoryBrowserList');
    const preview = document.getElementById('chatHistoryBrowserPreview');
    if (list) list.innerHTML = '<div class="chat-history-browser-meta">Loading...</div>';
    if (preview) preview.innerHTML = '<div class="chat-history-browser-markdown">Select a synced thread.</div>';
    setSummary('Loading synced threads...');
    try {
      const data = await fetchJson(`${THREADS_ENDPOINT}?limit=200&offset=0`);
      const threads = Array.isArray(data?.threads) ? data.threads : [];
      const hydrated = threads.filter(t => Number(t.message_count || 0) > 0).length;
      setSummary(`Total synced threads: ${threads.length} · Hydrated: ${hydrated} · Empty: ${threads.length - hydrated}`);
      renderThreadList(threads);
      if (threads.length) selectThread(threads[0], threads);
    } catch (err) {
      setSummary('Failed to load chat history.');
      if (list) list.innerHTML = `<div class="chat-history-empty-warning">${esc(err?.message || String(err))}</div>`;
    }
  }

  function openModal() {
    ensureStyles();
    const modal = ensureModal();
    modal.classList.remove('hidden');
    loadThreads();
  }

  function closeModal() {
    document.getElementById('chatHistoryBrowserModal')?.classList.add('hidden');
  }

  function injectButton() {
    if (document.getElementById('chatHistoryBrowseBtn')) return true;
    const footer = document.querySelector('.sidebar-footer');
    if (!footer) return false;
    const btn = document.createElement('button');
    btn.id = 'chatHistoryBrowseBtn';
    btn.className = 'sidebar-footer-btn';
    btn.type = 'button';
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h10M7 16h6"/></svg>
      Browse chats
    `;
    btn.addEventListener('click', openModal);
    const settings = document.getElementById('settingsBtn');
    footer.insertBefore(btn, settings || footer.firstChild);
    return true;
  }

  function init() {
    ensureStyles();
    if (injectButton()) return;
    const observer = new MutationObserver(() => {
      if (injectButton()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => observer.disconnect(), 10000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
