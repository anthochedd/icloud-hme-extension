"""Password generation, storage, and association management for iCloud Hide-My-Email v3."""

import json
import os
import secrets
import string
import time
from typing import Dict, Any, Optional

from .config import DATA_DIR
PASSWORDS_FILE = os.path.join(DATA_DIR, "passwords.json")

os.makedirs(DATA_DIR, exist_ok=True)

# Allowed special characters for generated passwords
SPECIAL_CHARS = "!?&@#$%*-_"


def generate_secure_password(length: int = 18) -> str:
    """Generates a secure, high-entropy password with uppercase, lowercase, numbers, and special chars."""
    if length < 12:
        length = 12

    uppers = string.ascii_uppercase
    lowers = string.ascii_lowercase
    digits = string.digits
    specials = SPECIAL_CHARS

    # Guarantee at least two characters from each category
    guaranteed = [
        secrets.choice(uppers),
        secrets.choice(uppers),
        secrets.choice(lowers),
        secrets.choice(lowers),
        secrets.choice(digits),
        secrets.choice(digits),
        secrets.choice("!?&"),  # include a common special character
        secrets.choice(specials),
    ]

    all_chars = uppers + lowers + digits + specials
    remaining = [secrets.choice(all_chars) for _ in range(length - len(guaranteed))]
    password_list = guaranteed + remaining

    # Cryptographically secure shuffle
    rng = secrets.SystemRandom()
    rng.shuffle(password_list)
    return "".join(password_list)


class PasswordManager:
    def __init__(self):
        self.passwords: Dict[str, Dict[str, Any]] = {}  # normalized_email -> entry
        self.last_assigned_email: Optional[str] = None
        self.load()

    def load(self):
        if not os.path.exists(PASSWORDS_FILE):
            self.passwords = {}
            self.save()
            return

        try:
            with open(PASSWORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self.passwords = data.get("passwords", {})
                    self.last_assigned_email = data.get("last_assigned_email")
                else:
                    self.passwords = {}
        except Exception:
            self.passwords = {}

    def save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = f"{PASSWORDS_FILE}.tmp"
        payload = {
            "last_assigned_email": self.last_assigned_email,
            "passwords": self.passwords,
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, PASSWORDS_FILE)

    def _normalize(self, ident: str) -> str:
        return (ident or "").strip().lower()

    def get_password(self, email_or_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves password entry by email address or anonymousId."""
        target = self._normalize(email_or_id)
        if not target:
            return None

        # 1. Direct email match
        if target in self.passwords:
            return self.passwords[target]

        # 2. Match by anonymousId or case-insensitive search
        for k, v in self.passwords.items():
            if self._normalize(k) == target:
                return v
            if self._normalize(v.get("anonymousId", "")) == target:
                return v
            if self._normalize(v.get("email", "")) == target:
                return v

        return None

    def get_password_by_site(self, site: str) -> Optional[Dict[str, Any]]:
        """Finds password entry associated with a domain or site name."""
        target = self._normalize(site)
        if not target:
            return None

        for v in reversed(list(self.passwords.values())):
            entry_site = self._normalize(v.get("site", ""))
            if entry_site and (entry_site in target or target in entry_site):
                return v
        return None

    def set_password(
        self,
        email: str,
        password: str,
        anonymous_id: str = "",
        site: str = "",
        label: str = "",
    ) -> Dict[str, Any]:
        """Sets or updates password for an email address."""
        norm_email = self._normalize(email)
        if not norm_email:
            raise ValueError("Email address cannot be empty.")

        now = time.time()
        existing = self.get_password(norm_email) or {}

        entry = {
            "email": email.strip(),
            "anonymousId": anonymous_id.strip() or existing.get("anonymousId", ""),
            "password": password.strip(),
            "site": site.strip() or existing.get("site", ""),
            "label": label.strip() or existing.get("label", ""),
            "created_at": existing.get("created_at", now),
            "updated_at": now,
        }

        self.passwords[norm_email] = entry
        self.last_assigned_email = norm_email
        self.save()
        return entry

    def generate_and_set(
        self,
        email: str,
        anonymous_id: str = "",
        site: str = "",
        label: str = "",
        length: int = 18,
    ) -> Dict[str, Any]:
        """Generates a secure password and associates it with the email."""
        pwd = generate_secure_password(length)
        return self.set_password(
            email=email,
            password=pwd,
            anonymous_id=anonymous_id,
            site=site,
            label=label,
        )

    def delete_password(self, email_or_id: str) -> bool:
        """Removes password association."""
        target = self._normalize(email_or_id)
        to_del = None
        for k, v in self.passwords.items():
            if self._normalize(k) == target or self._normalize(v.get("anonymousId", "")) == target:
                to_del = k
                break

        if to_del and to_del in self.passwords:
            del self.passwords[to_del]
            if self.last_assigned_email == to_del:
                self.last_assigned_email = list(self.passwords.keys())[-1] if self.passwords else None
            self.save()
            return True
        return False

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        return self.passwords


password_manager = PasswordManager()
