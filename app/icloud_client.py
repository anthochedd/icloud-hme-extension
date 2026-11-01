"""Self-contained iCloud Hide-My-Email client for v3.

Consolidates and modernizes all iCloud HME web APIs:
  - generate:       v1/hme/generate
  - reserve:        v1/hme/reserve
  - list:           v2/hme/list
  - get:            v2/hme/get
  - updateMetaData: v1/hme/updateMetaData
  - deactivate:     v1/hme/deactivate
  - delete:         v1/hme/delete
  - sync:           p113-keyvalueservice.icloud.com/json/sync (attempts token refresh)
  - keep_alive:     www.icloud.com/
"""

import asyncio
import json
import re
import ssl
import uuid
from typing import Optional

import aiohttp
import certifi

# Defaults provided by iCloud web interface (modernized 2636 build)
DEFAULT_BUILD = "2636Build17"
DEFAULT_PARTITION = "p55"


def format_proxy(proxy_str: Optional[str]) -> Optional[str]:
    """Formats IP:PORT, IP:PORT:USER:PASS or http(s) string into standard URL."""
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None
    if proxy_str.startswith("http://") or proxy_str.startswith("https://"):
        return proxy_str
    parts = proxy_str.split(":")
    if len(parts) == 4:
        return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return f"http://{proxy_str}"


def clean_cookie_str(raw: Optional[str]) -> str:
    """Cleans and standardizes raw cookie string from web input or cookies.txt."""
    if not raw:
        return ""
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    if "\t" in raw:
        lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
        pairs = []
        for l in lines:
            cols = l.split("\t")
            if len(cols) >= 7:
                pairs.append(f"{cols[5]}={cols[6]}")
        if pairs:
            return "; ".join(pairs)
    if "\n" in raw:
        lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("//") and not l.startswith("#")]
        if len(lines) == 1:
            raw = lines[0]
        elif all("=" in l for l in lines) and not any(";" in l for l in lines):
            raw = "; ".join(lines)
        else:
            raw = lines[0]
    return raw.strip()


