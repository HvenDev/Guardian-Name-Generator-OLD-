import time
import asyncio
import logging
from typing import Callable, List
import aiohttp
from platforms.base import Platform, AvailabilityResult
from generator.generator import UsernameGenerator
from utils.terminal import (
    show_progress, show_results, show_error, show_banner,
    show_available_list, clear, console,
)

logger = logging.getLogger("guardian")


class Scanner:
    def __init__(self, platform: Platform, length: int, amount: int, charset: str,
                 generation_mode: str = "Smart", concurrency: int = 3,
                 request_timeout: int = 10, request_delay: float = 0.35):
        self.platform = platform
        self.length = length
        self.amount = amount
        self.charset = charset
        self.generation_mode = generation_mode
        self.concurrency = concurrency
        self.request_timeout = request_timeout
        self.request_delay = request_delay
        self.results: List[AvailabilityResult] = []
        self.available_usernames: List[str] = []
        self._running = False
        self._cancelled = False
        self._start_time = 0.0
        self._checked = 0
        self._available = 0
        self._taken = 0
        self._invalid = 0
        self._unknown = 0
        self._errors = 0
        self._last_display = 0.0

    async def _check_one(self, username: str, session: aiohttp.ClientSession,
                         semaphore: asyncio.Semaphore) -> AvailabilityResult:
        async with semaphore:
            try:
                await asyncio.sleep(self.request_delay)
                result = await self.platform.check_availability(
                    username, session, timeout=self.request_timeout
                )
                if result.status == "RATE_LIMITED":
                    retry_msg = result.message or ""
                    wait = 5.0
                    if "Retry after" in retry_msg:
                        try:
                            wait = float(retry_msg.split("Retry after ")[1].split("s")[0])
                            wait = min(wait, 60.0)
                        except Exception:
                            wait = 5.0
                    logger.debug("RATE_LIMITED on %s, waiting %.1fs then retrying", username, wait)
                    await asyncio.sleep(wait)
                    result = await self.platform.check_availability(
                        username, session, timeout=self.request_timeout
                    )
                return result
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("CHECK_EXCEPTION: %s - %s: %s", username, type(e).__name__, str(e)[:100])
                return AvailabilityResult(
                    username=username, status="ERROR",
                    platform="Discord", message=str(e)[:100]
                )

    def start(self, on_complete: Callable = None):
        asyncio.run(self._run(on_complete))

    async def _run(self, on_complete: Callable = None):
        self._running = True
        self._cancelled = False
        self._start_time = time.time()
        self._checked = 0
        self._available = 0
        self._taken = 0
        self._invalid = 0
        self._unknown = 0
        self._errors = 0
        self.results = []
        self.available_usernames = []

        generator = UsernameGenerator(self.platform, self.length, self.charset, self.amount)
        usernames = list(generator.generate(self.generation_mode))
        actual = len(usernames)
        if actual == 0:
            show_error("No valid usernames could be generated.")
            self._running = False
            if on_complete:
                on_complete(self)
            return

        semaphore = asyncio.Semaphore(self.concurrency)
        try:
            async with aiohttp.ClientSession() as session:
                tasks = []
                for username in usernames:
                    if self._cancelled:
                        break
                    task = asyncio.ensure_future(
                        self._check_one(username, session, semaphore)
                    )
                    tasks.append(task)

                for coro in asyncio.as_completed(tasks):
                    if self._cancelled:
                        break
                    try:
                        result = await coro
                    except asyncio.CancelledError:
                        break

                    self._checked += 1
                    self.results.append(result)

                    if result.status == "AVAILABLE":
                        self._available += 1
                        self.available_usernames.append(result.username)
                    elif result.status == "TAKEN":
                        self._taken += 1
                    elif result.status == "INVALID":
                        self._invalid += 1
                    elif result.status == "UNKNOWN":
                        self._unknown += 1
                        logger.debug("UNKNOWN: %s - %s", result.username, result.message)
                    elif result.status == "ERROR":
                        self._errors += 1
                        logger.debug("ERROR: %s - %s", result.username, result.message)
                    elif result.status == "RATE_LIMITED":
                        self._unknown += 1
                        logger.debug("RATE_LIMITED: %s", result.username)

                    now = time.time()
                    if now - self._last_display >= 0.4:
                        self._last_display = now
                        show_progress(
                            result.username, self._checked, actual,
                            self._available, self._taken, self._unknown,
                            self._errors, now - self._start_time
                        )

        except asyncio.CancelledError:
            self._cancelled = True
        except KeyboardInterrupt:
            self._cancelled = True
        finally:
            self._running = False

        elapsed = time.time() - self._start_time
        if not self._cancelled:
            show_results(
                self._checked, self._available, self._taken,
                self._invalid, self._unknown, self._errors, elapsed
            )
            show_available_list(self.available_usernames)

        if on_complete:
            on_complete(self)

    def stop(self):
        self._cancelled = True
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
