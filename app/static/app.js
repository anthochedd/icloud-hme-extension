/**
 * iCloud Hide-My-Email Manager v3 - Frontend Application
 * Vercel Design System & Minimalist Engineering Interface
 */

// Application State
const state = {
  auth: { initialized: false, authenticated: false },
  account: null,
  pool: null,
  emails: [],
  selectedEmailIds: new Set(),
  activeFilter: 'all',
  searchQuery: '',
  pollTimer: null,
};

// ------------------------------------------------------------- Helpers & API
async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const res = await fetch(path, { credentials: 'include', ...options, headers });
  if (res.status === 401) {
    showAuthView(state.auth.initialized ? 'login' : 'setup');
    throw new Error('Not authenticated');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || `HTTP ${res.status}`);
  }
  return data;
}

function showToast(msg, duration = 3000) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.remove('hidden');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.add('hidden'), duration);
}

function formatDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts > 1e11 ? ts : ts * 1000);
  return d.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function inlineString(value) {
  return escapeHtml(JSON.stringify(String(value ?? '')));
}

function copyToClipboard(text, labelOrBtn = 'Copied to clipboard') {
  if (!text) return;
  let label = 'Copied to clipboard';
  let buttonEl = null;

  if (typeof labelOrBtn === 'string') {
    label = labelOrBtn;
  } else if (labelOrBtn && labelOrBtn.nodeType) {
    buttonEl = labelOrBtn;
  }

  const doFeedback = () => {
    showToast(label);
    if (buttonEl && buttonEl.tagName === 'BUTTON') {
      const origHtml = buttonEl.innerHTML;
      buttonEl.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      `;
      setTimeout(() => { buttonEl.innerHTML = origHtml; }, 1500);
    }
  };

  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(doFeedback).catch(() => {
      fallbackCopyText(text, label);
    });
  } else {
    fallbackCopyText(text, label);
  }
}

function fallbackCopyText(text, label) {
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.left = '-999999px';
  textArea.style.top = '-999999px';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    const ok = document.execCommand('copy');
    if (ok) showToast(label);
  } catch (err) {
    console.error('Fallback copy error:', err);
  }
  document.body.removeChild(textArea);
}

// ------------------------------------------------------------- Centered Dialog Modals (Confirm & Alert)
function confirmDialog({
  title = 'Confirmation',
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  isDanger = true,
}) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-modal-title');
    const msgEl = document.getElementById('confirm-modal-message');
    const okBtn = document.getElementById('confirm-modal-ok');
    const cancelBtn = document.getElementById('confirm-modal-cancel');
    const iconEl = document.getElementById('confirm-modal-icon');

    titleEl.textContent = title;
    msgEl.textContent = message;
    okBtn.textContent = confirmText;
    cancelBtn.textContent = cancelText;

    cancelBtn.style.display = 'inline-flex';
    if (isDanger) {
      okBtn.className = 'btn btn-danger';
      if (iconEl) {
        iconEl.style.background = 'rgba(238, 0, 0, 0.1)';
        iconEl.style.color = 'var(--red)';
      }
    } else {
      okBtn.className = 'btn btn-primary';
      if (iconEl) {
        iconEl.style.background = 'rgba(0, 112, 243, 0.1)';
        iconEl.style.color = 'var(--blue)';
      }
    }

    const cleanup = () => {
      modal.classList.add('hidden');
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      document.removeEventListener('keydown', onKeyDown);
      modal.removeEventListener('click', onBackdrop);
    };

    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onCancel();
    };
    const onBackdrop = (e) => {
      if (e.target === modal) onCancel();
    };

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    document.addEventListener('keydown', onKeyDown);
    modal.addEventListener('click', onBackdrop);

    modal.classList.remove('hidden');
    okBtn.focus();
  });
}

function alertDialog({
  title = 'Information',
  message,
  buttonText = 'Got it',
  isError = false,
}) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-modal-title');
    const msgEl = document.getElementById('confirm-modal-message');
    const okBtn = document.getElementById('confirm-modal-ok');
    const cancelBtn = document.getElementById('confirm-modal-cancel');
    const iconEl = document.getElementById('confirm-modal-icon');

    titleEl.textContent = title;
    msgEl.textContent = message;
    okBtn.textContent = buttonText;
    okBtn.className = isError ? 'btn btn-danger' : 'btn btn-primary';
    cancelBtn.style.display = 'none';

    if (iconEl) {
      if (isError) {
        iconEl.style.background = 'rgba(238, 0, 0, 0.1)';
        iconEl.style.color = 'var(--red)';
      } else {
        iconEl.style.background = 'rgba(0, 112, 243, 0.1)';
        iconEl.style.color = 'var(--blue)';
      }
    }

    const cleanup = () => {
      modal.classList.add('hidden');
      cancelBtn.style.display = 'inline-flex';
      okBtn.removeEventListener('click', onOk);
      document.removeEventListener('keydown', onKeyDown);
      modal.removeEventListener('click', onBackdrop);
    };

    const onOk = () => { cleanup(); resolve(); };
    const onKeyDown = (e) => {
      if (e.key === 'Escape' || e.key === 'Enter') onOk();
    };
    const onBackdrop = (e) => {
      if (e.target === modal) onOk();
    };

    okBtn.addEventListener('click', onOk);
    document.addEventListener('keydown', onKeyDown);
    modal.addEventListener('click', onBackdrop);

    modal.classList.remove('hidden');
    okBtn.focus();
  });
}

// ------------------------------------------------------------- Theme Management
function initTheme() {
  const saved = localStorage.getItem('ihme-theme') || 'dark';
  setTheme(saved);

  const toggleBtn = document.getElementById('theme-toggle-btn');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      const next = current === 'light' ? 'dark' : 'light';
      setTheme(next);
    });
  }
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('ihme-theme', theme);
  const icon = document.getElementById('theme-icon');
  if (icon) {
    if (theme === 'dark') {
      // Moon icon
      icon.innerHTML = '<path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>';
    } else {
      // Sun icon
      icon.innerHTML = '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>';
    }
  }
}

// ------------------------------------------------------------- Auth Flow
async function checkAuthStatus() {
  try {
    const res = await fetch('/api/auth/status', { credentials: 'include' });
    const data = await res.json();
    state.auth = data;

    if (!data.initialized) {
      showAuthView('setup');
    } else if (!data.authenticated) {
      showAuthView('login');
    } else {
      showAppView();
    }
  } catch (e) {
    showAuthView('login');
  }
}

function showAuthView(mode) {
  document.getElementById('onboarding').classList.add('hidden');
  document.getElementById('auth-password').minLength = mode === 'setup' ? 4 : 1;
  document.getElementById('app-container').classList.add('hidden');
  document.getElementById('auth-container').classList.remove('hidden');

  const title = document.getElementById('auth-title');
  const subtitle = document.getElementById('auth-subtitle');
  const label = document.getElementById('auth-label');
  const btn = document.getElementById('auth-submit-btn');

  if (mode === 'setup') {
    title.textContent = 'Setup iCloud HME';
    subtitle.textContent = 'Create your administrator master password to begin';
    label.textContent = 'Set Master Password';
    btn.querySelector('span').textContent = 'Create Password & Start';
  } else {
    title.textContent = 'Log in to iCloud HME';
    subtitle.textContent = 'Enter your master password to access your infrastructure';
    label.textContent = 'Master Password';
    btn.querySelector('span').textContent = 'Log In';
  }
}

function showAppView() {
  if (!state.auth.onboarding_complete) { showOnboarding(); return; }
  document.getElementById('reconfigure-btn').classList.toggle('hidden', Boolean(state.auth.is_connected));
  document.getElementById('auth-container').classList.add('hidden');
  document.getElementById('app-container').classList.remove('hidden');
  loadAllData();
  startPolling();
}

// Auth Form Submit
document.getElementById('auth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pwdInput = document.getElementById('auth-password');
  const errBox = document.getElementById('auth-error');
  errBox.classList.add('hidden');

  const endpoint = state.auth.initialized ? '/api/auth/login' : '/api/auth/setup';
  try {
    await api(endpoint, {
      method: 'POST',
      body: JSON.stringify({ password: pwdInput.value }),
    });
    pwdInput.value = '';
    state.auth.authenticated = true;
    state.auth.initialized = true;
    await checkAuthStatus();
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.remove('hidden');
  }
});

// Logout
document.getElementById('logout-btn').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' });
  state.auth.authenticated = false;
  clearInterval(state.pollTimer);
  showAuthView('login');
});

// ------------------------------------------------------------- Navigation
document.querySelectorAll('.v-tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.v-tab').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach((sec) => sec.classList.add('hidden'));

    btn.classList.add('active');
    const tabId = btn.getAttribute('data-tab');
    document.getElementById(tabId).classList.remove('hidden');

    // Instantly refresh emails list when switching to the addresses tab
    if (tabId === 'tab-emails') {
      fetchEmails();
    }
  });
});

// ------------------------------------------------------------- Data Loading
async function loadAllData() {
  await Promise.all([
    fetchAccount(),
    fetchPool(),
    fetchEmails(),
    fetchSettings(),
    fetchKeys(),
  ]);
}

let pollCycle = 0;
function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    if (!document.hidden) {
      pollCycle++;
      const tasks = [fetchAccount(true), fetchPool(true)];
      // Automatically keep emails in sync every 12s in background
      if (pollCycle % 3 === 0) {
        tasks.push(fetchEmails());
      }
      await Promise.all(tasks);
    }
  }, 4000);
}

// ------------------------------------------------------------- Account
async function fetchAccount(isBackground = false) {
  try {
    const acc = await api('/api/account');
    state.account = acc;
    renderAccountInfo();
  } catch (e) {
    if (!isBackground) console.error(e);
  }
}

function renderAccountInfo() {
  document.getElementById('reconfigure-btn').classList.toggle('hidden', Boolean(state.account?.is_connected));
  const emailSpan = document.getElementById('account-email');
  const pill = document.getElementById('account-pill');
  const dot = pill.querySelector('.v-status-dot');

  if (state.account && state.account.is_connected && state.account.forward_email) {
    emailSpan.textContent = state.account.forward_email;
    dot.className = 'v-status-dot';
  } else if (state.account && state.account.is_connected) {
    emailSpan.textContent = 'Connected (iCloud)';
    dot.className = 'v-status-dot';
  } else if (state.account && state.account.has_cookies) {
    emailSpan.textContent = 'Session Error / Disconnected';
    dot.className = 'v-status-dot error';
  } else {
    emailSpan.textContent = 'No Cookies Configured';
    dot.className = 'v-status-dot error';
  }

  // Capacity indicators (Overview & Generate tabs)
  if (state.account) {
    const totalCount = state.account.total_emails || 0;
    const poolCount = state.account.pool_emails || 0;
    const activeCount = state.account.active_emails || 0;
    const inactiveCount = state.account.inactive_emails || 0;

    const ovCap = document.getElementById('overview-capacity-num');
    if (ovCap) ovCap.textContent = totalCount;
    const ovSub = document.getElementById('overview-capacity-sub');
    if (ovSub) {
      ovSub.textContent = `${activeCount} active · ${inactiveCount} inactive · ${poolCount} pool reserve`;
    }

    const genCap = document.getElementById('gen-capacity-used');
    if (genCap) genCap.textContent = totalCount;
    const genBreakdown = document.getElementById('gen-capacity-breakdown');
    if (genBreakdown) {
      genBreakdown.textContent = `(${activeCount} active · ${inactiveCount} inactive · ${poolCount} pool reserve · 750 max)`;
    }

    const countInput = document.getElementById('manual-count');
    if (countInput) {
      const remaining = Math.max(0, 750 - totalCount);
      countInput.max = Math.min(50, remaining);
    }
  }

  // Global Alert
  const alertBox = document.getElementById('global-alert');
  if (state.account && !state.account.has_cookies) {
    alertBox.textContent = 'No iCloud session cookies found. Paste your cookies in Settings to connect.';
    alertBox.classList.remove('hidden');
  } else if (state.account && state.account.list_error) {
    alertBox.textContent = `iCloud sync issue: ${state.account.list_error}`;
    alertBox.classList.remove('hidden');
  } else {
    alertBox.classList.add('hidden');
  }
}

// Refresh Session Button
document.getElementById('refresh-global-btn').addEventListener('click', async () => {
  showToast('Refreshing session…');
  await api('/api/account/refresh', { method: 'POST' });
  await loadAllData();
  showToast('Session refreshed');
});

// ------------------------------------------------------------- TAB 1: Pool (Reserve)
async function fetchPool(isBackground = false) {
  try {
    const p = await api('/api/pool');
    if (state.lastPoolCount !== undefined && state.lastPoolCount !== p.ready_count) {
      fetchEmails();
    }
    state.lastPoolCount = p.ready_count;
    state.pool = p;
    renderPoolView();
  } catch (e) {
    if (!isBackground) console.error(e);
  }
}

function renderPoolView() {
  if (!state.pool) return;
  const p = state.pool;

  document.getElementById('nav-pool-count').textContent = `${p.ready_count}/${p.target}`;
  document.getElementById('pool-ready-num').textContent = p.ready_count;
  document.getElementById('pool-hourly-num').textContent = p.hourly_count;

  const dot = document.getElementById('pool-status-dot');
  const text = document.getElementById('pool-status-text');

  if (p.status === 'replenishing') {
    dot.className = 'v-status-dot cooldown';
    text.textContent = p.message || 'Replenishing pool…';
  } else if (p.status === 'cooldown') {
    dot.className = 'v-status-dot cooldown';
    text.textContent = p.message || 'Hourly limit cooldown';
  } else if (p.status === 'error') {
    dot.className = 'v-status-dot error';
    text.textContent = p.message || 'Pool error';
  } else {
    dot.className = 'v-status-dot';
    text.textContent = p.ready_count >= p.target ? 'Ready (10/10)' : (p.message || 'Idle');
  }

  // Render 10 slots
  const grid = document.getElementById('pool-slots-grid');
  grid.innerHTML = '';

  const slotsMap = p.slots || {};
  for (let slotIndex = 1; slotIndex <= (p.target || 10); slotIndex++) {
    const item = slotsMap[String(slotIndex)] || slotsMap[slotIndex];
    const slotDiv = document.createElement('div');
    const slotNum = String(slotIndex).padStart(2, '0');

    if (item) {
      slotDiv.className = 'slot-card ready';
      slotDiv.innerHTML = `
        <div class="slot-top">
          <span class="slot-id">POOL ${slotNum}</span>
          <span class="slot-pill ready">Ready</span>
        </div>
        <div>
          <div class="slot-email-text">${item.hme}</div>
          <div class="slot-label-text">${item.label || `pool${slotIndex}`}</div>
        </div>
        <div class="slot-bottom">
          <span class="slot-date">${formatDate(item.created_at)}</span>
          <button class="btn btn-secondary btn-sm" data-claim-slot="${slotIndex}">Claim</button>
        </div>
      `;
    } else {
      slotDiv.className = 'slot-card empty';
      slotDiv.innerHTML = `
        <div class="slot-top">
          <span class="slot-id">POOL ${slotNum}</span>
          <span class="slot-pill empty">Empty</span>
        </div>
        <div>
          <div class="slot-email-text muted">—</div>
          <div class="slot-label-text muted">${p.status === 'cooldown' ? 'Apple cooldown' : 'Missing (Queued)'}</div>
        </div>
        <div class="slot-bottom">
          <span class="slot-date">—</span>
        </div>
      `;
    }
    grid.appendChild(slotDiv);
  }

  grid.querySelectorAll('[data-claim-slot]').forEach((btn) => {
    btn.addEventListener('click', () => {
      openClaimModal();
    });
  });

  // Claimed History Table
  const historyTbody = document.getElementById('claimed-history-tbody');
  let claimedList = p.recent_claimed || [];

  if (state.emails && state.emails.length > 0) {
    const aliveSet = new Set();
    state.emails.forEach((e) => {
      if (e.hme) aliveSet.add(e.hme.toLowerCase());
      if (e.anonymousId) aliveSet.add(e.anonymousId.toLowerCase());
    });
    claimedList = claimedList.filter((c) => {
      const h = (c.hme || '').toLowerCase();
      const a = (c.anonymousId || '').toLowerCase();
      return (h && aliveSet.has(h)) || (a && aliveSet.has(a));
    });
  }

  if (claimedList.length === 0) {
    historyTbody.innerHTML = '<tr><td colspan="4" class="muted" style="text-align: center; padding: 24px;">No emails claimed yet.</td></tr>';
  } else {
    historyTbody.innerHTML = claimedList.slice().reverse().map((c) => {
      const hme = escapeHtml(c.hme || '');
      const label = escapeHtml(c.label || c.new_label || '—');
      return `
      <tr>
        <td><b>${label}</b></td>
        <td><span class="email-cell">${hme}</span></td>
        <td><span class="mono" style="font-size:12px;">${formatDate(c.claimed_at)}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="copyToClipboard(${inlineString(c.hme)})">Copy</button>
        </td>
      </tr>
    `;
    }).join('');
  }
}

// Pool Actions
document.getElementById('claim-direct-btn').addEventListener('click', () => openClaimModal());
document.getElementById('pool-force-replenish-btn').addEventListener('click', async () => {
  await api('/api/pool/replenish', { method: 'POST' });
  await fetchPool();
  showToast('Pool replenishment triggered');
});

function openClaimModal() {
  document.getElementById('claim-label').value = '';
  document.getElementById('claim-note').value = '';
  document.getElementById('claim-modal').classList.remove('hidden');
  document.getElementById('claim-label').focus();
}

document.getElementById('claim-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const label = document.getElementById('claim-label').value.trim();
  const note = document.getElementById('claim-note').value.trim();

  try {
    const res = await api('/api/pool/claim', {
      method: 'POST',
      body: JSON.stringify({ label, note }),
    });
    document.getElementById('claim-modal').classList.add('hidden');
    copyToClipboard(res.email, `Claimed & copied: ${res.email}`);
    await Promise.all([fetchPool(), fetchEmails()]);
  } catch (err) {
    alertDialog({ title: 'Claim Failed', message: err.message, isError: true });
  }
});

// ------------------------------------------------------------- TAB 2: Emails Listing
async function fetchEmails() {
  try {
    const data = await api('/api/emails');
    state.emails = data.emails || [];
    renderEmailsTable();
  } catch (e) {
    console.error('Error fetching emails:', e);
  }
}

function isPoolEmail(e) {
  if (!e || !e.label) return false;
  const l = e.label.trim();
  return /^pool[\s_-]?\d+$/i.test(l) || /^\[(?:reserve|pool)\]/i.test(l);
}

function renderEmailsTable() {
  const tbody = document.getElementById('emails-tbody');
  const q = state.searchQuery.toLowerCase();

  const filtered = state.emails.filter((e) => {
    const label = (e.label || '').toLowerCase();
    const mail = (e.hme || '').toLowerCase();
    const matchesSearch = !q || label.includes(q) || mail.includes(q);
    if (!matchesSearch) return false;

    const isPool = isPoolEmail(e);

    if (state.activeFilter === 'pool' || state.activeFilter === 'reserve') {
      return isPool;
    }
    if (state.activeFilter === 'active') {
      return e.isActive && !isPool;
    }
    if (state.activeFilter === 'inactive') {
      return !e.isActive && !isPool;
    }
    // Default 'all': excludes pool reserve emails and inactive emails
    return !isPool && e.isActive;
  });

  const normalEmails = state.emails.filter((e) => !isPoolEmail(e));
  const activeEmails = normalEmails.filter((e) => e.isActive);
  const inactiveEmails = normalEmails.filter((e) => !e.isActive);
  const poolEmails = state.emails.filter((e) => isPoolEmail(e));

  const countAllEl = document.getElementById('count-all');
  const countPoolEl = document.getElementById('count-pool');
  const countActiveEl = document.getElementById('count-active');
  const countInactiveEl = document.getElementById('count-inactive');
  const navCountEl = document.getElementById('nav-email-count');

  if (countAllEl) countAllEl.textContent = activeEmails.length;
  if (countPoolEl) countPoolEl.textContent = poolEmails.length;
  if (countActiveEl) countActiveEl.textContent = activeEmails.length;
  if (countInactiveEl) countInactiveEl.textContent = inactiveEmails.length;
  if (navCountEl) navCountEl.textContent = activeEmails.length;

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align: center; padding: 32px;">No addresses found.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map((e) => {
    const isChecked = state.selectedEmailIds.has(e.anonymousId);
    const anon = escapeHtml(e.anonymousId || '');
    const hme = escapeHtml(e.hme || '');
    const label = escapeHtml(e.label || '—');
    const note = e.note ? `<div class="muted" style="font-size:12px;">${escapeHtml(e.note)}</div>` : '';

    return `
      <tr>
        <td>
          <input type="checkbox" class="email-chk" data-anon="${anon}" ${isChecked ? 'checked' : ''} />
        </td>
        <td>
          <b>${label}</b>
          ${note}
        </td>
        <td><span class="email-cell">${hme}</span></td>
        <td>
          <div style="display: inline-flex; align-items: center; gap: 5px;">
            <button type="button" class="table-action-btn copy-btn" onclick="copyPasswordDirect(${inlineString(e.anonymousId)}, ${inlineString(e.hme)}, this)" title="${e.password ? 'Copy password' : 'Generate & copy password'}" aria-label="Copy password">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
            <button type="button" class="table-action-btn regen-btn" onclick="regeneratePasswordDirect(${inlineString(e.anonymousId)}, ${inlineString(e.hme)}, this)" title="${e.password ? 'Regenerate password' : 'Generate password'}" aria-label="Regenerate password">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="23 4 23 10 17 10"></polyline>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
              </svg>
            </button>
          </div>
        </td>
        <td>
          <span class="status-badge ${e.isActive ? 'active' : 'inactive'}">
            ${e.isActive ? 'Active' : 'Inactive'}
          </span>
        </td>
        <td><span class="mono" style="font-size:12px;">${formatDate(e.createTimestamp)}</span></td>
        <td>
          <div class="table-actions">
            <button type="button" class="table-action-btn copy-btn" onclick="copyToClipboard(${inlineString(e.hme)}, this)" title="Copy" aria-label="Copy">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
            <button type="button" class="table-action-btn edit-btn" onclick="openRenameModal(${inlineString(e.anonymousId)})" title="Rename" aria-label="Rename">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
              </svg>
            </button>
            ${e.isActive ? `
            <button type="button" class="table-action-btn deactivate-btn" onclick="deactivateSingleEmail(${inlineString(e.anonymousId)})" title="Deactivate" aria-label="Deactivate">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
            ` : `
            <button type="button" class="table-action-btn activate-btn" onclick="reactivateSingleEmail(${inlineString(e.anonymousId)})" title="Reactivate" aria-label="Reactivate" style="color: var(--green);">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </button>
            `}
            <button type="button" class="table-action-btn delete-btn" onclick="deleteSingleEmail(${inlineString(e.anonymousId)})" title="Permanently delete" aria-label="Permanently delete">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  tbody.querySelectorAll('.email-chk').forEach((chk) => {
    chk.addEventListener('change', () => {
      const anon = chk.getAttribute('data-anon');
      if (chk.checked) state.selectedEmailIds.add(anon);
      else state.selectedEmailIds.delete(anon);
      updateBulkActionBtns();
    });
  });
}

function updateBulkActionBtns() {
  const count = state.selectedEmailIds.size;
  document.querySelectorAll('.selected-count').forEach((el) => {
    el.textContent = count;
  });
  const delBtn = document.getElementById('bulk-delete-btn');
  const actBtn = document.getElementById('bulk-activate-btn');
  const deactBtn = document.getElementById('bulk-deactivate-btn');

  if (count > 0) {
    if (delBtn) delBtn.classList.remove('hidden');
    if (actBtn) actBtn.classList.remove('hidden');
    if (deactBtn) deactBtn.classList.remove('hidden');
  } else {
    if (delBtn) delBtn.classList.add('hidden');
    if (actBtn) actBtn.classList.add('hidden');
    if (deactBtn) deactBtn.classList.add('hidden');
  }
}

// Select All Checkbox
document.getElementById('select-all-emails').addEventListener('change', (e) => {
  const isChecked = e.target.checked;
  document.querySelectorAll('.email-chk').forEach((chk) => {
    chk.checked = isChecked;
    const anon = chk.getAttribute('data-anon');
    if (isChecked) state.selectedEmailIds.add(anon);
    else state.selectedEmailIds.delete(anon);
  });
  updateBulkActionBtns();
});

// Search input
document.getElementById('email-search').addEventListener('input', (e) => {
  state.searchQuery = e.target.value.trim();
  renderEmailsTable();
});

// Filter buttons
document.querySelectorAll('.filter-btn').forEach((pill) => {
  pill.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach((p) => p.classList.remove('active'));
    pill.classList.add('active');
    state.activeFilter = pill.getAttribute('data-filter');
    renderEmailsTable();
  });
});

