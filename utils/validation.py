import re


def is_valid_webhook_url(url: str) -> bool:
    pattern = r"^https://(discord\.com|discordapp\.com)/api/webhooks/\d+/[\w-]+$"
    return bool(re.match(pattern, url))


def mask_webhook_url(url: str) -> str:
    if not url:
        return ""
    parts = url.split("/")
    if len(parts) >= 2:
        token = parts[-1]
        masked = token[:4] + "*" * (len(token) - 8) + token[-4:] if len(token) > 8 else "****"
        return "/".join(parts[:-1]) + "/" + masked
    return "****"
