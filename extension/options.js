/**
 * iCloud Hide-My-Email v3 - Extension Options Script
 */

document.addEventListener('DOMContentLoaded', async () => {
  const urlInput = document.getElementById('server-url');
  const keyInput = document.getElementById('api-key');
  const testBox = document.getElementById('test-result');

  // Load saved options
  const data = await chrome.storage.local.get(['server_url', 'api_key']);
  urlInput.value = data.server_url || IHME_DEFAULT_SERVER_URL;
  if (!data.server_url) {
    await chrome.storage.local.set({ server_url: urlInput.value });
  }
  keyInput.value = data.api_key || '';

  // Form submit
  document.getElementById('options-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const server_url = urlInput.value.trim().replace(/\/+$/, '');
    const api_key = keyInput.value.trim();

    await chrome.storage.local.set({ server_url, api_key });

    testBox.className = 'test-result success';
    testBox.textContent = '✓ Settings saved successfully!';
    testBox.classList.remove('hidden');

    setTimeout(() => testBox.classList.add('hidden'), 3000);
  });

  // Test button
  document.getElementById('test-btn').addEventListener('click', async () => {
    const server_url = urlInput.value.trim().replace(/\/+$/, '');
    const api_key = keyInput.value.trim();

    testBox.className = 'test-result';
    testBox.textContent = 'Testing connection...';
    testBox.classList.remove('hidden');

    if (!server_url) {
      testBox.className = 'test-result error';
      testBox.textContent = 'Please enter a server URL.';
      return;
    }
    if (!api_key) {
      testBox.className = 'test-result error';
      testBox.textContent = 'Please enter your API key.';
      return;
    }

    try {
      const res = await fetch(`${server_url}/api/extension/status`, {
        headers: { 'X-API-Key': api_key },
      });

      if (!res.ok) {
        if (res.status === 401) {
          testBox.className = 'test-result error';
          testBox.textContent = 'Error 401: Invalid or revoked API key.';
        } else {
          testBox.className = 'test-result error';
          testBox.textContent = `HTTP Error ${res.status}`;
        }
        return;
      }

      const info = await res.json();
      testBox.className = 'test-result success';
      testBox.textContent = `✓ Connection successful! Account: ${info.account || 'iCloud'} · Reserve: ${info.pool_ready}/${info.pool_target} ready.`;
    } catch (err) {
      testBox.className = 'test-result error';
      testBox.textContent = `Connection failed: ${err.message}. Ensure the server is running and reachable.`;
    }
  });
});