// ------------------------------------------------------------- Asynchronous Action Queue
const actionQueue = [];
let isProcessingQueue = false;

function enqueueEmailAction(item, mode) {
  const anonId = item.anonymousId;
  const emailAddr = item.hme || item.label || 'this address';

  if (mode === 'both' || mode === 'delete') {
    // 1. Remove from the UI before the server responds
    state.emails = state.emails.filter((e) => e.anonymousId !== anonId);
    state.selectedEmailIds.delete(anonId);
    showToast(`Deleted: ${emailAddr}`);
  } else if (mode === 'deactivate') {
    // 1. Update inactive status before the server responds
    const found = state.emails.find((e) => e.anonymousId === anonId);
    if (found) found.isActive = false;
    showToast(`Deactivated: ${emailAddr}`);
  } else if (mode === 'activate' || mode === 'reactivate') {
    // 1. Update active status before the server responds
    const found = state.emails.find((e) => e.anonymousId === anonId);
    if (found) found.isActive = true;
    showToast(`Activated: ${emailAddr}`);
  }

  // Instantly re-render table and recount badges
  renderEmailsTable();
  updateBulkActionBtns();

  // 2. Enqueue for background execution
  actionQueue.push({ item, anonId, emailAddr, mode });
  processActionQueue();
}

