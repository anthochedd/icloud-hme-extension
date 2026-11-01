"""Configuration and authentication management for v3."""

import hashlib
import json
import os
import secrets
import time
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.getenv("IHME_DATA_DIR", os.path.join(BASE_DIR, "data")))
ROOT_COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")
DATA_COOKIE_FILE = os.path.join(DATA_DIR, "cookies.txt")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
API_KEYS_FILE = os.path.join(DATA_DIR, "api_keys.json")
POOL_FILE = os.path.join(DATA_DIR, "pool.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.txt")

os.makedirs(DATA_DIR, exist_ok=True)


class ConfigManager:
    def __init__(self):
        self._active_sessions: Dict[str, float] = {}  # token -> expiry_timestamp
        self._session_duration = 7 * 24 * 3600  # 7 days
        self.load()

    def default_config(self) -> Dict[str, Any]:
        return {
            "password_hash": "",
            "password_salt": "",
            "server_url": "",
            "onboarding_complete": False,
            "pool_target": 10,
            "gen_delay_min": 600,   # 10 minutes
            "gen_delay_max": 1200,  # 20 minutes
            "hourly_limit": 4,      # max 4 mails/hour
        }

    def load(self) -> Dict[str, Any]:
        if not os.path.exists(CONFIG_FILE):
            self.data = self.default_config()
            self.save()
        else:
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (OSError, ValueError) as exc:
                raise RuntimeError("Cannot read config.json; restore it before starting.") from exc
        return self.data

    def save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp_file = f"{CONFIG_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, CONFIG_FILE)

    # ----------------------------------------------------------- Password & Auth
    def is_initialized(self) -> bool:
        """Returns True if admin password has already been set."""
        return bool(self.data.get("password_hash"))

    def _hash_pwd(self, password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
        ).hex()

    def set_password(self, password: str):
        salt = secrets.token_hex(16)
        pwd_hash = self._hash_pwd(password, salt)
        self.data["password_salt"] = salt
        self.data["password_hash"] = pwd_hash
        self.save()

    def verify_password(self, password: str) -> bool:
        salt = self.data.get("password_salt", "")
        stored_hash = self.data.get("password_hash", "")
        if not salt or not stored_hash:
            return False
        return secrets.compare_digest(self._hash_pwd(password, salt), stored_hash)


    # ----------------------------------------------------------- Sessions
    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        expiry = time.time() + self._session_duration
        self._active_sessions[token] = expiry
        return token

    def verify_session(self, token: Optional[str]) -> bool:
        if not token:
            return False
        expiry = self._active_sessions.get(token)
        if not expiry:
            return False
        if time.time() > expiry:
            self._active_sessions.pop(token, None)
            return False
        return True

    def revoke_session(self, token: Optional[str]):
        if token in self._active_sessions:
            del self._active_sessions[token]

    # ----------------------------------------------------------- Settings
    def get_settings(self) -> Dict[str, Any]:
        return {
            "is_initialized": self.is_initialized(),
            "server_url": self.data.get("server_url", ""),
            "onboarding_complete": self.data.get("onboarding_complete", False),
            "pool_target": 10,
            "gen_delay_min": 600,
            "gen_delay_max": 1200,
            "hourly_limit": 4,
        }


config = ConfigManager()
