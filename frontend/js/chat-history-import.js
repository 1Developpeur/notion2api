(() => {
  const HAR_ENDPOINT = '/v1/chat-history/import/har';
  const NOTION_SYNC_ENDPOINT = '/v1/chat-history/sync/notion';

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
    const headers = {
      'Content-Type': 'application/json',
      'X-Client-Type': 'Web'
    };
    const key = getApiKey();
    if (key) headers.Authorization = `Bearer ${key}`;
    return headers;
  }

  function ensureStyles() {
    if (document.getElementById('chatHistoryImportStyles')) return;
    const style = document.createElement('style');
    style.id = 'chatHistoryImportStyles';
    style.textContent = `
      .chat-history-import-status{font-size:12px;line-height:1.5;color:var(--text-secondary);margin-top:8px;white-space:pre-wrap;word-break:break-word}
      .chat-history-import-warning{font-size:12px;line-height:1.5;color:var(--text-secondary);background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:12px}
      .chat-history-file-input{width:100%;padding:8px 0;color:var(--text-secondary)}
      .chat-history-tabs{display:flex;gap:6px;margin-bottom:12px}
      .chat-history-tab{flex:1;border:1px solid var(--border);border-radius:6px;padding:7px 10px;font-size:12px;color:var(--text-secondary);background:var(--card-bg)}
      .chat-history-tab.active{border-color:var(--border-active);color:var(--text);font-weight:500}
      .chat-history-panel.hidden{display:none!important}
      .chat-history-inline-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
      .chat-history-inline-grid input{width:100%}
      .chat-history-checkbox-row{display:flex;align-items:center;gap:8px;margin-top:10px;font-size:12px;color:var(--text-secondary)}
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    let modal = document.getElementById('chatHistoryImportModal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'chatHistoryImportModal';
    modal.className = 'modal-overlay hidden';
    modal.innerHTML = `
      <div class="modal-content">
        <div class="modal-header">
          <h3>Import Notion AI chat history</h3>
          <button id="closeChatHistoryImportBtn" class="modal-close-btn" type="button" aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="chat-history-tabs">
            <button id="chatHistoryPullTab" class="chat-history-tab active" type="button">Pull from Notion</button>
            <button id="chatHistoryHarTab" class="chat-history-tab" type="button">Import HAR</button>
          </div>

          <div id="chatHistoryPullPanel" class="chat-history-panel">
            <div class="chat-history-import-warning">
              Pull chat-history metadata directly from the configured Notion account. Full chat content is hydrated later only when a specific chat is selected, unless you enable full-content hydration below.
            </div>
            <div class="chat-history-inline-grid">
              <div class="form-group">
                <label>Account</label>
                <input id="chatHistoryAccountIndex" type="number" min="0" step="1" value="0">
              </div>
              <div class="form-group">
                <label>Limit</label>
                <input id="chatHistorySyncLimit" type="number" min="1" max="500" step="1" value="50">
              </div>
              <div class="form-group">
                <label>Pages</label>
                <input id="chatHistorySyncPages" type="number" min="1" max="20" step="1" value="2">
              </div>
            </div>
            <label class="chat-history-checkbox-row">
              <input id="chatHistoryHydrateAll" type="checkbox">
              Hydrate full content for all synced chats now. Slower.
            </label>
          </div>

          <div id="chatHistoryHarPanel" class="chat-history-panel hidden">
            <div class="chat-history-import-warning">
              Select a browser HAR JSON file captured from Notion. The file is sent only to this local notion2api server and stored in the local chat-history archive.
            </div>
            <div class="form-group">
              <label>HAR file</label>
              <input id="chatHistoryHarInput" class="chat-history-file-input" type="file" accept=".har,application/json">
            </div>
          </div>

          <div id="chatHistoryImportStatus" class="chat-history-import-status"></div>
        </div>
        <div class="modal-footer">
          <button id="cancelChatHistoryImportBtn" class="btn-secondary" type="button">Cancel</button>
          <button id="runChatHistoryPullBtn" class="btn-primary" type="button">Pull history</button>
          <button id="runChatHistoryHarImportBtn" class="btn-primary hidden" type="button">Import HAR</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    document.getElementById('closeChatHistoryImportBtn').addEventListener('click', closeModal);
    document.getElementById('cancelChatHistoryImportBtn').addEventListener('click', closeModal);
    document.getElementById('runChatHistoryPullBtn').addEventListener('click', pullFromNotion);
    document.getElementById('runChatHistoryHarImportBtn').addEventListener('click', importHar);
    document.getElementById('chatHistoryPullTab').addEventListener('click', () => setMode('pull'));
    document.getElementById('chatHistoryHarTab').addEventListener('click', () => setMode('har'));
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });

    return modal;
  }

  function setMode(mode) {
    const pullMode = mode === 'pull';
    document.getElementById('chatHistoryPullTab')?.classList.toggle('active', pullMode);
    document.getElementById('chatHistoryHarTab')?.classList.toggle('active', !pullMode);
    document.getElementById('chatHistoryPullPanel')?.classList.toggle('hidden', !pullMode);
    document.getElementById('chatHistoryHarPanel')?.classList.toggle('hidden', pullMode);
    document.getElementById('runChatHistoryPullBtn')?.classList.toggle('hidden', !pullMode);
    document.getElementById('runChatHistoryHarImportBtn')?.classList.toggle('hidden', pullMode);
    setStatus('');
  }

  function setStatus(text, isError = false) {
    const status = document.getElementById('chatHistoryImportStatus');
    if (!status) return;
    status.textContent = text || '';
    status.style.color = isError ? '#a94442' : 'var(--text-secondary)';
  }

  function resultText(prefix, data) {
    const imported = data?.imported || {};
    const stats = data?.stats || {};
    const lines = [prefix];
    lines.push(`Threads imported: ${imported.threads ?? stats.threads ?? 0}`);
    lines.push(`Messages imported: ${imported.messages ?? stats.messages ?? 0}`);
    if (stats.pages_fetched !== undefined) lines.push(`Pages fetched: ${stats.pages_fetched}`);
    if (stats.hydration_candidate_ids !== undefined) lines.push(`Hydration candidates: ${stats.hydration_candidate_ids}`);
    if (stats.hydrated_message_ids !== undefined) lines.push(`Message IDs hydrated: ${stats.hydrated_message_ids}`);
    if (stats.hydration_batches !== undefined) lines.push(`Hydration batches: ${stats.hydration_batches}`);
    return lines.join('\n');
  }

  function openModal() {
    ensureStyles();
    const modal = ensureModal();
    const input = document.getElementById('chatHistoryHarInput');
    if (input) input.value = '';
    setMode('pull');
    setStatus('');
    modal.classList.remove('hidden');
  }

  function closeModal() {
    const modal = document.getElementById('chatHistoryImportModal');
    if (modal) modal.classList.add('hidden');
  }

  async function pullFromNotion() {
    const btn = document.getElementById('runChatHistoryPullBtn');
    const accountIndex = Number.parseInt(document.getElementById('chatHistoryAccountIndex')?.value || '0', 10);
    const limit = Number.parseInt(document.getElementById('chatHistorySyncLimit')?.value || '50', 10);
    const maxPages = Number.parseInt(document.getElementById('chatHistorySyncPages')?.value || '2', 10);
    const hydrate = Boolean(document.getElementById('chatHistoryHydrateAll')?.checked);

    btn.disabled = true;
    btn.textContent = hydrate ? 'Pulling full content...' : 'Pulling metadata...';
    setStatus(hydrate ? 'Pulling and hydrating full Notion chat history. This can take a while...' : 'Pulling Notion chat metadata into the local archive...');

    try {
      const response = await fetch(`${getBaseUrl()}${NOTION_SYNC_ENDPOINT}`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          account_index: Number.isFinite(accountIndex) ? accountIndex : 0,
          limit: Number.isFinite(limit) ? limit : 50,
          max_pages: Number.isFinite(maxPages) ? maxPages : 2,
          hydrate
        })
      });
      let data = null;
      try { data = await response.json(); } catch (err) {}
      if (!response.ok) {
        const detail = data?.detail;
        const message = detail?.error?.message || detail || data?.error?.message || `Pull failed with HTTP ${response.status}`;
        throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
      }
      setStatus(resultText(hydrate ? 'Full pull complete.' : 'Metadata pull complete.', data));
    } catch (err) {
      setStatus(err?.message || String(err), true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Pull history';
    }
  }

  async function importHar() {
    const input = document.getElementById('chatHistoryHarInput');
    const file = input?.files?.[0];
    if (!file) {
      setStatus('Choose a HAR file first.', true);
      return;
    }

    let har;
    try {
      har = JSON.parse(await file.text());
    } catch (err) {
      setStatus('The selected file is not valid JSON/HAR.', true);
      return;
    }

    const btn = document.getElementById('runChatHistoryHarImportBtn');
    btn.disabled = true;
    btn.textContent = 'Importing...';
    setStatus('Importing HAR chat history into the local archive...');

    try {
      const response = await fetch(`${getBaseUrl()}${HAR_ENDPOINT}`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(har)
      });
      let data = null;
      try { data = await response.json(); } catch (err) {}
      if (!response.ok) {
        const message = data?.detail || data?.error?.message || `Import failed with HTTP ${response.status}`;
        throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
      }
      setStatus(resultText('HAR import complete.', data));
    } catch (err) {
      setStatus(err?.message || String(err), true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Import HAR';
    }
  }

  function injectButton() {
    if (document.getElementById('chatHistoryImportBtn')) return true;
    const footer = document.querySelector('.sidebar-footer');
    if (!footer) return false;
    const btn = document.createElement('button');
    btn.id = 'chatHistoryImportBtn';
    btn.className = 'sidebar-footer-btn';
    btn.type = 'button';
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/></svg>
      Import chats
    `;
    btn.addEventListener('click', openModal);
    footer.insertBefore(btn, footer.firstChild);
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