async function processActionQueue() {
  if (isProcessingQueue || actionQueue.length === 0) return;
  isProcessingQueue = true;

  while (actionQueue.length > 0) {
    const task = actionQueue.shift();
    try {
      await api('/api/emails/delete', {
        method: 'POST',
        body: JSON.stringify({ anonymousIds: [task.anonId], mode: task.mode }),
      });
    } catch (err) {
      console.error('Queue action error:', err);
      // Notify user of delayed error even with latency
      const errTitle = task.mode === 'deactivate'
        ? 'Deactivation Failed'
        : (task.mode === 'activate' || task.mode === 'reactivate' ? 'Activation Failed' : 'Deletion Failed');
      alertDialog({
        title: errTitle,
        message: `iCloud error for ${task.emailAddr}: ${err.message}`,
        isError: true,
      });

      // Rollback item in state if needed
      if (!state.emails.some((e) => e.anonymousId === task.anonId)) {
        state.emails.unshift(task.item);
      } else {
        const found = state.emails.find((e) => e.anonymousId === task.anonId);
        if (found) found.isActive = task.item.isActive;
      }
      renderEmailsTable();
    }
  }

  isProcessingQueue = false;

  // Background silent synchronization after all queued actions finish
  try {
    const data = await api('/api/emails');
    if (data && data.emails) {
      const pendingIds = new Set(actionQueue.map((t) => t.anonId));
      state.emails = data.emails.filter((e) => !pendingIds.has(e.anonymousId));
      renderEmailsTable();
    }
  } catch {}
}

