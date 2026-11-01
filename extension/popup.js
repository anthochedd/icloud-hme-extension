/**
 * iCloud Hide-My-Email v3 - Chrome Extension Popup Logic
 */

let config = {
  server_url: IHME_DEFAULT_SERVER_URL,
  api_key: '',
};

let allEmails = [];
let currentView = 'claim'; // 'claim', 'search', 'settings'

let pendingDeleteAnonId = null;
let pendingDeleteEmail = null;

document.addEventListener('DOMContentLoaded', async () => {
  // Load settings from sync storage
  const stored = await chrome.storage.local.get(['server_url', 'api_key']);
  if (stored.server_url) {
    config.server_url = stored.server_url.replace(/\/+$/, '');
  } else {
    await chrome.storage.local.set({ server_url: config.server_url });
  }
  if (stored.api_key) {
    config.api_key = stored.api_key;
  }

  // Load cached emails from local storage to show account counts and search results before fetching updates
  const localCache = await chrome.storage.local.get(['all_emails_cache']);
  if (localCache.all_emails_cache && Array.isArray(localCache.all_emails_cache)) {
    allEmails = localCache.all_emails_cache.filter((e) => !isPoolEmail(e.label) && e.isActive !== false);
    updateAccCount(allEmails.length);
  }

  // Bind Header Controls
  const searchBtn = document.getElementById('search-btn');
  const backSearchBtn = document.getElementById('back-search-btn');
  const gearBtn = document.getElementById('gear-btn');

  searchBtn.addEventListener('click', () => {
    switchView(currentView === 'search' ? 'claim' : 'search');
  });

  backSearchBtn.addEventListener('click', () => {
    switchView('claim');
  });

  gearBtn.addEventListener('click', () => {
    switchView(currentView === 'settings' ? 'claim' : 'settings');
  });

  const openWebBtn = document.getElementById('open-web-btn');
  if (openWebBtn) {
    openWebBtn.addEventListener('click', () => {
      const url = config.server_url || IHME_DEFAULT_SERVER_URL;
      chrome.tabs.create({ url: url });
    });
  }

  // Init Modals, Settings, Claim & Search
  initDeleteModal();
  initSettingsForm();
  initClaimForm();
  initSearch();

  // If not configured, open settings view directly inline
  if (!config.api_key) {
    switchView('settings');
    showSettingsStatus('Please enter your server URL and API key.', 'error');
  } else {
    switchView('claim');
    detectCurrentTab();
    checkStatus();
    loadHistory();
    fetchAllEmailsCache();
  }
});

// ----------------------------------------------------------------- View Switching
function switchView(viewName) {
  currentView = viewName;
  const claimView = document.getElementById('claim-view');
  const searchView = document.getElementById('search-view');
  const settingsView = document.getElementById('settings-view');
  const backBtn = document.getElementById('back-search-btn');
  const searchBtn = document.getElementById('search-btn');
  const gearBtn = document.getElementById('gear-btn');

  claimView.classList.toggle('hidden', viewName !== 'claim');
  searchView.classList.toggle('hidden', viewName !== 'search');
  settingsView.classList.toggle('hidden', viewName !== 'settings');

  // Back button next to the search icon is visible in search or settings view
  backBtn.classList.toggle('hidden', viewName === 'claim');

  // Active highlights
  searchBtn.classList.toggle('active', viewName === 'search');
  gearBtn.classList.toggle('active', viewName === 'settings');

  if (viewName === 'search') {
    const searchInput = document.getElementById('search-input');
    searchInput.value = '';
    renderSearchResults('');
    searchInput.focus();
  } else if (viewName === 'settings') {
    document.getElementById('settings-server-url').value = config.server_url;
    document.getElementById('settings-api-key').value = config.api_key;
    hideSettingsStatus();
  } else if (viewName === 'claim') {
    detectCurrentTab();
  }
}

// ----------------------------------------------------------------- Domain Detection
function detectCurrentTab() {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || tabs.length === 0 || !tabs[0].url) {
      setDomain('');
      return;
    }
    try {
      const url = new URL(tabs[0].url);
      if (url.protocol.startsWith('http')) {
        let host = url.hostname.replace(/^www\./, '');
        setDomain(host);
      } else {
        setDomain('');
      }
    } catch {
      setDomain('');
    }
  });
}

