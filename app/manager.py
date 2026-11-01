"""Central Account & Session Manager for v3.

Manages:
  - Importing cookies from the project root or data directory and saving refreshed cookies to data
  - iCloud client lifecycle and keep-alive background token refresh
  - Listing, manual generation, renaming, deactivation and deletion of emails
  - Integrating the 10-email pool worker
  - Detailed activity logging
"""

import asyncio
import os
import random
import re
import time
from typing import List, Dict, Optional, Any

from .config import (
    ROOT_COOKIE_FILE,
    DATA_COOKIE_FILE,
    LOGS_FILE,
)
from .icloud_client import HideMyEmail, clean_cookie_str, format_proxy
from .pool import pool_manager, match_pool_slot
from .passwords import password_manager


def compute_label(template: Optional[str], index: int, total_count: int) -> str:
    """Computes label for index (0-based) based on standard sequence patterns."""
    if not template or not template.strip():
        return f"Mail {random.randint(100, 99999)}"

    label = template.strip()
    n = index + 1  # 1-based index

    # 1. Standard printf format: %03d, %02d, %d
    m_printf = re.search(r'%(0?\d*)d', label)
    if m_printf:
        fmt = m_printf.group(0)
        formatted = fmt % n
        return label[:m_printf.start()] + formatted + label[m_printf.end():]

    # 2. Standard bracket hash pattern: {#}, {##}, {###}, [#], [##]
    m_bracket_hash = re.search(r'[\{\[](#+)[\}\]]', label)
    if m_bracket_hash:
        width = len(m_bracket_hash.group(1))
        formatted = str(n).zfill(width)
        return label[:m_bracket_hash.start()] + formatted + label[m_bracket_hash.end():]

    # Standard bare hash pattern: ## (01), ### (001)
    m_hash = re.search(r'(#{2,})', label)
    if m_hash:
        width = len(m_hash.group(1))
        formatted = str(n).zfill(width)
        return label[:m_hash.start()] + formatted + label[m_hash.end():]

    # 3. Standard variable placeholders: {n}, {i}, {index}, {num}, {#}
    m_var = re.search(r'\{(?:n|i|index|num|count|#)\}', label, re.IGNORECASE)
    if m_var:
        return re.sub(r'\{(?:n|i|index|num|count|#)\}', str(n), label, flags=re.IGNORECASE)

    # 4. Padded placeholders: {01}, {001}
    m_padded = re.search(r'\{(0+\d+)\}', label)
    if m_padded:
        width = len(m_padded.group(1))
        formatted = str(n).zfill(width)
        return label[:m_padded.start()] + formatted + label[m_padded.end():]

    # 5. Formula fallback: <start+step> or <start>
    m_step = re.search(r"<(\d+)\s*\+\s*(\d+)>", label)
    if m_step:
        start = int(m_step.group(1))
        step = int(m_step.group(2))
        val = start + (index * step)
        return label[:m_step.start()] + str(val) + label[m_step.end():]

    m_start = re.search(r"<(\d+)>", label)
    if m_start:
        start = int(m_start.group(1))
        val = start + index
        return label[:m_start.start()] + str(val) + label[m_start.end():]

    # 6. Default if multiple count and no format provided: append number
    if total_count > 1:
        return f"{label} {n}"

    return label


def _is_icloud_ok(res: Optional[Dict[str, Any]]) -> bool:
    if not res:
        return False
    if res.get("success") is True:
        return True
    if isinstance(res.get("result"), dict) and res["result"].get("message") == "success":
        return True
    return False


def _extract_icloud_error(res: Optional[Dict[str, Any]], default: str = "iCloud request failed") -> str:
    if not res:
        return default
    err = res.get("error")
    if isinstance(err, dict):
        return err.get("errorMessage") or err.get("reason") or str(err)
    if err:
        return str(err)
    if res.get("reason"):
        return str(res["reason"])
    if res.get("text"):
        return str(res["text"])
    return default