// Reactivate single
window.reactivateSingleEmail = function (anonId) {
  const item = state.emails.find((e) => e.anonymousId === anonId);
  if (!item) return;
  enqueueEmailAction(item, 'activate');
};

// Deactivate single
window.deactivateSingleEmail = function (anonId) {
  const item = state.emails.find((e) => e.anonymousId === anonId);
  if (!item) return;
  enqueueEmailAction(item, 'deactivate');
};

// Delete single
window.deleteSingleEmail = async function (anonId) {
  const item = state.emails.find((e) => e.anonymousId === anonId);
  if (!item) return;

  const confirmed = await confirmDialog({
    title: 'Permanently Delete',
    message: 'Permanently delete this Hide-My-Email address?',
    confirmText: 'Delete Permanently',
    isDanger: true,
  });
  if (!confirmed) return;

  // Instant optimistic delete & enqueue
  enqueueEmailAction(item, 'both');
};

// Bulk Activate
const bulkActBtn = document.getElementById('bulk-activate-btn');
if (bulkActBtn) {
  bulkActBtn.addEventListener('click', async () => {
    const ids = Array.from(state.selectedEmailIds);
    if (ids.length === 0) return;
    const items = state.emails.filter((e) => ids.includes(e.anonymousId));
    state.selectedEmailIds.clear();
    for (const item of items) {
      enqueueEmailAction(item, 'activate');
    }
    updateBulkActionBtns();
  });
}

