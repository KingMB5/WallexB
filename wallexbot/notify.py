"""
notify.py — optional Telegram notifications (no extra dependency: plain requests).

Off by default. Enable with TG_BOT_TOKEN + TG_CHAT_ID in .env.
The bot token is a secret: it is masked everywhere it might be logged.
"""

from __future__ import annotations

import logging

import requests

from .redact import mask

log = logging.getLogger("wallexbot.notify")


class Notifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.token = bot_token or None
        self.chat_id = chat_id or None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=10,
            )
        except requests.RequestException as e:
            log.warning("telegram notify failed (token=%s): %s", mask(self.token), type(e).__name__)
