(() => {
  const FEATURES_ENDPOINT = '/v1/features';
  const ATTACHMENTS_ENDPOINT = '/v1/features/attachments';

  function getBaseUrl() {
    return window.NotionAI?.Core?.State?.get?.('baseUrl') || localStorage.getItem('claude_base_url') || window.location.origin;
  }

  function getApiKey() {
    return window.NotionAI?.Core?.State?.get?.('apiKey') || localStorage.getItem('claude_api_key') || sessionStorage.getItem('claude_api_key') || '';
  }

  function headers() {
    const h = { 'Accept': 'application/json', 'Content-Type': 'application/json', 'X-Client-Type': 'Web' };
    const key = getApiKey();
    if (key) h.Authorization = `Bearer ${key}`;
    return h;
  }

  function ensureSettingsControl() {
    if (document.getElementById('attachmentFeatureGroup')) return;
    const modalBody = document.querySelector('#settingsModal .modal-body');
    if (!modalBody) return;

    const group = document.createElement('div');
    group.id = 'attachmentFeatureGroup';
    group.className = 'form-group';
    group.innerHTML = `
      <label style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
        <span>File uploads</span>
        <input type="checkbox" id="attachmentFeatureToggle" />
      </label>
      <div id="attachmentFeatureStatus" style="font-size:12px;color:var(--text-secondary);line-height:1.45;margin-top:6px;">Checking attachment status...</div>
    `;
    modalBody.appendChild(group);

    document.getElementById('attachmentFeatureToggle')?.addEventListener('change', async event => {
      await setAttachmentEnabled(Boolean(event.target.checked));
    });
  }

  function renderStatus(features) {
    const status = document.getElementById('attachmentFeatureStatus');
    const toggle = document.getElementById('attachmentFeatureToggle');
    if (!status || !toggle || !features?.attachments) return;

    const attachments = features.attachments;
    toggle.checked = Boolean(attachments.enabled);

    const maxMb = Math.round((Number(attachments.max_attachment_bytes || 0) / 1024 / 1024) * 10) / 10;
    const warnings = Array.isArray(attachments.warnings) ? attachments.warnings : [];
    const warningText = warnings.length ? `<br><strong>Warning:</strong> ${warnings.join(' ')}` : '';
    status.innerHTML = `${attachments.enabled ? 'Enabled' : 'Disabled'} · max ${attachments.max_attachments_per_request || 0} file(s), ${maxMb} MB each.${warningText}`;
  }

  async function refreshFeatures() {
    ensureSettingsControl();
    const status = document.getElementById('attachmentFeatureStatus');
    try {
      const response = await fetch(`${getBaseUrl()}${FEATURES_ENDPOINT}`, { headers: headers() });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || data?.detail || `HTTP ${response.status}`);
      window.NotionAI.Core.State.set('features', data);
      renderStatus(data);
      return data;
    } catch (err) {
      if (status) status.textContent = `Could not read attachment status: ${err?.message || String(err)}`;
      return null;
    }
  }

  async function setAttachmentEnabled(enabled) {
    const status = document.getElementById('attachmentFeatureStatus');
    const toggle = document.getElementById('attachmentFeatureToggle');
    if (toggle) toggle.disabled = true;
    if (status) status.textContent = enabled ? 'Enabling file uploads...' : 'Disabling file uploads...';
    try {
      const response = await fetch(`${getBaseUrl()}${ATTACHMENTS_ENDPOINT}`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ enabled })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.error?.message || data?.detail || `HTTP ${response.status}`);
      window.NotionAI.Core.State.set('features', data);
      renderStatus(data);
      return data;
    } catch (err) {
      if (status) status.textContent = `Could not update file uploads: ${err?.message || String(err)}`;
      await refreshFeatures();
      return null;
    } finally {
      if (toggle) toggle.disabled = false;
    }
  }

  function init() {
    ensureSettingsControl();
    refreshFeatures();
    const settingsBtn = document.getElementById('settingsBtn');
    settingsBtn?.addEventListener('click', () => setTimeout(refreshFeatures, 0));
  }

  window.NotionAI = window.NotionAI || {};
  window.NotionAI.Attachments = {
    refreshFeatures,
    setAttachmentEnabled
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