// Bulk Deactivate
const bulkDeactBtn = document.getElementById('bulk-deactivate-btn');
if (bulkDeactBtn) {
  bulkDeactBtn.addEventListener('click', async () => {
    const ids = Array.from(state.selectedEmailIds);
    if (ids.length === 0) return;
    const items = state.emails.filter((e) => ids.includes(e.anonymousId));
    state.selectedEmailIds.clear();
    for (const item of items) {
      enqueueEmailAction(item, 'deactivate');
    }
    updateBulkActionBtns();
  });
}

// Bulk Delete
document.getElementById('bulk-delete-btn').addEventListener('click', async () => {
  const ids = Array.from(state.selectedEmailIds);
  if (ids.length === 0) return;
  const confirmed = await confirmDialog({
    title: 'Permanently Delete',
    message: `Permanently delete these ${ids.length} address${ids.length > 1 ? 'es' : ''}?`,
    confirmText: `Delete (${ids.length})`,
    isDanger: true,
  });
  if (!confirmed) return;

  const itemsToDelete = state.emails.filter((e) => ids.includes(e.anonymousId));
  state.selectedEmailIds.clear();
  for (const item of itemsToDelete) {
    enqueueEmailAction(item, 'both');
  }
  updateBulkActionBtns();
});

// Rename Modal
window.openRenameModal = function (anonId, currentLabel, currentNote) {
  const item = state.emails.find((e) => e.anonymousId === anonId);
  const label = currentLabel !== undefined ? currentLabel : (item ? item.label : '');
  const note = currentNote !== undefined ? currentNote : (item ? item.note : '');
  document.getElementById('rename-anon-id').value = anonId;
  document.getElementById('rename-label-input').value = label || '';
  document.getElementById('rename-note-input').value = note || '';
  document.getElementById('rename-modal').classList.remove('hidden');
  document.getElementById('rename-label-input').focus();
};

