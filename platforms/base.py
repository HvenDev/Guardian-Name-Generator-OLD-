import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("guardian")


@dataclass
class PlatformRules:
    platform_name: str
    minimum_length: int
    maximum_length: int
    allowed_characters: str
    allowed_characters_pattern: str
    case_sensitive: bool
    description: str


@dataclass
class AvailabilityResult:
    username: str
    status: str  # AVAILABLE, TAKEN, INVALID, RATE_LIMITED, UNKNOWN, ERROR
    platform: str
    profile_url: Optional[str] = None
    message: Optional[str] = None


class Platform(ABC):

    @abstractmethod
    def get_rules(self) -> PlatformRules:
        pass

    @abstractmethod
    async def check_availability(self, username: str, session, timeout: int = 10) -> AvailabilityResult:
        pass

    def validate_username(self, username: str) -> bool:
        rules = self.get_rules()
        if len(username) < rules.minimum_length or len(username) > rules.maximum_length:
            return False
        if not re.match(rules.allowed_characters_pattern, username):
            return False
        return True

    def get_profile_url(self, username: str) -> Optional[str]:
        return None

    def diagnose_url(self, username: str) -> str:
        return ""
