import json
import os
from typing import Any

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "webhook_url": "",
    "default_length": 4,
    "default_amount": 1000,
    "default_generation_mode": "Smart",
}


class Config:
    def __init__(self):
        self._config: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self._config = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._config = DEFAULT_CONFIG.copy()
        else:
            self._config = DEFAULT_CONFIG.copy()

    def _save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._config, f, indent=4)

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        self._config[key] = value
        self._save()

    def get_webhook_url(self) -> str:
        return self._config.get("webhook_url", "")

    def set_webhook_url(self, url: str):
        self._config["webhook_url"] = url
        self._save()

    def is_webhook_configured(self) -> bool:
        return bool(self._config.get("webhook_url", ""))