document.getElementById('rename-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const anonId = document.getElementById('rename-anon-id').value;
  const label = document.getElementById('rename-label-input').value.trim();
  const note = document.getElementById('rename-note-input').value.trim();

  try {
    await api('/api/emails/update-label', {
      method: 'POST',
      body: JSON.stringify({ anonymousId: anonId, label, note }),
    });
    document.getElementById('rename-modal').classList.add('hidden');
    showToast('Address label updated');
    await fetchEmails();
  } catch (err) {
    alertDialog({ title: 'Update Failed', message: err.message, isError: true });
  }
});

// Password Controllers (Direct 1-Click Copy & Regenerate)

window.copyPasswordDirect = function (anonId, email, btnEl) {
  const found = state.emails.find((e) => e.anonymousId === anonId || e.hme === email);
  if (found && found.password) {
    copyToClipboard(found.password, btnEl);
    showToast('Password copied to clipboard!');
  } else {
    // Generate immediately and copy!
    regeneratePasswordDirect(anonId, email, btnEl);
  }
};

window.regeneratePasswordDirect = async function (anonId, email, btnEl) {
  if (btnEl) {
    btnEl.style.opacity = '0.5';
    btnEl.style.pointerEvents = 'none';
  }
  showToast('Generating password…');
  try {
    const res = await api('/api/passwords/generate', {
      method: 'POST',
      body: JSON.stringify({ email: email, anonymousId: anonId }),
    });
    const pwd = res.password;
    const found = state.emails.find((e) => e.anonymousId === anonId || e.hme === email);
    if (found) found.password = pwd;
    renderEmailsTable();
    copyToClipboard(pwd, btnEl);
    showToast('Password generated & copied to clipboard!');
  } catch (err) {
    alertDialog({ title: 'Password Error', message: err.message, isError: true });
  } finally {
    if (btnEl) {
      btnEl.style.opacity = '1';
      btnEl.style.pointerEvents = 'auto';
    }
  }
};

