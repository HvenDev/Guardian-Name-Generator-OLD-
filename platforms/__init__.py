from platforms.base import Platform, AvailabilityResult, PlatformRules
from platforms.discord import DiscordPlatform

PLATFORMS = {
    "Discord": DiscordPlatform,
}

__all__ = ["Platform", "PLATFORMS", "DiscordPlatform"]
