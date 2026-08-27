import logging
import aiohttp

logger = logging.getLogger("guardian")

from platforms.base import Platform, PlatformRules, AvailabilityResult

ENDPOINT = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


class DiscordPlatform(Platform):
    def get_rules(self) -> PlatformRules:
        return PlatformRules(
            platform_name="Discord",
            minimum_length=2,
            maximum_length=32,
            allowed_characters="lowercase letters, numbers, periods, underscores",
            allowed_characters_pattern=r"^[a-z0-9._]+$",
            case_sensitive=False,
            description="Discord usernames: 2-32 chars. Checked via unauthenticated availability endpoint.",
        )

    async def check_availability(self, username: str, session: aiohttp.ClientSession, timeout: int = 10) -> AvailabilityResult:
        if not self.validate_username(username):
            return AvailabilityResult(username=username, status="INVALID", platform="Discord", message="Invalid format")

        try:
            async with session.post(
                ENDPOINT,
                json={"username": username},
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                status_code = resp.status
                body = await resp.text()
                logger.debug("DISCORD %s: HTTP %d | %s", username, status_code, body[:150])

                if status_code in (200, 201, 204):
                    try:
                        import json
                        data = json.loads(body)
                    except Exception:
                        data = {}
                    taken = data.get("taken", True)
                    if taken:
                        return AvailabilityResult(username=username, status="TAKEN", platform="Discord")
                    else:
                        return AvailabilityResult(username=username, status="AVAILABLE", platform="Discord",
                                                  profile_url=f"https://discord.com/users/{username}")
                elif status_code == 429:
                    retry_after = 5
                    try:
                        import json
                        data = json.loads(body)
                        retry_after = data.get("retry_after", 5)
                    except Exception:
                        pass
                    return AvailabilityResult(username=username, status="RATE_LIMITED", platform="Discord",
                                              message=f"Retry after {retry_after}s")
                elif status_code == 400:
                    return AvailabilityResult(username=username, status="INVALID", platform="Discord",
                                              message="HTTP 400 - invalid username")
                elif status_code == 403:
                    return AvailabilityResult(username=username, status="UNKNOWN", platform="Discord",
                                              message="HTTP 403 - access blocked")
                else:
                    return AvailabilityResult(username=username, status="UNKNOWN", platform="Discord",
                                              message=f"HTTP {status_code}")
        except aiohttp.ClientError as e:
            logger.debug("DISCORD CONN_ERROR: %s - %s", username, str(e)[:100])
            return AvailabilityResult(username=username, status="ERROR", platform="Discord", message="Connection error")
        except Exception as e:
            logger.debug("DISCORD EXCEPTION: %s - %s: %s", username, type(e).__name__, str(e)[:100])
            return AvailabilityResult(username=username, status="ERROR", platform="Discord", message=str(e)[:100])

    def get_profile_url(self, username: str) -> str:
        return f"https://discord.com/users/{username}"

    def diagnose_url(self, username: str) -> str:
        return ENDPOINT