// ------------------------------------------------------------- TAB 3: Manual Generation
document.getElementById('manual-gen-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const count = parseInt(document.getElementById('manual-count').value, 10);
  const label = document.getElementById('manual-label').value.trim();

  try {
    await api('/api/emails/generate', {
      method: 'POST',
      body: JSON.stringify({ count, label: label || null }),
    });
    showToast('Generation started…');
    pollManualJob();
  } catch (err) {
    alertDialog({ title: 'Generation Failed', message: err.message, isError: true });
  }
});

document.getElementById('stop-manual-btn').addEventListener('click', async () => {
  await api('/api/emails/generate/stop', { method: 'POST' });
  showToast('Stopping generation…');
});

async function pollManualJob() {
  const statusBox = document.getElementById('manual-job-status');
  const startBtn = document.getElementById('start-manual-btn');
  const stopBtn = document.getElementById('stop-manual-btn');

  statusBox.classList.remove('hidden');
  startBtn.classList.add('hidden');
  stopBtn.classList.remove('hidden');

  const check = async () => {
    const titleEl = document.getElementById('manual-job-title');
    const descEl = document.getElementById('manual-job-desc');
    if (job.status === 'error') {
      titleEl.textContent = 'Generation Stopped (Error / Limit)';
      titleEl.style.color = 'var(--accent-red, #ef4444)';
      descEl.style.color = 'var(--accent-red, #ef4444)';
    } else {
      titleEl.textContent = job.status === 'running' ? 'Generation in progress…' : `Status: ${job.status}`;
      titleEl.style.color = '';
      descEl.style.color = '';
    }
    document.getElementById('manual-job-count').textContent = `${job.done || 0}/${job.target || 0}`;
    descEl.textContent = job.message || '';

    if (job.active) {
      setTimeout(check, 3000);
    } else {
      startBtn.classList.remove('hidden');
      stopBtn.classList.add('hidden');
      await fetchEmails();
    }
  };
  check();
}

// ------------------------------------------------------------- TAB 4: Extension & Keys
async function fetchKeys() {
  try {
    const keys = await api('/api/keys');
    const badge = document.getElementById('keys-count-badge');
    if (badge) badge.textContent = keys ? keys.length : 0;
    renderKeysTable(keys);
  } catch (e) {
    console.error('Error fetching keys:', e);
  }
}

function renderKeysTable(keys) {
  const tbody = document.getElementById('keys-tbody');
  if (!keys || keys.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align: center; padding: 24px;">No API keys created yet.</td></tr>';
    return;
  }

  tbody.innerHTML = keys.map((k) => {
    const prefix = k.prefix || '';
    return `
    <tr>
      <td class="key-name-cell"><b>${escapeHtml(k.name)}</b></td>
      <td class="key-token-cell">
        <code class="mono key-token-display" title="${escapeHtml(prefix)}">${escapeHtml(prefix)}</code>
      </td>
      <td class="key-date-cell"><span class="mono" style="font-size:12px;">${formatDate(k.created_at)}</span></td>
      <td class="key-used-cell"><span class="mono" style="font-size:12px;">${k.last_used_at ? formatDate(k.last_used_at) : 'Never'}</span></td>
      <td class="key-actions-cell">
        <div class="key-actions-group">
          <button class="btn btn-danger btn-sm" onclick="deleteApiKey(${inlineString(k.id)})">Revoke</button>
        </div>
      </td>
    </tr>
  `;
  }).join('');


}

window.deleteApiKey = async function (id) {
  const confirmed = await confirmDialog({
    title: 'Revoke API Key',
    message: 'Revoke this API key? Connected devices and extensions using this key will immediately lose access.',
    confirmText: 'Revoke Key',
    isDanger: true,
  });
  if (!confirmed) return;

  try {
    await api(`/api/keys/${id}`, { method: 'DELETE' });
    showToast('API Key revoked');
    await fetchKeys();
  } catch (err) {
    alertDialog({ title: 'Revoke Failed', message: err.message, isError: true });
  }
};

// Use a native attachment link so the browser handles saving the ZIP directly.
document.querySelectorAll('[data-download-extension]').forEach(link => {
  link.addEventListener('click', () => showToast('Preparing extension ZIP...'));
});