function setDomain(domain) {
  const labelInput = document.getElementById('label-input');
  if (labelInput) labelInput.value = domain || '';
}

// ----------------------------------------------------------------- Status & Account Count
function updateAccCount(count) {
  const el = document.getElementById('acc-count-val');
  if (el && typeof count === 'number') {
    el.textContent = count;
  }
}

async function checkStatus() {
  const dot = document.getElementById('pool-dot');
  const text = document.getElementById('pool-text');

  if (!config.api_key) {
    text.textContent = 'Config';
    dot.className = 'dot warn';
    return;
  }

  try {
    const res = await fetch(`${config.server_url}/api/extension/status`, {
      headers: { 'X-API-Key': config.api_key },
    });

    if (!res.ok) {
      if (res.status === 401) {
        text.textContent = 'Invalid key';
        dot.className = 'dot err';
      } else {
        text.textContent = 'Error';
        dot.className = 'dot warn';
      }
      return;
    }

    const data = await res.json();
    text.textContent = `${data.pool_ready}/${data.pool_target}`;
    dot.className = data.pool_ready >= 1 ? 'dot' : 'dot warn';

    if (typeof data.total_emails === 'number') {
      updateAccCount(data.total_emails);
    }
  } catch (err) {
    text.textContent = 'Offline';
    dot.className = 'dot err';
  }
}

// ----------------------------------------------------------------- Claim Email
function initClaimForm() {
  const claimForm = document.getElementById('claim-form');
  claimForm.addEventListener('submit', handleClaim);

  const copyBtn = document.getElementById('copy-result-btn');
  const resultEmailEl = document.getElementById('result-email');

  copyBtn.addEventListener('click', (e) => {
    const email = resultEmailEl.textContent;
    copyEmail(email, e.currentTarget);
  });

  if (resultEmailEl) {
    resultEmailEl.style.cursor = 'pointer';
    resultEmailEl.title = 'Click to copy to clipboard';
    resultEmailEl.addEventListener('click', () => {
      const email = resultEmailEl.textContent;
      copyEmail(email, copyBtn);
    });
  }

  const pwdBtn = document.getElementById('pwd-result-btn');
  if (pwdBtn) {
    pwdBtn.addEventListener('click', (e) => {
      const email = resultEmailEl.textContent;
      if (email && email !== '…') {
        handleExtensionPasswordClick(email, '', e.currentTarget);
      }
    });
  }
}

