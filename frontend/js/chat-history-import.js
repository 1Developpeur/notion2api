(() => {
  const ENDPOINT = '/v1/chat-history/import/har';

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

  function ensureStyles() {
    if (document.getElementById('chatHistoryImportStyles')) return;
    const style = document.createElement('style');
    style.id = 'chatHistoryImportStyles';
    style.textContent = `
      .chat-history-import-status{font-size:12px;line-height:1.5;color:var(--text-secondary);margin-top:8px;white-space:pre-wrap;word-break:break-word}
      .chat-history-import-warning{font-size:12px;line-height:1.5;color:var(--text-secondary);background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:12px}
      .chat-history-file-input{width:100%;padding:8px 0;color:var(--text-secondary)}
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
          <div class="chat-history-import-warning">
            Select a browser HAR JSON file captured from Notion. The file is sent only to this local notion2api server and stored in the local chat-history archive.
          </div>
          <div class="form-group">
            <label>HAR file</label>
            <input id="chatHistoryHarInput" class="chat-history-file-input" type="file" accept=".har,application/json">
          </div>
          <div id="chatHistoryImportStatus" class="chat-history-import-status"></div>
        </div>
        <div class="modal-footer">
          <button id="cancelChatHistoryImportBtn" class="btn-secondary" type="button">Cancel</button>
          <button id="runChatHistoryImportBtn" class="btn-primary" type="button">Import</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    document.getElementById('closeChatHistoryImportBtn').addEventListener('click', closeModal);
    document.getElementById('cancelChatHistoryImportBtn').addEventListener('click', closeModal);
    document.getElementById('runChatHistoryImportBtn').addEventListener('click', importHar);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });

    return modal;
  }

  function setStatus(text, isError = false) {
    const status = document.getElementById('chatHistoryImportStatus');
    if (!status) return;
    status.textContent = text || '';
    status.style.color = isError ? '#a94442' : 'var(--text-secondary)';
  }

  function openModal() {
    ensureStyles();
    const modal = ensureModal();
    const input = document.getElementById('chatHistoryHarInput');
    if (input) input.value = '';
    setStatus('');
    modal.classList.remove('hidden');
  }

  function closeModal() {
    const modal = document.getElementById('chatHistoryImportModal');
    if (modal) modal.classList.add('hidden');
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

    const btn = document.getElementById('runChatHistoryImportBtn');
    btn.disabled = true;
    btn.textContent = 'Importing...';
    setStatus('Importing chat history into the local archive...');

    try {
      const response = await fetch(`${getBaseUrl()}${ENDPOINT}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getApiKey()}`,
          'X-Client-Type': 'Web'
        },
        body: JSON.stringify(har)
      });
      let data = null;
      try { data = await response.json(); } catch (err) {}
      if (!response.ok) {
        const message = data?.detail || data?.error?.message || `Import failed with HTTP ${response.status}`;
        throw new Error(message);
      }
      const imported = data?.imported || {};
      setStatus(`Import complete.\nThreads: ${imported.threads || 0}\nMessages: ${imported.messages || 0}`);
    } catch (err) {
      setStatus(err?.message || String(err), true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Import';
    }
  }

  function injectButton() {
    if (document.getElementById('chatHistoryImportBtn')) return;
    const footer = document.querySelector('.sidebar-footer');
    if (!footer) return;
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
  }

  function init() {
    ensureStyles();
    injectButton();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