document.getElementById('new-key-btn').addEventListener('click', () => {
  document.getElementById('create-key-form').classList.remove('hidden');
  document.getElementById('key-result-box').classList.add('hidden');
  document.getElementById('new-key-name').value = '';
  document.getElementById('new-key-modal').classList.remove('hidden');
  document.getElementById('new-key-name').focus();
});

const createAnotherBtn = document.getElementById('create-another-key-btn');
if (createAnotherBtn) {
  createAnotherBtn.addEventListener('click', () => {
    document.getElementById('create-key-form').classList.remove('hidden');
    document.getElementById('key-result-box').classList.add('hidden');
    document.getElementById('new-key-name').value = '';
    document.getElementById('new-key-name').focus();
  });
}

document.getElementById('create-key-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('new-key-name').value.trim();

  try {
    const res = await api('/api/keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    document.getElementById('create-key-form').classList.add('hidden');
    document.getElementById('key-result-box').classList.remove('hidden');
    document.getElementById('generated-key-text').textContent = res.key;
    showToast(`Key “${name}” created`);
    await fetchKeys();
  } catch (err) {
    alertDialog({ title: 'Creation Failed', message: err.message, isError: true });
  }
});

// Copy delegation helper
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-copy]');
  if (btn) {
    const elId = btn.getAttribute('data-copy');
    const el = document.getElementById(elId);
    if (el) {
      const text = (el.textContent || el.value || '').trim();
      copyToClipboard(text, 'Copied to clipboard');
    }
  }
});

const copyNewKeyBtn = document.getElementById('copy-new-key-btn');
if (copyNewKeyBtn) {
  copyNewKeyBtn.addEventListener('click', () => {
    const text = document.getElementById('generated-key-text').textContent.trim();
    copyToClipboard(text, 'API Key copied to clipboard');
  });
}

// ------------------------------------------------------------- TAB 5: Settings & Cookies
async function fetchSettings() {
  try {
    const data = await api('/api/settings');
    const net = data.network || {};

    const tailscaleEl = document.getElementById('tailscale-url-val');
    if (tailscaleEl) tailscaleEl.textContent = net.tailscale_url || 'Not detected';
    const lanEl = document.getElementById('lan-url-val');
    if (lanEl) lanEl.textContent = net.lan_url || `http://127.0.0.1:${net.port}`;

    const proxyInput = document.getElementById('proxy-input');
    if (proxyInput && data.proxy !== undefined && !proxyInput.value) {
      proxyInput.value = data.proxy || '';
    }
  } catch (e) {
    console.error('Error fetching settings:', e);
  }
}

// Cookies Form
document.getElementById('cookies-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const cookie = document.getElementById('cookies-input').value.trim();
  const proxy = (document.getElementById('proxy-input') ? document.getElementById('proxy-input').value.trim() : '');

  if (!cookie) return alertDialog({ title: 'Input Required', message: 'Please enter your iCloud cookie string.' });

  const btn = document.getElementById('cookies-submit-btn');
  if (btn) btn.disabled = true;

  try {
    await api('/api/account/cookies', {
      method: 'POST',
      body: JSON.stringify({ cookie, proxy: proxy || null }),
    });
    showToast('Cookies saved & session connected ✓');
    document.getElementById('cookies-input').value = '';
    await loadAllData();
  } catch (err) {
    alertDialog({ title: 'Session Error', message: err.message, isError: true });
  } finally {
    if (btn) btn.disabled = false;
  }
});

// Change Master Password Form
const changePwdForm = document.getElementById('change-password-form');
if (changePwdForm) {
  changePwdForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const oldPwd = document.getElementById('pwd-old').value;
    const newPwd = document.getElementById('pwd-new').value;
    const repeatPwd = document.getElementById('pwd-repeat').value;
    const errBox = document.getElementById('change-pwd-error');
    errBox.classList.add('hidden');

    if (newPwd !== repeatPwd) {
      errBox.textContent = 'New passwords do not match.';
      errBox.classList.remove('hidden');
      return;
    }
    if (newPwd.length < 4) {
      errBox.textContent = 'Password must be at least 4 characters.';
      errBox.classList.remove('hidden');
      return;
    }

    const btn = document.getElementById('change-pwd-btn');
    if (btn) btn.disabled = true;

    try {
      await api('/api/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
      });
      showToast('Master password updated successfully ✓');
      changePwdForm.reset();
    } catch (err) {
      errBox.textContent = err.message || 'Error updating password.';
      errBox.classList.remove('hidden');
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}

// Logs
async function fetchLogs() {
  const container = document.getElementById('logs-container');
  try {
    const data = await api('/api/logs');
    const logs = data.logs || [];
    if (logs.length === 0) {
      container.innerHTML = '<div class="muted">No logs recorded yet.</div>';
      return;
    }
    container.innerHTML = logs.map((l) => `
      <div style="display: flex; gap: 12px; line-height: 1.4;">
        <span class="muted">[${escapeHtml(l.time)}]</span>
        <span style="font-weight: 500;">${escapeHtml(l.event)}</span>
        <span class="muted">${escapeHtml(l.detail)}</span>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = '<div class="muted">Error reading logs.</div>';
  }
}

document.getElementById('refresh-logs-btn').addEventListener('click', fetchLogs);

// Modal cancel buttons
document.querySelectorAll('.modal-cancel').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.modal-overlay').forEach((m) => m.classList.add('hidden'));
  });
});

// Boot
window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  checkAuthStatus();
});
