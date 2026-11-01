importScripts("config.js");
/**
 * iCloud Hide-My-Email v3 - Background Service Worker
 * Handles context menus:
 *   1) Create iCloud address and paste
 *   2) Generate password and paste
 */

// Register context menus for editable fields
chrome.runtime.onInstalled.addListener(() => {
  // Clear any previous menu items before creating
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: 'create_address_and_paste',
      title: 'Create iCloud address and paste',
      contexts: ['editable'],
    });

    chrome.contextMenus.create({
      id: 'generate_password_and_paste',
      title: 'Generate password and paste',
      contexts: ['editable'],
    });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'create_address_and_paste' && tab && tab.id) {
    await handleCreateAndPaste(info, tab);
  } else if (info.menuItemId === 'generate_password_and_paste' && tab && tab.id) {
    await handleGeneratePasswordAndPaste(info, tab);
  }
});

// Listener for messages from content scripts
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'generate_new_password_for_site') {
    (async () => {
      try {
        const stored = await chrome.storage.local.get(['server_url', 'api_key']);
        const serverUrl = (stored.server_url || IHME_DEFAULT_SERVER_URL).replace(/\/+$/, '');
        const apiKey = stored.api_key || '';

        const res = await fetch(`${serverUrl}/api/extension/password`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': apiKey,
          },
          body: JSON.stringify({
            action: 'generate_new',
            domain: msg.domain || '',
            email: msg.email || '',
          }),
        });

        const data = await res.json();
        sendResponse(data);
      } catch (err) {
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true; // Keep channel open for async response
  }
});

// ------------------------------------------------------------- 1. Create Address & Paste
async function handleCreateAndPaste(info, tab) {
  const stored = await chrome.storage.local.get(['server_url', 'api_key']);
  const serverUrl = (stored.server_url || IHME_DEFAULT_SERVER_URL).replace(/\/+$/, '');
  const apiKey = stored.api_key || '';

  if (!apiKey) {
    chrome.tabs.sendMessage(tab.id, {
      action: 'paste_text',
      text: '',
      toastMessage: '⚠️ iCloud HME: Please set your API key in extension settings.',
    });
    return;
  }

  let label = 'None';
  if (tab.url) {
    try {
      const parsed = new URL(tab.url);
      if (parsed.protocol.startsWith('http')) {
        label = parsed.hostname.replace(/^www\./, '') || 'None';
      }
    } catch {
      label = 'None';
    }
  }

  let email = '';
  try {
    const res = await fetch(`${serverUrl}/api/extension/claim`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify({
        label: label,
        note: `Created via right-click for ${label}`,
      }),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const errorMsg = data.detail || data.message || `HTTP ${res.status}`;
      chrome.tabs.sendMessage(tab.id, {
        action: 'paste_text',
        text: '',
        toastMessage: `⚠️ iCloud error: ${errorMsg}`,
      });
      return;
    }

    email = data.email;

    // Save to local extension history
    const localData = await chrome.storage.local.get(['claim_history']);
    const history = localData.claim_history || [];
    history.unshift({
      label: label,
      email: email,
      anonymousId: data.anonymousId || '',
      time: Date.now(),
    });
    await chrome.storage.local.set({
      claim_history: history.slice(0, 10),
      last_claimed: { email: email, domain: label, tabId: tab.id, time: Date.now() },
    });

    chrome.tabs.sendMessage(tab.id, {
      action: 'paste_text',
      text: email,
      toastMessage: `✓ iCloud Address: ${email} (pasted & copied)`,
    });
  } catch (err) {
    chrome.tabs.sendMessage(tab.id, {
      action: 'paste_text',
      text: '',
      toastMessage: `⚠️ Network error: ${err.message}`,
    });
  }
}

// ------------------------------------------------------------- 2. Generate Password & Paste
let isGeneratingPassword = false;
let lastPasswordGenTimestamp = 0;

async function handleGeneratePasswordAndPaste(info, tab) {
  const now = Date.now();
  // Prevent double request / rapid double-clicks
  if (isGeneratingPassword || (now - lastPasswordGenTimestamp < 1500)) {
    return;
  }
  isGeneratingPassword = true;
  lastPasswordGenTimestamp = now;

  try {
    const stored = await chrome.storage.local.get(['server_url', 'api_key']);
    const serverUrl = (stored.server_url || IHME_DEFAULT_SERVER_URL).replace(/\/+$/, '');
    const apiKey = stored.api_key || '';

    if (!apiKey) {
      chrome.tabs.sendMessage(tab.id, {
        action: 'paste_text',
        text: '',
        toastMessage: '⚠️ iCloud HME: Please set your API key in extension settings.',
      });
      return;
    }

    let domain = 'None';
    if (tab.url) {
      try {
        const parsed = new URL(tab.url);
        if (parsed.protocol.startsWith('http')) {
          domain = parsed.hostname.replace(/^www\./, '') || 'None';
        }
      } catch {
        domain = 'None';
      }
    }

    // Check if an address was claimed on this tab or for this domain recently
    let preferredEmail = '';
    try {
      const localData = await chrome.storage.local.get(['last_claimed']);
      if (localData.last_claimed && (Date.now() - localData.last_claimed.time < 300000)) {
        if (localData.last_claimed.tabId === tab.id || localData.last_claimed.domain === domain) {
          preferredEmail = localData.last_claimed.email || '';
        }
      }
    } catch {}

    // 1. Check if password already exists for this email or domain
    const checkRes = await fetch(`${serverUrl}/api/extension/password`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify({
        action: 'check',
        domain: domain,
        email: preferredEmail,
      }),
    });

    const checkData = await checkRes.json();

    // If password was literally just generated (duplicate request prevention), paste it directly
    if (checkData.just_generated && checkData.password) {
      chrome.tabs.sendMessage(tab.id, {
        action: 'paste_text',
        text: checkData.password,
        toastMessage: `✓ Password generated & pasted (saved for ${checkData.email || domain})`,
      });
      return;
    }

    if (checkData.has_password && checkData.password) {
      // Conflict / existing password exists -> Prompt user
      chrome.tabs.sendMessage(tab.id, {
        action: 'show_password_choice',
        data: {
          site: domain,
          domain: domain,
          email: checkData.email,
          password: checkData.password,
        },
      });
      return;
    }

    // 2. No existing password -> Generate and paste immediately!
    const genRes = await fetch(`${serverUrl}/api/extension/password`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify({
        action: 'generate_new',
        domain: domain,
        email: preferredEmail || checkData.email || '',
      }),
    });

    const genData = await genRes.json();
    if (genData.ok && genData.password) {
      chrome.tabs.sendMessage(tab.id, {
        action: 'paste_text',
        text: genData.password,
        toastMessage: `✓ Password generated & pasted (saved for ${genData.email || domain})`,
      });
    } else {
      throw new Error(genData.detail || 'Could not generate password');
    }
  } catch (err) {
    chrome.tabs.sendMessage(tab.id, {
      action: 'paste_text',
      text: '',
      toastMessage: `⚠️ Password error: ${err.message}`,
    });
  } finally {
    setTimeout(() => {
      isGeneratingPassword = false;
    }, 1000);
  }
}