async function handleClaim(e) {
  e.preventDefault();
  const labelInput = document.getElementById('label-input');
  const claimBtn = document.getElementById('claim-btn');
  const label = labelInput.value.trim() || 'Chrome Extension';

  claimBtn.disabled = true;
  claimBtn.querySelector('span').textContent = 'Claiming…';

  try {
    const res = await fetch(`${config.server_url}/api/extension/claim`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': config.api_key,
      },
      body: JSON.stringify({
        label: label,
        note: 'Claimed via Chrome Extension',
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      alert(data.detail || data.message || 'Error claiming address');
      return;
    }

    // Success: display result
    const resultCard = document.getElementById('result-card');
    document.getElementById('result-email').textContent = data.email;
    document.getElementById('remaining-pool').textContent = `${data.remaining_pool} in reserve`;
    resultCard.classList.remove('hidden');

    // Auto copy to clipboard with icon feedback
    copyEmail(data.email, document.getElementById('copy-result-btn'));

    // Save to local extension history
    saveToHistory(label, data.email, data.anonymousId || '');

    // Refresh status indicator and background cache
    checkStatus();
    fetchAllEmailsCache();
  } catch (err) {
    alert(`Connection error: ${err.message}`);
  } finally {
    claimBtn.disabled = false;
    claimBtn.querySelector('span').textContent = 'Claim';
  }
}

// ----------------------------------------------------------------- Clipboard Helper
function copyEmail(email, buttonEl = null) {
  if (!email) return;

  const doFeedback = () => {
    if (buttonEl) {
      buttonEl.classList.add('copied');
      const origHtml = buttonEl.innerHTML;
      buttonEl.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      `;
      setTimeout(() => {
        buttonEl.innerHTML = origHtml;
        buttonEl.classList.remove('copied');
      }, 1500);
    }
  };

  if (navigator.clipboard) {
    navigator.clipboard.writeText(email).then(doFeedback).catch(() => {
      fallbackCopy(email);
      doFeedback();
    });
  } else {
    fallbackCopy(email);
    doFeedback();
  }
}

function fallbackCopy(text) {
  const t = document.createElement('textarea');
  t.value = text;
  t.style.position = 'fixed';
  t.style.left = '-9999px';
  document.body.appendChild(t);
  t.select();
  document.execCommand('copy');
  document.body.removeChild(t);
}

// ----------------------------------------------------------------- Action Buttons Markup & Events
function renderItemActions(anonymousId, email) {
  const anon = escapeHtml(anonymousId || '');
  const mail = escapeHtml(email || '');
  return `
    <div class="item-actions">
      <button type="button" class="action-icon-btn pwd-btn" data-anon-id="${anon}" data-mail="${mail}" title="Password (View or Generate)" aria-label="Password">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="7.5" cy="15.5" r="5.5"></circle>
          <path d="m21 2-9.6 9.6"></path>
          <path d="m15.5 7.5 3 3L22 7l-3-3"></path>
        </svg>
      </button>
      <button type="button" class="action-icon-btn copy-btn" data-copy-val="${mail}" title="Copy" aria-label="Copy">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>
      </button>
      <button type="button" class="action-icon-btn deactivate-btn" data-anon-id="${anon}" data-mail="${mail}" title="Deactivate" aria-label="Deactivate">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
      </button>
      <button type="button" class="action-icon-btn delete-btn" data-anon-id="${anon}" data-mail="${mail}" title="Permanently delete" aria-label="Permanently delete">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>
  `;
}

function bindItemActionButtons(container) {
  // Password Key button
  container.querySelectorAll('.pwd-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const mail = btn.getAttribute('data-mail');
      const anonId = btn.getAttribute('data-anon-id');
      handleExtensionPasswordClick(mail, anonId, btn);
    });
  });

  // Copy
  container.querySelectorAll('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const mail = btn.getAttribute('data-copy-val');
      copyEmail(mail, btn);
    });
  });

  // Deactivate (Grey trash icon)
  container.querySelectorAll('.deactivate-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const anonId = btn.getAttribute('data-anon-id');
      const mail = btn.getAttribute('data-mail');
      executeDeactivate(anonId, mail, btn);
    });
  });

  // Permanent Delete (Red cross icon)
  container.querySelectorAll('.delete-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const anonId = btn.getAttribute('data-anon-id');
      const mail = btn.getAttribute('data-mail');
      promptDeleteConfirmation(anonId, mail);
    });
  });
}

async function handleExtensionPasswordClick(mail, anonId, btn) {
  if (!config.api_key) {
    alert('Please set your API key in extension settings.');
    return;
  }
  if (btn && btn.disabled) return;
  if (btn) btn.disabled = true;
  const origHtml = btn ? btn.innerHTML : '';
  if (btn) btn.innerHTML = '…';
  try {
    const res = await fetch(`${config.server_url}/api/extension/password`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': config.api_key,
      },
      body: JSON.stringify({ email: mail, action: 'check' }),
    });
    const data = await res.json();
    let pwd = data.password;

    if (!data.has_password || !pwd) {
      const genRes = await fetch(`${config.server_url}/api/extension/password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': config.api_key,
        },
        body: JSON.stringify({ email: mail, action: 'generate_new' }),
      });
      const genData = await genRes.json();
      pwd = genData.password;
    }

    if (pwd) {
      copyEmail(pwd);
      promptPasswordDisplay(mail, pwd);
    }
  } catch (err) {
    alert(`Password error: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

function promptPasswordDisplay(email, password) {
  const existing = document.getElementById('popup-pwd-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'popup-pwd-modal';
  modal.style.cssText = `
    position: fixed; inset: 0; background: rgba(0,0,0,0.76);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    display: flex; align-items: center; justify-content: center; z-index: 9999;
    padding: 16px;
  `;
  modal.innerHTML = `
    <div style="background: #0d0f15; border: 1px solid rgba(255,255,255,0.1); border-top: 1px solid rgba(255,255,255,0.2); border-radius: 12px; padding: 18px; width: 100%; max-width: 280px; box-shadow: 0 16px 40px rgba(0,0,0,0.75);">
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="7.5" cy="15.5" r="5.5"></circle>
          <path d="m21 2-9.6 9.6"></path>
          <path d="m15.5 7.5 3 3L22 7l-3-3"></path>
        </svg>
        <strong style="font-size: 14px; color: #ffffff;">Password</strong>
      </div>
      <div style="font-size: 11.5px; color: #9ca3af; margin-bottom: 12px; word-break: break-all;">${escapeHtml(email)}</div>
      <div style="display: flex; align-items: center; gap: 6px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); padding: 8px 10px; border-radius: 6px; margin-bottom: 14px;">
        <code style="font-family: monospace; font-size: 13px; font-weight: 600; color: #ffffff; flex: 1; word-break: break-all;">${escapeHtml(password)}</code>
      </div>
      <div style="display: flex; justify-content: center; width: 100%;">
        <button id="popup-copy-pwd-btn" class="btn primary-btn btn-block">
          <span>Copy &amp; Close</span>
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  modal.querySelector('#popup-copy-pwd-btn').addEventListener('click', () => {
    copyEmail(password);
    modal.remove();
  });
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });
}

