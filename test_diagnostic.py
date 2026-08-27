"""Minimal scanner diagnostic - tests the exact async pipeline with raw print."""
import sys
import os
import time
import asyncio
import aiohttp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from platforms.discord import DiscordPlatform

ENDPOINT = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

CONCURRENCY = 3
TIMEOUT = 10
DELAY = 0.35
TEST_COUNT = 3


async def check_one(username, session, semaphore):
    async with semaphore:
        print(f"[REQ] Starting request: {username}", flush=True)
        try:
            await asyncio.sleep(DELAY)
            print(f"[REQ] Sending HTTP: {username}", flush=True)
            timeout = aiohttp.ClientTimeout(total=TIMEOUT)
            async with session.post(
                ENDPOINT,
                json={"username": username},
                headers=HEADERS,
                timeout=timeout,
            ) as resp:
                status_code = resp.status
                body = await resp.text()
                print(f"[REQ] Response received: {username} HTTP {status_code}", flush=True)

                if status_code in (200, 201, 204):
                    import json
                    try:
                        data = json.loads(body)
                    except Exception:
                        data = {}
                    taken = data.get("taken", True)
                    status = "TAKEN" if taken else "AVAILABLE"
                elif status_code == 429:
                    status = "RATE_LIMITED"
                elif status_code == 400:
                    status = "INVALID"
                else:
                    status = f"HTTP_{status_code}"

                print(f"[RESULT] {username} -> {status}", flush=True)
                return status
        except asyncio.CancelledError:
            print(f"[CANCELLED] {username}", flush=True)
            raise
        except Exception as e:
            print(f"[ERROR] {username} -> {type(e).__name__}: {e}", flush=True)
            return f"ERROR: {e}"


async def run_test(count):
    print(f"\n{'='*50}", flush=True)
    print(f"TEST: {count} checks, concurrency={CONCURRENCY}", flush=True)
    print(f"{'='*50}", flush=True)

    usernames = [f"testdiag{i:04d}" for i in range(count)]
    semaphore = asyncio.Semaphore(CONCURRENCY)
    checked = 0
    start = time.time()

    async with aiohttp.ClientSession() as session:
        tasks = []
        for u in usernames:
            task = asyncio.ensure_future(check_one(u, session, semaphore))
            tasks.append(task)

        print(f"[QUEUE] {len(tasks)} tasks created", flush=True)
        print(f"[QUEUE] Starting as_completed loop", flush=True)

        for coro in asyncio.as_completed(tasks):
            try:
                print(f"[QUEUE] Awaiting next result (checked={checked})...", flush=True)
                result = await coro
                checked += 1
                elapsed = time.time() - start
                print(f"[COUNT] {checked}/{count} done in {elapsed:.1f}s - {result}", flush=True)
            except asyncio.CancelledError:
                print(f"[QUEUE] CancelledError", flush=True)
                break
            except Exception as e:
                checked += 1
                print(f"[QUEUE] Exception: {type(e).__name__}: {e}", flush=True)

    elapsed = time.time() - start
    print(f"\n[DONE] {checked}/{count} checks completed in {elapsed:.1f}s", flush=True)
    print(f"[DONE] Speed: {checked/elapsed:.1f}/s", flush=True)
    return checked


def main():
    print("GUARDIAN Scanner Diagnostic", flush=True)
    print(f"Python {sys.version}", flush=True)

    # Test 1: 3 checks
    result = asyncio.run(run_test(3))
    if result < 3:
        print(f"\n[FAIL] Only {result}/3 completed. Freezing detected at HTTP layer.", flush=True)
        return

    # Test 2: 10 checks
    result = asyncio.run(run_test(10))
    if result < 10:
        print(f"\n[FAIL] Only {result}/10 completed.", flush=True)
        return

    # Test 3: 50 checks
    result = asyncio.run(run_test(50))
    if result < 50:
        print(f"\n[FAIL] Only {result}/50 completed.", flush=True)
        return

    print(f"\n[PASS] All tests completed successfully.", flush=True)


if __name__ == "__main__":
    main()
