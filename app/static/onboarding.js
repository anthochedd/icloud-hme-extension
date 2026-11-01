// First-run configuration. Uses the same authenticated APIs as Settings.
let setupUrl = '';

async function showOnboarding() {
  document.getElementById('app-container').classList.add('hidden');
  document.getElementById('auth-container').classList.add('hidden');
  document.getElementById('onboarding').classList.remove('hidden');
  try {
    const data = await api('/api/settings');
    const select = document.getElementById('setup-addresses');
    select.replaceChildren();
    const isUnconfiguredContainer = data.network.container && !data.network.host_addresses_supplied;
    const candidates = isUnconfiguredContainer
      ? data.network.candidates.filter(item => item.url === data.network.local_url)
      : data.network.candidates;
    for (const item of candidates) {
      select.add(new Option(`${item.label} — ${item.url}`, item.url));
    }
    // The address already used by this browser is a useful Docker/proxy fallback.
    if (![...select.options].some(o => o.value === location.origin)) {
      select.add(new Option(`Current browser address — ${location.origin}`, location.origin));
    }
    setupUrl = data.settings.server_url || location.origin;
    select.add(new Option('Custom address', 'custom'));
    select.value = [...select.options].some(o => o.value === setupUrl) ? setupUrl : 'custom';
    document.getElementById('setup-url').value = setupUrl;
    updateAddressSelection();
    setupStep('network');
  } catch (err) { setupError(err); }
}

function setupStep(name) {
  document.querySelectorAll('[data-setup-step]').forEach(el => {
    el.classList.toggle('hidden', el.dataset.setupStep !== name);
  });
  document.getElementById('setup-error').textContent = '';
  document.getElementById('setup-progress').textContent =
    {network: '02 / NETWORK', cookies: '03 / ICLOUD SESSION', extension: '04 / BROWSER EXTENSION'}[name];
}

function setupError(err) {
  document.getElementById('setup-error').textContent = err.message;
}

function updateAddressSelection() {
  const select = document.getElementById('setup-addresses');
  const custom = select.value === 'custom';
  const input = document.getElementById('setup-url');
  document.getElementById('setup-custom-address').classList.toggle('hidden', !custom);
  input.disabled = !custom;
  input.required = custom;
  if (custom) input.focus();
}

document.getElementById('setup-addresses').addEventListener('change', updateAddressSelection);

document.getElementById('setup-network-form').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    const settings = await api('/api/settings', {method: 'POST', body: JSON.stringify({
      server_url: document.getElementById('setup-addresses').value === 'custom'
        ? document.getElementById('setup-url').value.trim()
        : document.getElementById('setup-addresses').value,
    })});
    setupUrl = settings.server_url;
    setupStep('cookies');
  } catch (err) { setupError(err); }
});

document.getElementById('setup-cookies-form').addEventListener('submit', async e => {
  e.preventDefault();
  const button = e.submitter;
  button.disabled = true;
  try {
    const account = await api('/api/account/cookies', {method: 'POST', body: JSON.stringify({
      cookie: document.getElementById('setup-cookies').value.trim(),
    })});
    if (!account.is_connected) throw new Error(account.list_error || 'Could not connect. Export fresh iCloud cookies and try again.');
    document.getElementById('setup-cookies').value = '';
    setupStep('extension');
    document.getElementById('setup-chosen-url').textContent = setupUrl;
  } catch (err) { setupError(err); }
  finally { button.disabled = false; }
});

document.getElementById('setup-create-key').addEventListener('click', async e => {
  e.target.disabled = true;
  try {
    const key = await api('/api/keys', {method: 'POST', body: JSON.stringify({name: 'Browser extension'})});
    document.getElementById('setup-api-key').value = key.key;
  } catch (err) { setupError(err); e.target.disabled = false; }
});

async function completeOnboarding(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await api('/api/settings', {method: 'POST', body: JSON.stringify({server_url: setupUrl, complete: true})});
    state.auth.onboarding_complete = true;
    document.getElementById('setup-api-key').value = '';
    document.getElementById('setup-cookies').value = '';
    document.getElementById('setup-create-key').disabled = false;
    document.getElementById('onboarding').classList.add('hidden');
    showAppView();
  } catch (err) { setupError(err); }
  finally { button.disabled = false; }
}

document.getElementById('setup-finish').addEventListener('click', completeOnboarding);
document.getElementById('setup-explore').addEventListener('click', completeOnboarding);

document.getElementById('setup-back-network').addEventListener('click', () => setupStep('network'));
document.getElementById('reconfigure-btn').addEventListener('click', () => {
  clearInterval(state.pollTimer);
  showOnboarding();
});