// ----------------------------------------------------------------- Deactivation
async function executeDeactivate(anonId, email, btnEl) {
  // If anonId missing, find in allEmails
  let targetId = anonId;
  if (!targetId && email) {
    const found = allEmails.find((e) => e.hme === email);
    if (found) targetId = found.anonymousId;
  }

  if (!targetId) {
    alert('Unable to locate the identifier for this address.');
    return;
  }

  if (btnEl) btnEl.style.opacity = '0.4';

  try {
    const res = await fetch(`${config.server_url}/api/emails/delete`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': config.api_key,
      },
      body: JSON.stringify({
        anonymousIds: [targetId],
        mode: 'deactivate',
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || 'Error deactivating address.');
      if (btnEl) btnEl.style.opacity = '1';
      return;
    }

    // Remove from local cache and history
    allEmails = allEmails.filter((e) => (targetId ? e.anonymousId !== targetId : true) && e.hme !== email);
    await chrome.storage.local.set({ all_emails_cache: allEmails });
    updateAccCount(allEmails.length);

    const stored = await chrome.storage.local.get(['claim_history']);
    if (stored.claim_history) {
      const updated = stored.claim_history.filter((h) => h.email !== email);
      await chrome.storage.local.set({ claim_history: updated });
    }

    const searchInput = document.getElementById('search-input');
    renderSearchResults(searchInput ? searchInput.value.trim().toLowerCase() : '');
    loadHistory();
    checkStatus();
    fetchAllEmailsCache();
  } catch (err) {
    alert(`Connection error: ${err.message}`);
    if (btnEl) btnEl.style.opacity = '1';
  }
}

// ----------------------------------------------------------------- Delete Modal Logic
function initDeleteModal() {
  const modal = document.getElementById('confirm-modal');
  const cancelBtn = document.getElementById('modal-cancel-btn');
  const confirmBtn = document.getElementById('modal-confirm-btn');

  cancelBtn.addEventListener('click', closeDeleteModal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeDeleteModal();
  });

  confirmBtn.addEventListener('click', executePermanentDelete);
}

function promptDeleteConfirmation(anonId, email) {
  let targetId = anonId;
  if (!targetId && email) {
    const found = allEmails.find((e) => e.hme === email);
    if (found) targetId = found.anonymousId;
  }

  pendingDeleteAnonId = targetId;
  pendingDeleteEmail = email;

  const targetEl = document.getElementById('modal-email-target');
  targetEl.textContent = email || 'this address';

  const modal = document.getElementById('confirm-modal');
  modal.classList.remove('hidden');
}

function closeDeleteModal() {
  const modal = document.getElementById('confirm-modal');
  modal.classList.add('hidden');
  pendingDeleteAnonId = null;
  pendingDeleteEmail = null;
}