class AccountManager:
    def __init__(self):
        self.client = HideMyEmail()
        self.forward_email: Optional[str] = None
        self.emails: List[Dict[str, Any]] = []
        self.list_error: Optional[str] = None
        self.last_refresh: Optional[float] = None
        self.is_connected: bool = False

        # Manual generation state
        self.manual_job_active: bool = False
        self.manual_job_target: int = 0
        self.manual_job_done: int = 0
        self.manual_job_status: str = "idle"
        self.manual_job_message: str = ""
        self._manual_gen_task: Optional[asyncio.Task] = None

        # Background tasks
        self._keepalive_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

        # Connect pool callbacks to keep in-memory emails up to date instantly
        pool_manager.on_email_created_cb = self._on_pool_created
        pool_manager.on_email_claimed_cb = self._on_pool_claimed

    def _on_pool_created(self, email_data: Dict[str, Any]):
        new_entry = {
            "anonymousId": email_data["anonymousId"],
            "label": email_data["label"],
            "note": f"Temporary reserve email {email_data['label']}",
            "hme": email_data["hme"],
            "isActive": True,
            "createTimestamp": int(email_data.get("created_at", time.time()) * 1000),
        }
        if not any(e.get("anonymousId") == new_entry["anonymousId"] for e in self.emails):
            self.emails.insert(0, new_entry)

    def _on_pool_claimed(self, claimed_record: Dict[str, Any]):
        for e in self.emails:
            if e.get("anonymousId") == claimed_record["anonymousId"]:
                e["label"] = claimed_record["new_label"]
                e["note"] = "Assigned via Reserve / Extension"
                break
        password_manager.last_assigned_email = claimed_record.get("hme")

    # ----------------------------------------------------------- Cookies Handling
    def find_cookie_file(self) -> Optional[str]:
        """Find cookies.txt in the project root or private data directory."""
        if os.path.exists(ROOT_COOKIE_FILE) and os.path.getsize(ROOT_COOKIE_FILE) > 10:
            return ROOT_COOKIE_FILE
        if os.path.exists(DATA_COOKIE_FILE) and os.path.getsize(DATA_COOKIE_FILE) > 10:
            return DATA_COOKIE_FILE
        return None

    def load_cookies_from_disk(self) -> bool:
        cookie_path = self.find_cookie_file()
        if not cookie_path:
            return False
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            cleaned = clean_cookie_str(content)
            if not cleaned:
                return False
            if cleaned != self.client.cookies:
                self.client.cookies = cleaned
            # Check for proxy on subsequent lines
            proxy_line = None
            for line in lines:
                if not line.startswith("X-APPLE-") and not line.startswith("X_APPLE_") and not line.startswith("sessionToken") and not line.startswith("scnt"):
                    if any(c in line for c in [":", "http://", "https://"]) and "=" not in line:
                        proxy_line = line
                        break
            if proxy_line:
                self.client.proxy = format_proxy(proxy_line)
            return True
        except Exception as e:
            self._log("cookie_read_error", str(e))
            return False

    def save_cookies_to_disk(self):
        """Save the current cookie header and optional proxy in the private data directory."""
        content = self.client.cookies
        if self.client.proxy:
            content += f"\n{self.client.proxy}"
        for path in [DATA_COOKIE_FILE]:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                pass

    async def set_new_cookies(self, cookies_str: str, proxy_str: Optional[str] = None):
        """Sets new cookies and optional proxy from user input and saves them."""
        self.client.cookies = cookies_str.strip()
        if proxy_str is not None:
            self.client.proxy = format_proxy(proxy_str) if proxy_str.strip() else None
        await self.client.reset_session()
        self.save_cookies_to_disk()

    # ----------------------------------------------------------- Startup & Shutdown
    async def startup(self):
        """Initializes account session, keep-alive loop, first refresh, and pool worker."""
        has_cookies = self.load_cookies_from_disk()
        await self.client.open()

        if has_cookies and self.client.cookies:
            # Perform synchronous first refresh so emails are immediately ready
            try:
                await self.refresh()
            except Exception as e:
                self._log("startup_refresh_error", str(e))

        # Start continuous keep-alive loop
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        # Start pool replenishment worker
        pool_manager.start_worker(self.client, log_func=self._log)

    async def shutdown(self):
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._manual_gen_task:
            self._manual_gen_task.cancel()
        pool_manager.stop_worker()
        await self.client.close()

    # ----------------------------------------------------------- Account & Refresh
    async def refresh(self) -> Dict[str, Any]:
        """Refreshes iCloud session and lists all HME addresses."""
        async with self.lock:
            # Always check if cookies on disk have been added or updated
            self.load_cookies_from_disk()

            if not self.client.cookies:
                self.is_connected = False
                self.list_error = "No cookies configured. Please paste your iCloud cookies."
                return self.public_state()

            # Ensure session is open
            await self.client.open()

            # Sync session token
            await self.client.sync()
            self.save_cookies_to_disk()

            # Fetch list of emails
            list_res = await self.client.list_email()

            if not list_res or list_res.get("error") or not list_res.get("success", True):
                self.is_connected = False
                self.list_error = (
                    list_res.get("reason")
                    or (list_res.get("error", {}) if isinstance(list_res.get("error"), dict) else {}).get("errorMessage")
                    or "Unable to reach iCloud (session expired?)"
                )
                self._log("refresh_error", str(self.list_error))
            else:
                self.is_connected = True
                self.list_error = None
                result = list_res.get("result") or {}
                raw_emails = result.get("hmeEmails") or result.get("hmes") or []
                self.emails = [e for e in raw_emails if isinstance(e, dict)]
                self.emails.sort(key=lambda e: e.get("createTimestamp", 0), reverse=True)

                fwds = result.get("forwardToEmails") or []
                if fwds:
                    self.forward_email = fwds[0]
                elif self.emails:
                    self.forward_email = self.emails[0].get("forwardToEmail")

                self.last_refresh = time.time()
                self._log("refresh_success", f"{len(self.emails)} addresses found")

                # Sync pool with iCloud existing emails
                pool_manager.sync_with_icloud(self.emails, log_func=self._log)

            return self.public_state()

    # ----------------------------------------------------------- Keep-Alive Loop
    async def _keepalive_loop(self):
        """Runs in background to refresh iCloud token every 90-180 seconds."""
        while True:
            try:
                wait_sec = random.randint(90, 180)
                await asyncio.sleep(wait_sec)

                if not self.client.cookies:
                    continue

                res = await self.client.sync()
                await self.client.keep_alive()
                self.save_cookies_to_disk()

                if res and not res.get("error"):
                    self._log("keepalive_sync", "Token refreshed successfully")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log("keepalive_error", str(e))

    # ----------------------------------------------------------- Manual Generation
    async def start_manual_generation(self, count: int, label: Optional[str] = None):
        if self.manual_job_active:
            raise ValueError("A manual generation is already in progress.")
        MAX_CAPACITY = 750
        total_current = len(self.emails)
        if total_current >= MAX_CAPACITY:
            raise ValueError(
                f"iCloud capacity limit reached: {total_current}/{MAX_CAPACITY} addresses "
                "(active, inactive & Sign in with Apple). Delete addresses to generate more."
            )
        available = MAX_CAPACITY - total_current
        if count > available:
            raise ValueError(
                f"Cannot generate {count} addresses: only {available} slot(s) remaining "
                f"before iCloud cap of {MAX_CAPACITY}."
            )
        self.manual_job_active = True
        self.manual_job_target = count
        self.manual_job_done = 0
        self.manual_job_status = "running"
        self.manual_job_message = "Starting…"
        self._manual_gen_task = asyncio.create_task(self._manual_gen_job(count, label))

    async def stop_manual_generation(self):
        if self._manual_gen_task and not self._manual_gen_task.done():
            self._manual_gen_task.cancel()
        self.manual_job_active = False
        self.manual_job_status = "stopped"
        self.manual_job_message = "Generation stopped by user."

    async def _manual_gen_job(self, count: int, label: Optional[str]):
        self._log("manual_gen_start", f"{count} mail(s) - label={label}")
        try:
            while self.manual_job_done < count:
                if len(self.emails) >= 750:
                    self.manual_job_message = "Reached max iCloud capacity of 750 addresses."
                    break

                can_gen, wait = pool_manager.can_generate()
                if not can_gen and wait:
                    mins = max(1, int(wait // 60))
                    self.manual_job_message = (
                        f"Application hourly limit reached (max 4/h). Pausing for {mins} min ({int(wait)}s)…"
                    )
                    await asyncio.sleep(min(wait, 30))
                    continue

                self.manual_job_message = f"Creating {self.manual_job_done + 1}/{count}…"
                await self.client.sync()
                gen = await self.client.generate_email()

                if not gen or not gen.get("success"):
                    err_msg = _extract_icloud_error(gen, "iCloud generation error")
                    is_limit = any(
                        x in err_msg.lower()
                        for x in [
                            "maximum number",
                            "limit of addresses",
                            "reached the limit",
                            "too many",
                            "quota",
                        ]
                    )
                    is_auth = any(x in err_msg.lower() for x in ["invalid global session", "unauthorized", "cookie"])
                    if is_limit:
                        self.manual_job_status = "error"
                        self.manual_job_message = f"Stopped (Limit reached): {err_msg}"
                        self._log("manual_gen_limit", err_msg)
                        break
                    elif is_auth:
                        self.manual_job_status = "error"
                        self.manual_job_message = "Stopped: iCloud session expired."
                        self._log("manual_gen_error", "Session expired")
                        break
                    else:
                        self.manual_job_message = f"Failed: {err_msg}, retrying in 30s…"
                        await asyncio.sleep(30)
                        continue

                email = gen["result"]["hme"]
                use_label = compute_label(label, self.manual_job_done, count)
                res = await self.client.reserve_email(email, label=use_label)

                if res and res.get("success"):
                    self.manual_job_done += 1
                    pool_manager.gen_timestamps.append(time.time())
                    self._log("manual_mail_generated", f"{email} ({use_label})")
                    self.manual_job_message = f"{self.manual_job_done}/{count} created: {email} ✓"
                else:
                    err_msg = _extract_icloud_error(res, "iCloud reservation error")
                    is_limit = any(
                        x in err_msg.lower()
                        for x in [
                            "maximum number",
                            "limit of addresses",
                            "reached the limit",
                            "quota",
                        ]
                    )
                    if is_limit:
                        self.manual_job_status = "error"
                        self.manual_job_message = f"Stopped (Limit reached): {err_msg}"
                        self._log("manual_gen_limit", err_msg)
                        break
                    self.manual_job_message = f"Reservation failed: {err_msg}, retrying in 30s…"
                    await asyncio.sleep(30)
                    continue

                if self.manual_job_done < count:
                    # Respect the application's rolling hourly limit
                    delay = random.randint(30, 60)
                    self.manual_job_message = f"Pacing pause of {delay}s before next email (application limit: 4/h)…"
                    await asyncio.sleep(delay)

            self.manual_job_status = "done"
            self.manual_job_message = f"Finished: {self.manual_job_done}/{count} created."
            await self.refresh()
        except asyncio.CancelledError:
            self.manual_job_status = "stopped"
            self.manual_job_message = f"Stopped: {self.manual_job_done}/{count} created."
        except Exception as e:
            self.manual_job_status = "error"
            self.manual_job_message = f"Error: {e}"
        finally:
            self.manual_job_active = False

    # ----------------------------------------------------------- Actions on Emails
    async def update_email_metadata(self, anonymous_id: str, label: str, note: str = "") -> dict:
        """Updates label and note using iCloud updateMetaData endpoint."""
        res = await self.client.update_metadata(anonymous_id, label, note)
        if res and not res.get("error"):
            # Update in local list
            for e in self.emails:
                if e.get("anonymousId") == anonymous_id:
                    e["label"] = label
                    e["note"] = note
                    break
            self._log("mail_renamed", f"{anonymous_id} -> {label}")
        return res

    async def get_email_details(self, anonymous_id: str) -> dict:
        """Fetches details of an email via iCloud get endpoint."""
        return await self.client.get_email(anonymous_id)

    async def delete_emails(self, anonymous_ids: List[str], mode: str = "both") -> Dict[str, Any]:
        """Activates, deactivates, or permanently deletes selected emails."""
        results = {"success": 0, "failed": 0, "errors": []}
        for anon in anonymous_ids:
            try:
                # Find current active state of this email
                email_info = next((e for e in self.emails if e.get("anonymousId") == anon), None)
                is_active = email_info.get("isActive", True) if email_info else True

                # Step 1: Reactivate if requested
                if mode in ("activate", "reactivate"):
                    if not is_active:
                        res = await self.client.reactivate_email(anon)
                        if not _is_icloud_ok(res):
                            err_msg = _extract_icloud_error(res, "iCloud reactivation failed")
                            raise Exception(err_msg)
                        await asyncio.sleep(0.3)
                    for e in self.emails:
                        if e.get("anonymousId") == anon:
                            e["isActive"] = True
                            break
                    results["success"] += 1
                    continue

                # Step 2: Deactivate if requested and still active
                if mode in ("deactivate", "both"):
                    if is_active:
                        res = await self.client.deactivate_email(anon)
                        if not _is_icloud_ok(res):
                            err_msg = _extract_icloud_error(res, "iCloud deactivation failed")
                            is_already_inactive = (
                                "already deactivated" in err_msg.lower()
                                or "invalid request" in err_msg.lower()
                                or (isinstance(res, dict) and res.get("error", {}).get("errorCode") == "-41000")
                            )
                            # If we are deleting anyway and it is already inactive, continue
                            if mode == "both" and is_already_inactive:
                                pass
                            else:
                                raise Exception(err_msg)
                        await asyncio.sleep(0.5)
                    elif mode == "deactivate":
                        # Already deactivated, nothing to do
                        pass

                # Step 3: Delete permanently if requested
                if mode in ("delete", "both"):
                    # If mode is explicitly 'delete' but email is still active, Apple requires deactivation first
                    if mode == "delete" and is_active:
                        res_deact = await self.client.deactivate_email(anon)
                        if not _is_icloud_ok(res_deact):
                            err_msg = _extract_icloud_error(res_deact, "iCloud deactivation failed")
                            is_already_inactive = (
                                "already deactivated" in err_msg.lower()
                                or "invalid request" in err_msg.lower()
                                or (isinstance(res_deact, dict) and res_deact.get("error", {}).get("errorCode") == "-41000")
                            )
                            if not is_already_inactive:
                                raise Exception(err_msg)
                        await asyncio.sleep(0.5)

                    res = await self.client.delete_email(anon)
                    if not _is_icloud_ok(res):
                        err = _extract_icloud_error(res, "iCloud deletion failed")
                        raise Exception(err)
                    await asyncio.sleep(0.3)

                # Instantly reflect in local memory cache
                if mode in ("delete", "both"):
                    self.emails = [e for e in self.emails if e.get("anonymousId") != anon]
                    pool_manager.remove_claimed_emails([anon])
                elif mode == "deactivate":
                    for e in self.emails:
                        if e.get("anonymousId") == anon:
                            e["isActive"] = False
                            break

                results["success"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))

        action_name = "activated" if mode in ("activate", "reactivate") else ("deactivated" if mode == "deactivate" else "deleted")
        if results["failed"] > 0:
            err_details = f" ({', '.join(results['errors'])})" if results["errors"] else ""
            self._log(f"bulk_{action_name}", f"{results['success']} {action_name}, {results['failed']} failed{err_details}")
        else:
            self._log(f"bulk_{action_name}", f"{results['success']} {action_name}, {results['failed']} failed")

        await self.refresh()
        return results

    async def create_new_email(self, label: str, note: str = "") -> Dict[str, Any]:
        """Creates a brand new Hide-My-Email address directly on iCloud (does NOT rename pool reserve)."""
        MAX_CAPACITY = 750
        if len(self.emails) >= MAX_CAPACITY:
            raise ValueError(
                f"iCloud capacity limit reached: {len(self.emails)}/{MAX_CAPACITY} addresses "
                "(active, inactive, pool reserve & Sign in with Apple). Delete addresses to generate more."
            )

        can_gen, wait = pool_manager.can_generate()
        if not can_gen and wait:
            mins = max(1, int(wait // 60))
            raise ValueError(f"Apple hourly limit reached (max 4/hour). Resuming in ~{mins} min ({int(wait)}s).")

        await self.client.sync()
        gen_res = await self.client.generate_email()
        if not gen_res or not gen_res.get("success"):
            err_msg = _extract_icloud_error(gen_res, "iCloud generate failed")
            if any(x in err_msg.lower() for x in ["maximum number", "limit of addresses", "reached the limit"]):
                raise ValueError("Maximum address quota reached on iCloud (750).")
            if "invalid global session" in err_msg.lower():
                raise ValueError("iCloud session expired. Please refresh your cookies.")
            raise ValueError(f"iCloud generation error: {err_msg}")

        email = gen_res["result"]["hme"]
        use_label = (label or "").strip() or f"Mail {random.randint(100, 99999)}"
        use_note = note or "Created via API"

        res_res = await self.client.reserve_email(email, label=use_label, note=use_note)
        if not res_res or not res_res.get("success"):
            err_msg = _extract_icloud_error(res_res, "iCloud reserve failed")
            if any(x in err_msg.lower() for x in ["maximum number", "limit of addresses", "reached the limit"]):
                raise ValueError("Maximum address quota reached on iCloud (750).")
            raise ValueError(f"iCloud reservation error: {err_msg}")

        pool_manager.gen_timestamps.append(time.time())

        # Extract anonymousId
        result_obj = res_res.get("result", {})
        anon_id = ""
        if isinstance(result_obj, dict):
            hme_obj = result_obj.get("hme")
            if isinstance(hme_obj, dict):
                anon_id = hme_obj.get("anonymousId", "")
            if not anon_id:
                anon_id = result_obj.get("anonymousId", "")
        if not anon_id:
            anon_id = email.split("@")[0]

        new_entry = {
            "anonymousId": anon_id,
            "label": use_label,
            "note": use_note,
            "hme": email,
            "isActive": True,
            "createTimestamp": int(time.time() * 1000),
        }
        self.emails.insert(0, new_entry)
        password_manager.last_assigned_email = email
        self._log("mail_generated", f"{email} ({use_label})")

        return {
            "anonymousId": anon_id,
            "email": email,
            "label": use_label,
            "created_at": time.time(),
        }

    # ----------------------------------------------------------- State & Logs
    def public_state(self) -> Dict[str, Any]:
        cookie_path = self.find_cookie_file()
        has_cookies = bool(cookie_path) or bool(self.client.cookies)
        total_count = len(self.emails)

        pool_count = sum(1 for e in self.emails if match_pool_slot(e.get("label", "")) is not None)
        active_count = sum(1 for e in self.emails if e.get("isActive") and match_pool_slot(e.get("label", "")) is None)
        inactive_count = sum(1 for e in self.emails if not e.get("isActive") and match_pool_slot(e.get("label", "")) is None)

        return {
            "is_connected": self.is_connected,
            "has_cookies": has_cookies,
            "forward_email": self.forward_email,
            "dsid": self.client.dsid,
            "partition": self.client.partition,
            "total_emails": total_count,
            "active_emails": active_count,
            "inactive_emails": inactive_count,
            "pool_emails": pool_count,
            "max_capacity": 750,
            "available_capacity": max(0, 750 - total_count),
            "proxy": self.client.proxy,
            "list_error": self.list_error,
            "last_refresh": self.last_refresh,
            "manual_job": {
                "active": self.manual_job_active,
                "target": self.manual_job_target,
                "done": self.manual_job_done,
                "status": self.manual_job_status,
                "message": self.manual_job_message,
            },
            "pool": pool_manager.public_state(),
        }

    def _log(self, event: str, detail: str = ""):
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(LOGS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{ts},{event},{detail}\n")
        except Exception:
            pass

    def read_logs(self, limit: int = 200) -> List[Dict[str, str]]:
        if not os.path.exists(LOGS_FILE):
            return []
        try:
            with open(LOGS_FILE, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            records = []
            for line in lines[-limit:]:
                parts = line.split(",", 2)
                records.append({
                    "time": parts[0] if len(parts) > 0 else "",
                    "event": parts[1] if len(parts) > 1 else "",
                    "detail": parts[2] if len(parts) > 2 else "",
                })
            records.reverse()
            return records
        except Exception:
            return []


account_manager = AccountManager()
