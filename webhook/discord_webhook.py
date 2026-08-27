import requests
import json
from utils.validation import is_valid_webhook_url, mask_webhook_url
from utils.logging import log_event


class DiscordWebhook:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.masked_url = mask_webhook_url(webhook_url)

    def test_webhook(self) -> tuple[bool, str]:
        if not is_valid_webhook_url(self.webhook_url):
            return False, "Invalid webhook URL format"

        try:
            payload = {
                "content": "**GUARDIAN** - Webhook test successful.",
                "username": "GUARDIAN",
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code == 204 or resp.status_code == 200:
                log_event(f"Webhook test successful: {self.masked_url}")
                return True, "Webhook connection successful"
            else:
                return False, f"Webhook returned status {resp.status_code}"
        except requests.exceptions.Timeout:
            return False, "Webhook connection timed out"
        except requests.exceptions.ConnectionError:
            return False, "Could not connect to Discord webhook"
        except Exception as e:
            return False, f"Webhook error: {str(e)}"

    def send_scan_results(self, platform_name: str, length: int, checked: int,
                          available_count: int, taken: int, invalid: int,
                          unknown: int, available_usernames: list) -> bool:
        if not self.webhook_url:
            return False

        available_list = "\n".join(available_usernames[:50]) if available_usernames else "None found"

        embed = {
            "title": "GUARDIAN - Scan Complete",
            "color": 0x00FF00 if available_count > 0 else 0xFF0000,
            "fields": [
                {"name": "Service", "value": platform_name, "inline": True},
                {"name": "Length", "value": str(length), "inline": True},
                {"name": "Checked", "value": f"{checked:,}", "inline": True},
                {"name": "Available", "value": f"{available_count:,}", "inline": True},
                {"name": "Taken", "value": f"{taken:,}", "inline": True},
                {"name": "Invalid", "value": f"{invalid:,}", "inline": True},
                {"name": "Unknown", "value": f"{unknown:,}", "inline": True},
                {"name": "Available Usernames", "value": f"```\n{available_list}\n```", "inline": False},
            ],
            "footer": {"text": "GUARDIAN v1.0 - Username Research Tool"},
        }

        try:
            payload = {"embeds": [embed], "username": "GUARDIAN"}
            resp = requests.post(self.webhook_url, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                log_event("Scan results sent to Discord webhook")
                return True
            elif resp.status_code == 429:
                return False
            else:
                return False
        except Exception as e:
            log_event(f"Webhook send failed: {str(e)}", "error")
            return False

    def send_message(self, content: str) -> bool:
        if not self.webhook_url:
            return False
        try:
            payload = {"content": content, "username": "GUARDIAN"}
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code in (200, 204)
        except Exception:
            return False
