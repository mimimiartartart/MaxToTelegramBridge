from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher

from .persistence import load_last_active, load_seen_ids, load_telegram_outbox
from .settings import Settings


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    bot: Bot
    dp: Dispatcher

    seen_ids: set[str]
    telegram_outbox: list[dict]
    last_active_prev: float

    reconnect_counter: int = 0
    pending_name_replies: dict[int, asyncio.Future] = field(default_factory=dict)
    seq_counter: int = 0
    seq_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    chat_titles: dict[str, str] = field(default_factory=dict)
    subscribed_chats: set[str] = field(default_factory=set)
    outgoing_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    pending_send_replies: dict[int, asyncio.Future] = field(default_factory=dict)
    pending_history_replies: dict[int, dict] = field(default_factory=dict)
    history_state: dict[int, dict] = field(default_factory=dict)
    ws_connected: asyncio.Event = field(default_factory=asyncio.Event)
    outbox_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    outbox_wakeup: asyncio.Event = field(default_factory=asyncio.Event)
    pending_sends: dict[str, dict] = field(default_factory=dict)
    reconnect_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def next_seq(self) -> int:
        async with self.seq_lock:
            self.seq_counter += 1
            return self.seq_counter


def create_runtime(settings: Settings) -> AppRuntime:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(bot=bot)

    seen_ids = load_seen_ids(settings.seen_ids_file)
    telegram_outbox = load_telegram_outbox(settings.telegram_outbox_file)
    for item in telegram_outbox:
        message_id = item.get("id")
        if message_id:
            seen_ids.add(str(message_id))

    last_active_prev = load_last_active(settings.last_active_file)

    return AppRuntime(
        settings=settings,
        bot=bot,
        dp=dp,
        seen_ids=seen_ids,
        telegram_outbox=telegram_outbox,
        last_active_prev=last_active_prev,
    )

