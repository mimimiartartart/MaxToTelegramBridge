from __future__ import annotations

import asyncio
import os
import time

from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

from .persistence import save_last_active, save_seen_ids, save_telegram_outbox
from .runtime import AppRuntime


def normalize_outbox_item(item: dict | None) -> dict | None:
    if not isinstance(item, dict):
        return None

    if "attachments" not in item or not isinstance(item["attachments"], list):
        item["attachments"] = []
    if "attaches_sent" not in item or not isinstance(item["attaches_sent"], list):
        item["attaches_sent"] = [False] * len(item["attachments"])

    if len(item["attaches_sent"]) < len(item["attachments"]):
        item["attaches_sent"].extend([False] * (len(item["attachments"]) - len(item["attaches_sent"])))
    if len(item["attaches_sent"]) > len(item["attachments"]):
        item["attaches_sent"] = item["attaches_sent"][: len(item["attachments"])]

    item.setdefault("text_sent", False)
    item.setdefault("attempts", 0)
    item.setdefault("next_try_ts", 0.0)
    item.setdefault("ts", time.time())
    return item


def normalize_existing_outbox(runtime: AppRuntime) -> None:
    normalized: list[dict] = []
    for item in runtime.telegram_outbox:
        normalized_item = normalize_outbox_item(item)
        if normalized_item:
            normalized.append(normalized_item)
    runtime.telegram_outbox = normalized


async def save_seen_ids_safe(runtime: AppRuntime) -> None:
    try:
        save_seen_ids(runtime.settings.seen_ids_file, runtime.seen_ids)
    except Exception as exc:
        print("Ошибка сохранения seen_ids:", exc, flush=True)


async def save_telegram_outbox_safe(runtime: AppRuntime) -> None:
    try:
        save_telegram_outbox(runtime.settings.telegram_outbox_file, runtime.telegram_outbox)
    except Exception as exc:
        print("Ошибка сохранения telegram_outbox:", exc, flush=True)


async def enqueue_telegram_delivery(runtime: AppRuntime, item: dict) -> None:
    normalized_item = normalize_outbox_item(item)
    if not normalized_item:
        return

    async with runtime.outbox_lock:
        item_id = normalized_item.get("id")
        if item_id:
            item_id = str(item_id)
            for existing in runtime.telegram_outbox:
                existing_id = existing.get("id")
                if existing_id and str(existing_id) == item_id:
                    return
        runtime.telegram_outbox.append(normalized_item)
        await save_telegram_outbox_safe(runtime)
    runtime.outbox_wakeup.set()


async def deliver_outbox_item(runtime: AppRuntime, item: dict) -> bool:
    normalized_item = normalize_outbox_item(item)
    if not normalized_item:
        return False

    now = time.time()
    if normalized_item.get("next_try_ts", 0.0) > now:
        return False

    if not normalized_item.get("text_sent"):
        try:
            await runtime.bot.send_message(
                chat_id=runtime.settings.telegram_chat_id,
                text=normalized_item.get("text", ""),
                parse_mode=ParseMode.HTML,
            )
            normalized_item["text_sent"] = True
        except Exception as exc:
            normalized_item["attempts"] = int(normalized_item.get("attempts", 0)) + 1
            normalized_item["last_error"] = str(exc)
            delay = min(
                runtime.settings.outbox_max_backoff,
                runtime.settings.outbox_base_backoff * (2 ** min(normalized_item["attempts"], 6)),
            )
            normalized_item["next_try_ts"] = now + delay
            return False

    attachments = normalized_item.get("attachments") or []
    attaches_sent = normalized_item.get("attaches_sent") or [False] * len(attachments)
    if len(attaches_sent) < len(attachments):
        attaches_sent.extend([False] * (len(attachments) - len(attaches_sent)))

    for index, path in enumerate(attachments):
        if index < len(attaches_sent) and attaches_sent[index]:
            continue
        if not path or not os.path.exists(path):
            attaches_sent[index] = True
            continue

        try:
            low = str(path).lower()
            file_obj = FSInputFile(path)
            if low.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                await runtime.bot.send_photo(chat_id=runtime.settings.telegram_chat_id, photo=file_obj)
            else:
                await runtime.bot.send_document(chat_id=runtime.settings.telegram_chat_id, document=file_obj)
            attaches_sent[index] = True
        except Exception as exc:
            normalized_item["attaches_sent"] = attaches_sent
            normalized_item["attempts"] = int(normalized_item.get("attempts", 0)) + 1
            normalized_item["last_error"] = str(exc)
            delay = min(
                runtime.settings.outbox_max_backoff,
                runtime.settings.outbox_base_backoff * (2 ** min(normalized_item["attempts"], 6)),
            )
            normalized_item["next_try_ts"] = now + delay
            return False

    normalized_item["attaches_sent"] = attaches_sent
    return True


async def process_outbox_once(runtime: AppRuntime) -> None:
    async with runtime.outbox_lock:
        if not runtime.telegram_outbox:
            return
        items = list(runtime.telegram_outbox)

    changed = False
    for item in items:
        ok = await deliver_outbox_item(runtime, item)
        if ok:
            async with runtime.outbox_lock:
                try:
                    runtime.telegram_outbox.remove(item)
                    changed = True
                except ValueError:
                    pass
        else:
            changed = True

    if changed:
        async with runtime.outbox_lock:
            await save_telegram_outbox_safe(runtime)


async def telegram_outbox_worker(runtime: AppRuntime) -> None:
    try:
        while True:
            try:
                await process_outbox_once(runtime)
            except Exception as exc:
                print("Ошибка обработки outbox:", exc, flush=True)

            try:
                await asyncio.wait_for(runtime.outbox_wakeup.wait(), timeout=runtime.settings.outbox_poll_interval)
            except asyncio.TimeoutError:
                pass
            runtime.outbox_wakeup.clear()
    except asyncio.CancelledError:
        return


async def last_active_writer(runtime: AppRuntime) -> None:
    try:
        while True:
            try:
                save_last_active(runtime.settings.last_active_file, time.time())
            except Exception as exc:
                print("Ошибка сохранения last_active:", exc, flush=True)
            await asyncio.sleep(runtime.settings.last_active_update_interval)
    except asyncio.CancelledError:
        return
