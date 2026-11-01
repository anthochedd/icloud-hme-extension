"""Pool manager: maintains a constant reserve of 10 ready-to-assign iCloud emails (pool1..pool10).

Features:
  - Slots 1 through 10 labeled directly on iCloud as pool1, pool2, ..., pool10.
  - Automatically launches at program startup and reconciles with iCloud:
      * Adopts existing pool1..pool10 from iCloud into DB (no duplicate creations).
      * Identifies missing slots and replenishes them in the background.
  - Instant claim: pops available pool slot and calls iCloud updateMetaData (latency depends on Apple).
  - Rate limiting & human pacing: 600-1200s between consecutive creations, max 4/hour.
  - Detailed activity logging for all operations (scan, adopt, create, claim, pacing, cooldown).
  - Persistent storage in the private data directory (pool.json).
"""

import asyncio
import json
import os
import random
import re
import time
from typing import List, Dict, Optional, Any, Tuple

from .config import POOL_FILE, config
from .icloud_client import HideMyEmail


def match_pool_slot(label: str) -> Optional[int]:
    """Matches labels like pool1..pool10, Pool 1..Pool 10, [Reserve] #1, etc."""
    if not label:
        return None
    cleaned = label.strip()
    # Direct match: pool1 .. pool10 (case-insensitive, optional space or dash)
    m = re.match(r"^pool[\s_-]?(\d+)$", cleaned, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 10:
            return val
    # Match [Reserve] #1 .. #10
    m2 = re.match(r"^\[(?:reserve|pool)\]\s*#?(\d+)", cleaned, re.IGNORECASE)
    if m2:
        val = int(m2.group(1))
        if 1 <= val <= 10:
            return val
    return None


class PoolManager:
    def __init__(self):
        self.slots: Dict[str, Dict[str, Any]] = {}  # "1" -> {"slot": 1, "label": "pool1", ...}
        self.ready: List[Dict[str, Any]] = []
        self.claimed: List[Dict[str, Any]] = []
        self.gen_timestamps: List[float] = []
        self.rate_limit_cooldown_until: float = 0.0

        self.status = "idle"  # idle | replenishing | cooldown | error
        self.status_message = "Ready"
        self.lock = asyncio.Lock()
        self._replenish_task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()
        self.on_email_created_cb = None
        self.on_email_claimed_cb = None

        self.load()

    # ----------------------------------------------------------- Persistence
    def load(self):
        if os.path.exists(POOL_FILE):
            try:
                with open(POOL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.slots = data.get("slots", {})
                    # Backward compatibility if slots is empty but ready had items
                    if not self.slots and data.get("ready"):
                        for idx, item in enumerate(data.get("ready", []), start=1):
                            if idx <= 10:
                                slot_num = match_pool_slot(item.get("label", "")) or idx
                                self.slots[str(slot_num)] = {
                                    "slot": slot_num,
                                    "label": f"pool{slot_num}",
                                    "anonymousId": item.get("anonymousId"),
                                    "hme": item.get("hme"),
                                    "created_at": item.get("created_at", time.time()),
                                }
                    self.claimed = data.get("claimed", [])
                    self.gen_timestamps = data.get("gen_timestamps", [])
                    self.rate_limit_cooldown_until = data.get("rate_limit_cooldown_until", 0.0)
            except Exception:
                self.slots = {}
                self.claimed = []
                self.gen_timestamps = []
                self.rate_limit_cooldown_until = 0.0
        else:
            self.slots = {}
            self.claimed = []
            self.gen_timestamps = []
            self.rate_limit_cooldown_until = 0.0

        self.ready = [self.slots[k] for k in sorted(self.slots.keys(), key=int)]

    def save(self):
        tmp_file = f"{POOL_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "target": 10,
                    "slots": self.slots,
                    "ready": self.ready,
                    "claimed": self.claimed[-50:],  # keep last 50 claimed
                    "gen_timestamps": self.gen_timestamps,
                    "rate_limit_cooldown_until": self.rate_limit_cooldown_until,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        os.replace(tmp_file, POOL_FILE)

    # ----------------------------------------------------------- Reconciliation
    def sync_with_icloud(self, icloud_emails: List[Dict[str, Any]], log_func=None) -> Dict[str, Any]:
        """Scans iCloud emails to recognize existing pool1..pool10 addresses.
        Adopts existing ones into the DB, clears deleted or renamed ones.
        """
        active_in_icloud: Dict[int, Dict[str, Any]] = {}
        for e in icloud_emails:
            if not e.get("isActive", True):
                continue
            slot_num = match_pool_slot(e.get("label", ""))
            if slot_num and slot_num not in active_in_icloud:
                active_in_icloud[slot_num] = {
                    "slot": slot_num,
                    "label": f"pool{slot_num}",
                    "anonymousId": e.get("anonymousId"),
                    "hme": e.get("hme"),
                    "created_at": (
                        e.get("createTimestamp", 0) / 1000.0
                        if e.get("createTimestamp")
                        else time.time()
                    ),
                }

        # Adopt into self.slots
        for slot_num, info in active_in_icloud.items():
            k = str(slot_num)
            if k not in self.slots or self.slots[k].get("anonymousId") != info["anonymousId"]:
                self.slots[k] = info
                if log_func:
                    log_func(
                        "pool_adopt",
                        f"pool{slot_num} ({info['hme']}) found on iCloud and synchronized into DB",
                    )

        # Clear slots that no longer exist with pool label in iCloud
        for k in list(self.slots.keys()):
            if int(k) not in active_in_icloud:
                del self.slots[k]
                if log_func:
                    log_func("pool_slot_vacated", f"Slot pool{k} is no longer active under this name on iCloud")

        self.ready = [self.slots[k] for k in sorted(self.slots.keys(), key=int)]

        # Purge any claimed emails that are no longer present on iCloud
        self.filter_claimed_against_alive(icloud_emails)

        self.save()

        found = sorted([int(k) for k in self.slots.keys()])
        missing = [i for i in range(1, 11) if str(i) not in self.slots]

        if log_func:
            log_func(
                "pool_scan",
                f"{len(found)}/10 pool ready on iCloud ({', '.join(f'pool{s}' for s in found) or 'none'}). "
                f"Missing: {', '.join(f'pool{s}' for s in missing) or 'none'}.",
            )

        # If there are missing slots, wake up the replenishment worker
        if missing:
            self.wake_replenish()

        return {
            "found_count": len(found),
            "found_slots": found,
            "missing_slots": missing,
        }

    def filter_claimed_against_alive(self, alive_emails: List[Dict[str, Any]]):
        """Purges claimed history of addresses that were deleted from iCloud."""
        if not alive_emails:
            return
        alive_ids = {e.get("anonymousId") for e in alive_emails if e.get("anonymousId")}
        alive_hmes = {e.get("hme") for e in alive_emails if e.get("hme")}
        before_len = len(self.claimed)
        self.claimed = [
            c for c in self.claimed
            if (c.get("anonymousId") and c.get("anonymousId") in alive_ids)
            or (c.get("hme") and c.get("hme") in alive_hmes)
        ]
        if len(self.claimed) != before_len:
            self.save()

    def remove_claimed_emails(self, identifiers: List[str]):
        """Explicitly purges claimed history by anonymousId or email address."""
        if not identifiers:
            return
        id_set = {str(x).strip().lower() for x in identifiers if x}
        before_len = len(self.claimed)
        self.claimed = [
            c for c in self.claimed
            if str(c.get("anonymousId", "")).strip().lower() not in id_set
            and str(c.get("hme", "")).strip().lower() not in id_set
        ]
        if len(self.claimed) != before_len:
            self.save()

    # ----------------------------------------------------------- Rate Limiting
    def gen_in_last_hour(self) -> int:
        cutoff = time.time() - 3600
        self.gen_timestamps = [t for t in self.gen_timestamps if t > cutoff]
        return len(self.gen_timestamps)

    def can_generate(self) -> Tuple[bool, Optional[float]]:
        """Checks rolling hourly limit (strictly max 4 / hour) and safety cooldown. Returns (allowed, wait_seconds_if_not)."""
        now = time.time()
        if self.rate_limit_cooldown_until > now:
            wait = self.rate_limit_cooldown_until - now
            return False, max(wait, 60.0)

        limit = config.data.get("hourly_limit", 4)
        current = self.gen_in_last_hour()
        if current >= limit and self.gen_timestamps:
            oldest = min(self.gen_timestamps)
            wait = max(60.0, 3600.0 - (now - oldest))
            return False, wait
        return True, None

    # ----------------------------------------------------------- Public State
    def public_state(self, alive_emails: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        target = 10
        hourly_limit = config.data.get("hourly_limit", 4)
        can_gen, wait = self.can_generate()

        slots_dict = {str(k): v for k, v in self.slots.items()}
        ready_items = [self.slots[k] for k in sorted(self.slots.keys(), key=int)]

        claimed_list = self.claimed
        if alive_emails is not None:
            alive_ids = {e.get("anonymousId") for e in alive_emails if e.get("anonymousId")}
            alive_hmes = {e.get("hme") for e in alive_emails if e.get("hme")}
            claimed_list = [
                c for c in self.claimed
                if (c.get("anonymousId") and c.get("anonymousId") in alive_ids)
                or (c.get("hme") and c.get("hme") in alive_hmes)
            ]

        return {
            "ready_count": len(self.slots),
            "target": target,
            "status": self.status,
            "message": self.status_message,
            "hourly_count": self.gen_in_last_hour(),
            "hourly_limit": hourly_limit,
            "cooldown_seconds": int(wait) if wait else None,
            "slots": slots_dict,
            "ready_items": ready_items,
            "recent_claimed": claimed_list[-10:],
        }

    # ----------------------------------------------------------- Claim (Instant)
    async def claim_email(
        self, client: HideMyEmail, label: str, note: str = "", log_func=None
    ) -> Dict[str, Any]:
        """Pops lowest available pool slot (e.g. pool1) and renames it in iCloud via updateMetaData."""
        async with self.lock:
            available_slots = sorted([int(k) for k in self.slots.keys()])
            if not available_slots:
                can_gen, wait = self.can_generate()
                wait_text = f" in ~{int(wait // 60)} min" if wait else ""
                msg = f"Reserve pool temporarily empty (0/10). Replenishment in progress{wait_text}."
                if log_func:
                    log_func("pool_claim_empty", msg)
                return {
                    "success": False,
                    "error": "pool_depleted",
                    "message": msg,
                }

            claim_slot = available_slots[0]
            item = self.slots[str(claim_slot)]

        use_label = (label or "").strip() or f"Assigned {time.strftime('%Y-%m-%d %H:%M')}"
        use_note = note or "Assigned via Chrome Extension (v3)"

        try:
            update_res = await client.update_metadata(
                anonymous_id=item["anonymousId"],
                label=use_label,
                note=use_note,
            )
        except Exception as e:
            if log_func:
                log_func("pool_claim_error", f"iCloud error for pool{claim_slot}: {e}")
            return {
                "success": False,
                "error": "icloud_update_error",
                "message": f"Error communicating with iCloud: {e}",
            }

        if update_res and update_res.get("error"):
            err_msg = update_res.get("reason") or str(update_res.get("error"))
            if log_func:
                log_func("pool_claim_error", f"iCloud rejected renaming pool{claim_slot}: {err_msg}")
            return {
                "success": False,
                "error": "icloud_error",
                "message": f"iCloud rejected renaming: {err_msg}",
            }

        # Success: remove from slots and record into claimed
        async with self.lock:
            del self.slots[str(claim_slot)]
            self.ready = [self.slots[k] for k in sorted(self.slots.keys(), key=int)]

            claimed_record = {
                "slot": claim_slot,
                "original_label": f"pool{claim_slot}",
                "new_label": use_label,
                "anonymousId": item["anonymousId"],
                "hme": item["hme"],
                "claimed_at": time.time(),
            }
            self.claimed.append(claimed_record)
            self.save()

        if self.on_email_claimed_cb:
            try:
                self.on_email_claimed_cb(claimed_record)
            except Exception:
                pass

        if log_func:
            log_func(
                "pool_claim",
                f"Slot pool{claim_slot} ({item['hme']}) claimed and renamed to '{use_label}' ({len(self.slots)}/10 remaining)",
            )

        # Wake replenishment worker immediately so it fills the missing slot
        self.wake_replenish()

        return {
            "success": True,
            "email": item["hme"],
            "anonymousId": item["anonymousId"],
            "slot": claim_slot,
            "label": use_label,
            "remaining_pool": len(self.slots),
        }

    # ----------------------------------------------------------- Background Worker
    def start_worker(self, client: HideMyEmail, log_func=None):
        if self._replenish_task is None or self._replenish_task.done():
            self._replenish_task = asyncio.create_task(self._worker_loop(client, log_func))

    def stop_worker(self):
        if self._replenish_task and not self._replenish_task.done():
            self._replenish_task.cancel()

    def wake_replenish(self):
        self._wake_event.set()

    async def _sleep_with_sync(self, client: HideMyEmail, total_seconds: float, reason: str = ""):
        """Sleeps in short intervals (10-15s), refreshing iCloud session every ~300s, while updating status_message."""
        elapsed = 0.0
        last_sync = time.time()
        while elapsed < total_seconds:
            remaining = total_seconds - elapsed
            remaining_mins = max(1, int(remaining // 60))
            self.status_message = f"{reason} — resuming in ~{remaining_mins} min ({int(remaining)}s)"

            sleep_chunk = min(remaining, 15.0)
            await asyncio.sleep(sleep_chunk)
            elapsed += sleep_chunk

            # Sync session every 5 minutes to avoid cookie expiry
            if time.time() - last_sync >= 300.0 and client.cookies:
                try:
                    await client.sync()
                    last_sync = time.time()
                except Exception:
                    pass

    async def _worker_loop(self, client: HideMyEmail, log_func=None):
        """Monitors pool1..pool10 slots and replenishes any missing slot safely in the background."""
        last_generated_time = 0.0
        if self.gen_timestamps:
            last_generated_time = max(self.gen_timestamps)

        if log_func:
            log_func("pool_worker_start", "Pool worker started on launch")

        while True:
            try:
                missing_slots = [i for i in range(1, 11) if str(i) not in self.slots]

                if not missing_slots:
                    self.status = "idle"
                    self.status_message = "Reserve full (10/10 ready: pool1 to pool10)"
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=60.0)
                        self._wake_event.clear()
                    except asyncio.TimeoutError:
                        pass
                    continue

                target_slot = missing_slots[0]

                # Check if client has cookies
                if not client.cookies:
                    self.status = "error"
                    self.status_message = "Waiting for iCloud cookies..."
                    await asyncio.sleep(15.0)
                    continue

                # 1. Check application hourly limit and Apple cooldown
                can_gen, wait = self.can_generate()
                if not can_gen and wait:
                    self.status = "cooldown"
                    mins = int(wait // 60) + 1
                    self.status_message = (
                        f"Hourly limit reached ({self.gen_in_last_hour()}/4). Resuming in ~{mins} min."
                    )
                    if log_func:
                        log_func(
                            "pool_cooldown",
                            f"Hourly quota reached (max 4/h). Safety cooldown of {int(wait)}s (~{mins} min) before pool{target_slot}...",
                        )
                    await self._sleep_with_sync(client, wait, reason="Hourly quota reached (max 4/h)")
                    continue

                # 2. Human pacing between consecutive email creations: 10 to 20 minutes (600s - 1200s)
                min_delay = config.data.get("gen_delay_min", 600)
                max_delay = config.data.get("gen_delay_max", 1200)
                time_since_last = time.time() - last_generated_time
                if last_generated_time > 0 and time_since_last < min_delay:
                    target_delay = random.randint(min_delay, max_delay)
                    wait_needed = max(0.0, target_delay - time_since_last)
                    if wait_needed > 0:
                        self.status = "replenishing"
                        mins = max(1, int(wait_needed // 60))
                        if log_func:
                            log_func(
                                "pool_pacing",
                                f"Human-like pause of {int(wait_needed)}s (~{mins} min) before generating pool{target_slot} ({len(self.slots)}/10 ready)",
                            )
                        await self._sleep_with_sync(
                            client, wait_needed, reason=f"Safety pause before pool{target_slot}"
                        )

                # 3. Perform email creation
                self.status = "replenishing"
                self.status_message = f"Generating pool{target_slot} on iCloud…"
                if log_func:
                    log_func("pool_generating", f"Generating pool{target_slot} on iCloud...")

                success, email_data = await self._generate_one_temp(client, target_slot)

                if success and email_data:
                    now_t = time.time()
                    async with self.lock:
                        self.slots[str(target_slot)] = email_data
                        self.ready = [self.slots[k] for k in sorted(self.slots.keys(), key=int)]
                        self.gen_timestamps.append(now_t)
                        last_generated_time = now_t
                        self.save()

                    if self.on_email_created_cb:
                        try:
                            self.on_email_created_cb(email_data)
                        except Exception:
                            pass

                    if log_func:
                        log_func(
                            "pool_generated",
                            f"pool{target_slot} successfully created: {email_data['hme']} ({len(self.slots)}/10 ready)",
                        )
                    self.status_message = f"Added: pool{target_slot} ({email_data['hme']})"
                else:
                    err = email_data.get("error", "Failed") if isinstance(email_data, dict) else "Failed"
                    err_str = str(err).lower()
                    is_rate_limited = any(
                        x in err_str
                        for x in [
                            "limit of addresses",
                            "reached the limit",
                            "try again later",
                            "too many",
                            "maximum number",
                            "rate limit",
                            "throttled",
                        ]
                    )

                    if is_rate_limited:
                        # 1 hour safety pause (3600 seconds)
                        self.rate_limit_cooldown_until = time.time() + 3600.0
                        self.status = "cooldown"
                        self.status_message = "Apple quota reached: 1 hour safety cooldown (3600s)…"
                        self.save()
                        if log_func:
                            log_func(
                                "pool_cooldown",
                                f"Apple limit reached for pool{target_slot}: {err}. Mandatory safety cooldown of 1 hour (3600s).",
                            )
                        await self._sleep_with_sync(client, 3600.0, reason="Apple quota (1h pause)")
                    else:
                        # Other errors: wait 10 minutes (600s), NOT 60s
                        self.status = "error"
                        self.status_message = f"Error pool{target_slot}: {err}. Pausing 10 min (600s)…"
                        if log_func:
                            log_func(
                                "pool_error",
                                f"Failed to create pool{target_slot}: {err}. Pausing 10 min (600s).",
                            )
                        await self._sleep_with_sync(client, 600.0, reason=f"Error pool{target_slot}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.status = "error"
                self.status_message = f"Pool error: {e}"
                if log_func:
                    log_func("pool_exception", str(e))
                await asyncio.sleep(60.0)

    async def _generate_one_temp(
        self, client: HideMyEmail, slot_num: int
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Generates and reserves a single temporary email named pool{slot_num} on iCloud."""
        try:
            await client.sync()
            gen_res = await client.generate_email()

            if not gen_res or not gen_res.get("success"):
                err_msg = (
                    gen_res.get("reason")
                    or (gen_res.get("error", {}) if isinstance(gen_res.get("error"), dict) else {}).get(
                        "errorMessage"
                    )
                    or "iCloud generate failed"
                )
                return False, {"error": err_msg}

            email = gen_res["result"]["hme"]
            pool_label = f"pool{slot_num}"

            res_res = await client.reserve_email(
                email=email,
                label=pool_label,
                note=f"Temporary reserve email pool{slot_num}",
            )

            if not res_res or not res_res.get("success"):
                err_msg = (
                    res_res.get("reason")
                    or (res_res.get("error", {}) if isinstance(res_res.get("error"), dict) else {}).get(
                        "errorMessage"
                    )
                    or "iCloud reserve failed"
                )
                return False, {"error": err_msg}

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

            return True, {
                "slot": slot_num,
                "label": pool_label,
                "anonymousId": anon_id,
                "hme": email,
                "created_at": time.time(),
            }
        except Exception as e:
            return False, {"error": str(e)}


pool_manager = PoolManager()