class HideMyEmail:
    def __init__(
        self,
        cookies: str = "",
        proxy: Optional[str] = None,
        client_id: Optional[str] = None,
        build: str = DEFAULT_BUILD,
        partition: str = DEFAULT_PARTITION,
    ):
        self.proxy = format_proxy(proxy)
        self.client_id = client_id or str(uuid.uuid4())
        self.build = build
        self.default_partition = partition
        self.partition = partition
        self.dsid = ""
        self.s: Optional[aiohttp.ClientSession] = None
        self.__cookies = ""
        self.cookies = cookies

    # ------------------------------------------------------------------ Cookies
    @property
    def cookies(self) -> str:
        return self.__cookies

    @cookies.setter
    def cookies(self, cookies: str):
        self.__cookies = clean_cookie_str(cookies)
        self._parse_cookies()
        if self.s is not None and not self.s.closed:
            self.s.headers["Cookie"] = self.__cookies

    async def reset_session(self):
        """Forces closing existing session so next request creates a fresh one."""
        if self.s is not None:
            try:
                if not self.s.closed:
                    await self.s.close()
            except Exception:
                pass
            self.s = None

    def _parse_cookies(self):
        """Extracts dsid and partition hint from cookies string."""
        m_dsid = re.search(r'X-APPLE-WEBAUTH-USER=".*?d=(\d+)"', self.__cookies)
        if m_dsid:
            self.dsid = m_dsid.group(1)
        m_part = re.search(r"X-APPLE-USER-PARTITION=(\d+)", self.__cookies)
        if m_part:
            self.partition = f"p{m_part.group(1)}"
        else:
            self.partition = self.default_partition

    def update_cookie(self, name: str, value: str):
        """Replaces or adds a cookie and updates the running session."""
        parts = {}
        for item in self.__cookies.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                parts[k] = v
        parts[name] = value
        self.__cookies = "; ".join(f"{k}={v}" for k, v in parts.items())
        self._parse_cookies()
        if self.s is not None and not self.s.closed:
            self.s.headers["Cookie"] = self.__cookies

    # ------------------------------------------------------------------ URLs & Params
    def _hme_url(self, endpoint: str, version: str = "v1", partition: Optional[str] = None) -> str:
        part = partition or self.partition or DEFAULT_PARTITION
        return f"https://{part}-maildomainws.icloud.com/{version}/hme/{endpoint}"

    def _params(self) -> dict:
        return {
            "clientBuildNumber": self.build,
            "clientMasteringNumber": self.build,
            "clientId": self.client_id,
            "dsid": self.dsid,
        }

    def _headers(self) -> dict:
        return {
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
            ),
            "Content-Type": "text/plain",
            "Accept": "*/*",
            "Sec-GPC": "1",
            "Origin": "https://www.icloud.com",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.icloud.com/",
            "Accept-Language": "en-US,en-GB;q=0.9,en;q=0.8",
            "sec-ch-ua": '"Brave";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "Cookie": self.__cookies,
        }

    # ------------------------------------------------------------------ Session
    async def open(self):
        if self.s is not None and not self.s.closed:
            return self
        connector = aiohttp.TCPConnector(
            ssl=ssl.create_default_context(cafile=certifi.where())
        )
        self.s = aiohttp.ClientSession(
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=20),
            connector=connector,
        )
        return self

    async def close(self):
        if self.s is not None and not self.s.closed:
            await self.s.close()
            self.s = None

    async def __aenter__(self):
        return await self.open()

    async def __aexit__(self, *exc):
        await self.close()

    # ------------------------------------------------------------------ HTTP Helpers
    async def _post_json(self, url: str, payload: dict) -> dict:
        await self.open()
        try:
            async with self.s.post(url, params=self._params(), json=payload, proxy=self.proxy) as r:
                return await r.json()
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}

    async def _post_text(self, url: str, payload: dict) -> dict:
        """POST with Content-Type: text/plain and JSON payload string (standard iCloud format)."""
        await self.open()
        try:
            data = json.dumps(payload)
            async with self.s.post(
                url,
                params=self._params(),
                data=data,
                headers={"Content-Type": "text/plain"},
                proxy=self.proxy,
            ) as r:
                try:
                    return await r.json()
                except Exception:
                    return {"success": r.status == 200, "text": await r.text()}
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}

    # ------------------------------------------------------------------ HME APIs
    async def generate_email(self) -> dict:
        """Generate a temporary HME address (v1/hme/generate)."""
        url = self._hme_url("generate", version="v1")
        return await self._post_json(url, {"langCode": "en-us"})

    async def reserve_email(self, email: str, label: str, note: str = "") -> dict:
        """Reserve and activate an address with a label (v1/hme/reserve)."""
        url = self._hme_url("reserve", version="v1")
        payload = {"hme": email, "label": label, "note": note or ""}
        return await self._post_json(url, payload)

    async def list_email(self) -> dict:
        """List all HME addresses (v2/hme/list)."""
        await self.open()
        url = self._hme_url("list", version="v2")
        try:
            async with self.s.get(url, params=self._params(), proxy=self.proxy) as r:
                return await r.json()
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}

    async def get_email(self, anonymous_id: str) -> dict:
        """Get address details by anonymousId (v2/hme/get)."""
        url = self._hme_url("get", version="v2")
        return await self._post_json(url, {"anonymousId": anonymous_id})

    async def update_metadata(self, anonymous_id: str, label: str, note: str = "") -> dict:
        """Update the address label and note (v1/hme/updateMetaData)."""
        url = self._hme_url("updateMetaData", version="v1")
        payload = {"anonymousId": anonymous_id, "label": label, "note": note or ""}
        # iCloud accepts either text/plain json or application/json, text/plain is safest across versions
        return await self._post_text(url, payload)

    async def deactivate_email(self, anonymous_id: str) -> dict:
        """Deactivate an HME address (v1/hme/deactivate)."""
        url = self._hme_url("deactivate", version="v1")
        return await self._post_text(url, {"anonymousId": anonymous_id})

    async def reactivate_email(self, anonymous_id: str) -> dict:
        """Reactivate an HME address (v1/hme/reactivate)."""
        url = self._hme_url("reactivate", version="v1")
        return await self._post_text(url, {"anonymousId": anonymous_id})

    async def delete_email(self, anonymous_id: str) -> dict:
        """Permanently delete an HME address (v1/hme/delete)."""
        url = self._hme_url("delete", version="v1")
        return await self._post_text(url, {"anonymousId": anonymous_id})

    # ------------------------------------------------------------------ Sync & KeepAlive
    async def sync(self) -> dict:
        """Attempt to refresh the Apple session and capture any returned X-APPLE-WEBAUTH-TOKEN."""
        await self.open()
        url = "https://p113-keyvalueservice.icloud.com/json/sync"
        payload = {
            "service-id": "appleprefs",
            "apps": [{"app-id": "hidemyemail", "registry-version": ""}],
        }
        try:
            async with self.s.post(
                url, params=self._params(), json=payload, proxy=self.proxy
            ) as r:
                res = await r.json()
                if r.status == 200:
                    for k, morsel in r.cookies.items():
                        if k == "X-APPLE-WEBAUTH-TOKEN":
                            self.update_cookie(k, morsel.value)
                return res
        except asyncio.TimeoutError:
            return {"error": 1, "reason": "Request timed out"}
        except Exception as e:
            return {"error": 1, "reason": str(e)}

    async def keep_alive(self) -> bool:
        """Send a lightweight heartbeat request to iCloud.com."""
        await self.open()
        try:
            async with self.s.get("https://www.icloud.com/", proxy=self.proxy) as r:
                return r.status == 200
        except Exception:
            return False
