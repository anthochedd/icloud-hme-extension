// Public GitHub metadata only. No application credentials leave this page.
document.addEventListener('DOMContentLoaded', async () => {
  const cacheKey = 'github-stars:anthochedd/icloud-hme-extension';

  function showCount(count) {
    document.querySelectorAll('[data-repo-stars]').forEach(el => {
      el.textContent = new Intl.NumberFormat('en-US', {
        notation: count >= 10000 ? 'compact' : 'standard',
        maximumFractionDigits: 1,
      }).format(count);
      el.setAttribute('aria-label', `${count} GitHub stars`);
      el.hidden = false;
    });
  }

  try {
    const cached = JSON.parse(localStorage.getItem(cacheKey) || 'null');
    if (cached && Number.isSafeInteger(cached.count) && cached.count >= 0) {
      showCount(cached.count);
    }
  } catch { /* Storage may be disabled; the link still works. */ }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch('https://api.github.com/repos/anthochedd/icloud-hme-extension', {
      headers: { Accept: 'application/vnd.github+json' },
      credentials: 'omit',
      cache: 'no-cache',
      referrerPolicy: 'no-referrer',
      signal: controller.signal,
    });
    if (!response.ok) return;
    const data = await response.json();
    if (!Number.isSafeInteger(data.stargazers_count) || data.stargazers_count < 0) return;
    showCount(data.stargazers_count);
    try {
      localStorage.setItem(cacheKey, JSON.stringify({count: data.stargazers_count, fetchedAt: Date.now()}));
    } catch { /* Display does not depend on cache availability. */ }
  } catch { /* Keep the cached count, or just the star link, when GitHub is unavailable. */ }
  finally { clearTimeout(timeout); }
});
