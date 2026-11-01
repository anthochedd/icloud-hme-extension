// Keep track of the last right-clicked element for context menu operations
document.addEventListener('contextmenu', (e) => {
  window.__lastRightClickedElement = e.target;
}, true);

// Listen for messages from background script
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'paste_text') {
    handlePasteAndToast(msg.text, msg.toastMessage || `✓ Pasted: ${msg.text}`);
    sendResponse({ ok: true });
    return true;
  }

  if (msg.action === 'show_password_choice') {
    showPasswordChoiceModal(msg.data);
    sendResponse({ ok: true });
    return true;
  }
});

function handlePasteAndToast(text, toastMsg) {
  // A. Copy to clipboard
  try {
    navigator.clipboard.writeText(text);
  } catch {
    const t = document.createElement('textarea');
    t.value = text;
    t.style.position = 'fixed';
    t.style.opacity = '0';
    document.body.appendChild(t);
    t.select();
    document.execCommand('copy');
    document.body.removeChild(t);
  }

  // B. Paste directly into input / active element
  const target = window.__lastRightClickedElement || document.activeElement;
  if (target) {
    target.focus();
    if (target.isContentEditable) {
      document.execCommand('insertText', false, text);
    } else if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
      const start = target.selectionStart !== null ? target.selectionStart : target.value.length;
      const end = target.selectionEnd !== null ? target.selectionEnd : target.value.length;
      const ok = document.execCommand('insertText', false, text);
      if (!ok) {
        const val = target.value || '';
        target.value = val.substring(0, start) + text + val.substring(end);
        target.selectionStart = target.selectionEnd = start + text.length;
      }
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  // C. Show subtle floating feedback notification
  showFloatingToast(toastMsg);
}

function showFloatingToast(msg) {
  const toast = document.createElement('div');
  toast.textContent = msg;
  toast.style.cssText = `
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #111111;
    color: #ffffff;
    padding: 10px 16px;
    border-radius: 8px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
    font-weight: 500;
    box-shadow: 0 4px 14px rgba(0,0,0,0.25);
    z-index: 2147483647;
    pointer-events: none;
    transition: opacity 0.3s ease, transform 0.3s ease;
    transform: translateY(0);
    opacity: 1;
  `;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

function showPasswordChoiceModal(data) {
  const existingModal = document.getElementById('__ihme_password_choice_modal');
  if (existingModal) existingModal.remove();

  const overlay = document.createElement('div');
  overlay.id = '__ihme_password_choice_modal';
  overlay.style.cssText = `
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.72);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    z-index: 2147483647;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  `;

  const box = document.createElement('div');
  box.style.cssText = `
    background: #0d0f15;
    color: #f3f4f6;
    width: 380px;
    max-width: 90vw;
    border-radius: 14px;
    padding: 22px;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.75);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-top: 1px solid rgba(255, 255, 255, 0.22);
  `;

  function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, (m) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    }[m]));
  }

  box.innerHTML = `
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="7.5" cy="15.5" r="5.5"></circle>
        <path d="m21 2-9.6 9.6"></path>
        <path d="m15.5 7.5 3 3L22 7l-3-3"></path>
      </svg>
      <h3 style="margin:0; font-size:16px; font-weight:600; color:#ffffff;">Existing Password Found</h3>
    </div>
    <p style="margin:0 0 16px; font-size:13px; color:#9ca3af; line-height:1.45;">
      A password is already saved for <b style="color:#ffffff;">${escapeHtml(data.site || data.domain || 'this site')}</b>
      ${data.email ? `<br/><span style="font-size:12px; font-family:monospace; color:#cbd5e1; background:rgba(255,255,255,0.06); padding:2px 6px; border-radius:4px; display:inline-block; margin-top:4px;">(${escapeHtml(data.email)})</span>` : ''}
    </p>
    <div style="display:flex; flex-direction:column; gap:8px;">
      <button id="__ihme_btn_use" style="
        background: #0070f3; color: #fff; border: 1px solid rgba(255,255,255,0.15); padding: 10px 14px;
        border-radius: 8px; font-size: 13.5px; font-weight: 500; cursor: pointer; text-align: left;
        display: flex; align-items: center; justify-content: space-between; transition: opacity 0.15s ease;
      ">
        <span>Use Existing Password</span>
        <span style="font-size:11px; opacity:0.85; letter-spacing:1px;">••••••••</span>
      </button>
      <button id="__ihme_btn_new" style="
        background: rgba(255, 255, 255, 0.08); color: #f3f4f6; border: 1px solid rgba(255, 255, 255, 0.15); padding: 10px 14px;
        border-radius: 8px; font-size: 13.5px; font-weight: 500; cursor: pointer; text-align: left; transition: background 0.15s ease;
      ">
        ⚡ Generate New Password
      </button>
      <button id="__ihme_btn_cancel" style="
        background: transparent; color: #9ca3af; border: none; padding: 8px 14px;
        border-radius: 8px; font-size: 12.5px; cursor: pointer; text-align: center; margin-top: 4px;
      ">
        Cancel
      </button>
    </div>
  `;

  overlay.appendChild(box);
  document.body.appendChild(overlay);

  box.querySelector('#__ihme_btn_use').addEventListener('click', (e) => {
    e.target.disabled = true;
    overlay.remove();
    handlePasteAndToast(data.password, `✓ Existing password pasted & copied (for ${data.email || data.site})`);
  });

  box.querySelector('#__ihme_btn_new').addEventListener('click', (e) => {
    e.target.disabled = true;
    overlay.remove();
    chrome.runtime.sendMessage({
      action: 'generate_new_password_for_site',
      domain: data.domain || data.site,
      email: data.email,
    }, (resp) => {
      if (resp && resp.password) {
        handlePasteAndToast(resp.password, `✓ New password generated & pasted (saved for ${resp.email || data.site})`);
      }
    });
  });

  box.querySelector('#__ihme_btn_cancel').addEventListener('click', () => {
    overlay.remove();
  });

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove();
  });
}