async function executePermanentDelete() {
  if (!pendingDeleteEmail && !pendingDeleteAnonId) return;

  const anonId = pendingDeleteAnonId;
  const email = pendingDeleteEmail;

  // 1. Remove from the UI before the server responds
  const backupItem = allEmails.find((e) => (anonId ? e.anonymousId === anonId : false) || e.hme === email);
  allEmails = allEmails.filter((e) => (anonId ? e.anonymousId !== anonId : true) && e.hme !== email);
  await chrome.storage.local.set({ all_emails_cache: allEmails });
  updateAccCount(allEmails.length);

  const stored = await chrome.storage.local.get(['claim_history']);
  if (stored.claim_history) {
    const updated = stored.claim_history.filter((h) => h.email !== email);
    await chrome.storage.local.set({ claim_history: updated });
  }

  closeDeleteModal();
  const searchInput = document.getElementById('search-input');
  renderSearchResults(searchInput ? searchInput.value.trim().toLowerCase() : '');
  loadHistory();

  // 2. Background async execution
  try {
    const res = await fetch(`${config.server_url}/api/emails/delete`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': config.api_key,
      },
      body: JSON.stringify({
        anonymousIds: anonId ? [anonId] : [],
        mode: 'both',
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`iCloud error for ${email}: ${err.detail || 'Failed to permanently delete.'}`);
      // Rollback
      if (backupItem) {
        allEmails.unshift(backupItem);
        await chrome.storage.local.set({ all_emails_cache: allEmails });
        updateAccCount(allEmails.length);
        renderSearchResults(searchInput ? searchInput.value.trim().toLowerCase() : '');
      }
      return;
    }

    checkStatus();
    fetchAllEmailsCache();
  } catch (err) {
    alert(`Network error for ${email}: ${err.message}`);
    if (backupItem) {
      allEmails.unshift(backupItem);
      await chrome.storage.local.set({ all_emails_cache: allEmails });
      updateAccCount(allEmails.length);
      renderSearchResults(searchInput ? searchInput.value.trim().toLowerCase() : '');
    }
  }
}

// ----------------------------------------------------------------- Recently Claimed
async function saveToHistory(label, email, anonymousId = '') {
  const stored = await chrome.storage.local.get(['claim_history']);
  let history = stored.claim_history || [];
  history.unshift({ label, email, anonymousId, time: Date.now() });
  history = history.slice(0, 10);
  await chrome.storage.local.set({ claim_history: history });
  loadHistory();
}

function isPoolEmail(labelOrObj) {
  if (!labelOrObj) return false;
  const l = typeof labelOrObj === 'object' ? (labelOrObj.label || '') : String(labelOrObj);
  return /^pool[\s_-]?\d+$/i.test(l.trim()) || /^\[(?:reserve|pool)\]/i.test(l.trim());
}

async function loadHistory() {
  const stored = await chrome.storage.local.get(['claim_history', 'all_emails_cache']);
  const activeCache = (stored.all_emails_cache && stored.all_emails_cache.length > 0)
    ? stored.all_emails_cache
    : (allEmails || []);

  const activeEmailsSet = new Set(
    activeCache
      .filter((e) => e.isActive !== false && !isPoolEmail(e))
      .map((e) => (e.hme || '').toLowerCase())
  );

  const rawHistory = stored.claim_history || [];
  // Filter out reserve pool emails and emails that were deleted
  const history = rawHistory.filter((item) => {
    if (isPoolEmail(item.label)) return false;
    if (activeEmailsSet.size > 0 && !activeEmailsSet.has((item.email || '').toLowerCase())) {
      return false; // Email deleted
    }
    return true;
  });

  // Keep browser storage clean
  if (history.length !== rawHistory.length) {
    await chrome.storage.local.set({ claim_history: history });
  }

  const list = document.getElementById('history-list');
  if (history.length === 0) {
    list.innerHTML = '<div class="history-empty">No recent addresses</div>';
    return;
  }

  list.innerHTML = history.map((item) => `
    <div class="history-item">
      <div class="history-item-content">
        <span class="history-item-label">${escapeHtml(item.label)}</span>
        <span class="history-item-mail" title="Click to copy">${escapeHtml(item.email)}</span>
      </div>
      ${renderItemActions(item.anonymousId, item.email)}
    </div>
  `).join('');

  bindItemActionButtons(list);

  list.querySelectorAll('.history-item-mail').forEach((span) => {
    span.addEventListener('click', () => {
      copyEmail(span.textContent);
    });
  });
}

// ----------------------------------------------------------------- Search View
function initSearch() {
  const searchInput = document.getElementById('search-input');
  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.trim().toLowerCase();
    renderSearchResults(query);
  });
}

