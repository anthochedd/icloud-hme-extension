# iCloud HME browser extension

Use the server setup wizard to choose a reachable URL, connect iCloud, download and extract a configured ZIP, and create an API key.

1. Open `chrome://extensions`, enable **Developer mode**, and choose **Load unpacked**.
2. Select the extracted folder containing `manifest.json`.
3. Open extension settings. The packaged default is the URL chosen in setup. Paste your API key, save and test the connection.

You can also load this source folder directly; its default is `http://127.0.0.1:8001`. For a remote server, enter its reachable LAN or Tailscale address instead. Saved browser settings override the packaged default. Configuration and keys use local browser storage, not Chrome Sync.

Use the popup to claim or search aliases. On supported editable fields, use the right-click menu to insert an address or generate a password. The server must be running and authenticated to iCloud, with reserve capacity for claims.

The extension requests HTTP(S) host access to reach the configured server, plus website content-script, clipboard, storage, tab and scripting permissions for filling. Protected pages and some frames cannot be filled.

The ZIP contains no cookies or API key. Never share your saved key. See the [main README](../README.md) for installation, cookie export, API documentation and limitations.

Enjoying the extension? [Star the repo](https://github.com/anthochedd/icloud-hme-extension) or [report an issue](https://github.com/anthochedd/icloud-hme-extension/issues).
