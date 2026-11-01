"""API Keys management for extension and external integrations."""

import hashlib
import json
import os
import secrets
import time
from typing import List, Dict, Optional, Any

from .config import API_KEYS_FILE


class ApiKeyManager:
    def __init__(self):
        self.keys: List[Dict[str, Any]] = []
        self.load()

    def load(self):
        if os.path.exists(API_KEYS_FILE):
            try:
                with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
                    self.keys = json.load(f)
            except Exception:
                self.keys = []
        else:
            self.keys = []

    def save(self):
        tmp_file = f"{API_KEYS_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.keys, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, API_KEYS_FILE)

    def _hash_key(self, raw_key: str) -> str:
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    def create_key(self, name: str) -> Dict[str, Any]:
        """Creates a new API key. Returns the raw key string once."""
        raw_token = secrets.token_hex(20)
        raw_key = f"ihme_live_{raw_token}"
        key_id = secrets.token_hex(8)
        prefix = raw_key[:14] + "..."

        key_record = {
            "id": key_id,
            "name": name.strip() or "Chrome Extension",
            "prefix": prefix,
            "hash": self._hash_key(raw_key),
            "created_at": time.time(),
            "last_used_at": None,
        }
        self.keys.append(key_record)
        self.save()

        return {
            "id": key_id,
            "name": key_record["name"],
            "key": raw_key,
            "prefix": prefix,
            "created_at": key_record["created_at"],
        }

    def list_keys(self) -> List[Dict[str, Any]]:
        """Return key metadata without exposing secret values."""
        self.load()
        return [
            {
                "id": k["id"],
                "name": k["name"],
                "prefix": k["prefix"],
                "created_at": k["created_at"],
                "last_used_at": k.get("last_used_at"),
            }
            for k in self.keys
        ]

    def delete_key(self, key_id: str) -> bool:
        self.load()
        initial_len = len(self.keys)
        self.keys = [k for k in self.keys if k["id"] != key_id]
        if len(self.keys) < initial_len:
            self.save()
            return True
        return False

    def validate_key(self, raw_key: Optional[str]) -> bool:
        if not raw_key:
            return False
        self.load()
        h = self._hash_key(raw_key)
        for k in self.keys:
            if secrets.compare_digest(k["hash"], h):
                k["last_used_at"] = time.time()
                self.save()
                return True
        return False


api_keys = ApiKeyManager()