async function fetchAllEmailsCache() {
  if (!config.api_key) return;
  try {
    const res = await fetch(`${config.server_url}/api/extension/emails`, {
      headers: { 'X-API-Key': config.api_key },
    });
    if (res.ok) {
      const data = await res.json();
      allEmails = (data.emails || []).filter((e) => !isPoolEmail(e.label) && e.isActive !== false);
      await chrome.storage.local.set({ all_emails_cache: allEmails });
      updateAccCount(allEmails.length);
      const searchView = document.getElementById('search-view');
      if (searchView && !searchView.classList.contains('hidden')) {
        const query = document.getElementById('search-input').value.trim().toLowerCase();
        renderSearchResults(query);
      }
    }
  } catch (err) {
    console.log('Cache fetch info:', err);
  }
}

function renderSearchResults(query = '') {
  const list = document.getElementById('search-results-list');
  const filtered = allEmails.filter((item) => {
    if (isPoolEmail(item.label)) return false;
    if (item.isActive === false) return false;
    if (!query) return true;
    const label = (item.label || '').toLowerCase();
    const mail = (item.hme || '').toLowerCase();
    return label.includes(query) || mail.includes(query);
  });

  if (filtered.length === 0) {
    list.innerHTML = `<div class="history-empty">${query ? 'No addresses found' : 'No addresses in account'}</div>`;
    return;
  }

  list.innerHTML = filtered.map((item) => `
    <div class="search-email-card">
      <div class="search-email-info">
        <span class="search-email-label">${escapeHtml(item.label || 'Unnamed')}</span>
        <span class="search-email-address">${escapeHtml(item.hme)}</span>
      </div>
      ${renderItemActions(item.anonymousId, item.hme)}
    </div>
  `).join('');

  bindItemActionButtons(list);

  list.querySelectorAll('.search-email-address').forEach((span) => {
    span.addEventListener('click', () => {
      copyEmail(span.textContent);
    });
  });
}

// ----------------------------------------------------------------- Inline Settings Logic
function initSettingsForm() {
  const form = document.getElementById('settings-form');
  const testBtn = document.getElementById('settings-test-btn');
  const urlInput = document.getElementById('settings-server-url');
  const keyInput = document.getElementById('settings-api-key');

  testBtn.addEventListener('click', async () => {
    const testUrl = urlInput.value.trim().replace(/\/+$/, '');
    const testKey = keyInput.value.trim();

    if (!testUrl) {
      showSettingsStatus('Please enter a server URL.', 'error');
      return;
    }
    if (!testKey) {
      showSettingsStatus('Please enter your API key.', 'error');
      return;
    }

    showSettingsStatus('Testing connection…', 'info');

    try {
      const res = await fetch(`${testUrl}/api/extension/status`, {
        headers: { 'X-API-Key': testKey },
      });

      if (!res.ok) {
        if (res.status === 401) {
          showSettingsStatus('Error 401: Invalid or revoked API key.', 'error');
        } else {
          showSettingsStatus(`HTTP Error ${res.status}`, 'error');
        }
        return;
      }

      const data = await res.json();
      showSettingsStatus(`✓ Connection established! Reserve: ${data.pool_ready}/${data.pool_target} ready.`, 'success');
    } catch (err) {
      showSettingsStatus(`Connection failed: ${err.message}. Check URL and network/Tailscale.`, 'error');
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const saveUrl = urlInput.value.trim().replace(/\/+$/, '');
    const saveKey = keyInput.value.trim();

    await chrome.storage.local.set({ server_url: saveUrl, api_key: saveKey });
    config.server_url = saveUrl;
    config.api_key = saveKey;

    showSettingsStatus('✓ Settings saved successfully!', 'success');

    // Trigger state checks
    checkStatus();
    loadHistory();
    fetchAllEmailsCache();

    // Auto-return to claim view after a short delay
    setTimeout(() => {
      switchView('claim');
    }, 700);
  });
}

function showSettingsStatus(msg, type = 'info') {
  const box = document.getElementById('settings-status-box');
  box.textContent = msg;
  box.className = `settings-status-box ${type}`;
  box.classList.remove('hidden');
}

function hideSettingsStatus() {
  const box = document.getElementById('settings-status-box');
  box.classList.add('hidden');
}

// ----------------------------------------------------------------- String Escaper
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
