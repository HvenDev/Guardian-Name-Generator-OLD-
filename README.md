# GUARDIAN

**Multi-Platform Username Research Tool**

GUARDIAN is a terminal-based tool for finding short, potentially valuable usernames across multiple platforms.

## Quick Start

1. **Install Python 3.8+** from [python.org](https://www.python.org/downloads/)
2. Run `install.bat` (double-click)
3. Run `start.bat` (double-click)
4. Enter your Discord webhook URL
5. Choose a service, length, amount, and start scanning

## Features

- **14 Platforms**: Discord, Twitch, YouTube, Instagram, TikTok, X/Twitter, GitHub, Reddit, Steam, Telegram, Kick, Roblox, Snapchat, Pinterest
- **Smart Generation**: Intelligent username candidate generation with variations, prefixes, suffixes, and character substitutions
- **Real Availability Checking**: No fake results - only confirmed available usernames
- **Live Scanner Dashboard**: Real-time progress, speed, and results display
- **Discord Webhook Integration**: Automatic scan results sent to your Discord channel
- **Result Export**: TXT, CSV, and JSON formats with full scan history

## Usage

### Find Usernames (Primary Function)

```
Select a platform -> Choose length -> Set amount -> Pick character type -> Start
```

### Check Single Username

Quick availability check for a specific username on any platform.

### Platform Settings

View detailed rules for each platform (min/max length, allowed characters).

### Webhook Settings

- Change your Discord webhook
- Test webhook connection
- Remove webhook

### Scan History

Browse previous scan results with full details.

## How Availability Checking Works

GUARDIAN uses legitimate, publicly available mechanisms to check usernames:

- **Discord**: API endpoint returns 404 for available, 200 for taken
- **GitHub**: API endpoint returns 404 for available, 200 for taken
- **Reddit**: API endpoint returns 404 for available, 200 for taken
- **Twitch/YouTube/Instagram/TikTok**: Page content analysis
- **Others**: Platform-specific public endpoints

### Result Statuses

| Status | Meaning |
|--------|---------|
| `AVAILABLE` | Username is confirmed available |
| `TAKEN` | Username is confirmed taken |
| `INVALID` | Username violates platform rules |
| `UNKNOWN` | Cannot reliably determine availability |
| `ERROR` | Request failed (timeout, connection error) |

**Never** does GUARDIAN fabricate availability results. If uncertain, the status will be `UNKNOWN`.

## Rate Limiting

GUARDIAN respects platform rate limits:

- Built-in delay between requests (configurable)
- Automatic retry on rate limit detection
- Exponential backoff for repeated limits

## Configuration

Edit `config/config.json` or use the Settings menu:

- **Request timeout**: 1-60 seconds (default: 10)
- **Rate limit delay**: 100-10000ms (default: 1000)
- **Logging**: Enable/disable scan logging
- **Theme**: Red, Rainbow, White, Green, Purple
- **Test mode**: Developer testing with mocked responses

## Results

Scan results are saved to:

```
results/latest.txt       # Plain text list
results/latest.csv       # CSV with status and metadata
results/latest.json      # Full structured data
results/history/         # Timestamped scan history
```

## Adding a Platform

1. Create `platforms/yourplatform.py`
2. Implement the `Platform` base class
3. Add to `platforms/__init__.py`

Example platform structure:

```python
from platforms.base import Platform, PlatformRules, AvailabilityResult

class YourPlatform(Platform):
    def get_rules(self) -> PlatformRules:
        return PlatformRules(
            platform_name="YourPlatform",
            minimum_length=3,
            maximum_length=20,
            allowed_characters="letters, numbers",
            allowed_characters_pattern=r"^[a-zA-Z0-9]+$",
            case_sensitive=False,
            description="Your platform rules",
        )

    def check_availability(self, username, timeout=10, test_mode=False):
        # Your availability check logic
        pass

    def get_profile_url(self, username):
        return f"https://yourplatform.com/{username}"
```

## Test Mode

Run with `--test` for developer testing:

```bash
python guardian.py --test
```

Uses mocked responses instead of real platform checks.

## Logging

Logs are written to `logs/guardian.log`:

- Startup/shutdown events
- Configuration changes
- Scan starts and completions
- Errors and rate limits

Webhook URLs and credentials are never logged.

## License

Research tool for educational purposes. Respect platform terms of service.
