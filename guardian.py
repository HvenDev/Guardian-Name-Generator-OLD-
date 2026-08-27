#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from platforms.discord import DiscordPlatform
from generator.generator import CHARSET_LETTERS_NUMBERS
from scanner.scanner import Scanner
from utils.logging import setup_logging, log_event
from utils.validation import is_valid_webhook_url
from utils.terminal import (
    show_banner, console, prompt_input, prompt_choice,
    prompt_int, show_results, show_available_list, show_error,
    show_success, press_enter,
)


def main():
    setup_logging(True, False)
    log_event("GUARDIAN started")

    show_banner()

    webhook_url = _get_webhook()
    length = prompt_int("USERNAME LENGTH (2-32)", 2, 32)
    amount = prompt_int("AMOUNT (1-50000)", 1, 50000)
    mode = prompt_choice("GENERATION MODE", ["Random", "Sequential", "Smart"])

    platform = DiscordPlatform()

    console.print()

    scanner = Scanner(
        platform=platform,
        length=length,
        amount=amount,
        charset=CHARSET_LETTERS_NUMBERS,
        generation_mode=mode,
        concurrency=3,
        request_timeout=10,
        request_delay=0.35,
    )

    def on_complete(scan):
        if scan.available_usernames and webhook_url:
            try:
                from webhook.discord_webhook import DiscordWebhook
                import requests as _req
                webhook = DiscordWebhook(webhook_url)
                sent = webhook.send_scan_results(
                    platform_name="Discord",
                    length=length,
                    checked=scan._checked,
                    available_count=scan._available,
                    taken=scan._taken,
                    invalid=scan._invalid,
                    unknown=scan._unknown,
                    available_usernames=scan.available_usernames,
                )
                if sent:
                    show_success("Results sent to Discord webhook.")
                else:
                    show_error("Failed to send webhook results.")
            except Exception:
                show_error("Webhook delivery failed.")

        console.print()
        press_enter()

    try:
        scanner.start(on_complete=on_complete)
    except KeyboardInterrupt:
        scanner.stop()
        console.print("\n  [dim]Scan cancelled.[/dim]")
        press_enter()


def _get_webhook() -> str:
    from utils.config import Config
    config = Config()
    saved = config.get_webhook_url()

    if saved and is_valid_webhook_url(saved):
        console.print("  [dim]Using saved webhook.[/dim]")
        return saved

    while True:
        url = prompt_input("WEBHOOK URL")
        if not url:
            console.print("  [dim]URL cannot be empty.[/dim]")
            continue
        if not is_valid_webhook_url(url):
            show_error("Invalid Discord webhook URL.")
            console.print("  [dim]Format: https://discord.com/api/webhooks/ID/TOKEN[/dim]")
            continue

        config.set_webhook_url(url)
        console.print("  [dim]Webhook saved.[/dim]")
        return url


if __name__ == "__main__":
    main()
