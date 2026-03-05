from __future__ import annotations

import asyncio
import json
import time
from html import escape

import aiohttp
from aiogram.enums import ParseMode

from .attachments import download_and_attach
from .outbox import enqueue_telegram_delivery, save_seen_ids_safe
from .restart_utils import do_restart_now
from .runtime import AppRuntime


def should_backfill_message(runtime: AppRuntime, msg_time_ms: int) -> bool:
    if not msg_time_ms:
        return False
    if runtime.last_active_prev <= 0:
        return False

    msg_ts = msg_time_ms / 1000.0
    if msg_ts <= runtime.last_active_prev:
        return False
    if runtime.settings.max_backfill_age_seconds and (
        msg_ts - runtime.last_active_prev
    ) > runtime.settings.max_backfill_age_seconds:
        return False
    return True


async def handle_sync_messages(runtime: AppRuntime, messages_payload, ws, http_session: aiohttp.ClientSession) -> None:
    try:
        items = None
        if isinstance(messages_payload, dict):
            if "chats" in messages_payload and isinstance(messages_payload["chats"], dict):
                items = messages_payload["chats"].items()
            else:
                items = messages_payload.items()
        elif isinstance(messages_payload, list):
            items = []
            for entry in messages_payload:
                if not isinstance(entry, dict):
                    continue
                chat_id = entry.get("chatId") or entry.get("chat_id")
                msgs = entry.get("messages") or entry.get("items") or entry.get("msgs")
                items.append((chat_id, msgs))
        else:
            return

        for chat_id, msgs in items:
            if chat_id is None:
                continue
            try:
                cid = int(chat_id)
            except Exception:
                cid = chat_id

            if isinstance(msgs, dict) and "messages" in msgs:
                msgs = msgs.get("messages")
            if not isinstance(msgs, list):
                continue

            for msg in msgs:
                if not isinstance(msg, dict):
                    continue
                msg_time = msg.get("time") or 0
                if not should_backfill_message(runtime, msg_time):
                    continue
                await process_group_message(runtime, cid, msg, ws, http_session, source="sync")
    except Exception as exc:
        print("Ошибка обработки сообщений синхронизации:", exc, flush=True)


async def handle_history_messages(
    runtime: AppRuntime,
    chat_id: int,
    messages_payload,
    ws,
    http_session: aiohttp.ClientSession,
) -> None:
    try:
        if not chat_id or not isinstance(messages_payload, list):
            return

        state = runtime.history_state.get(chat_id)
        if state is not None:
            state["got_any"] = True

        def _msg_time(message: dict) -> int:
            try:
                return int(message.get("time") or 0)
            except Exception:
                return 0

        for message in sorted(messages_payload, key=_msg_time):
            if not isinstance(message, dict):
                continue
            msg_time = message.get("time") or 0
            if not should_backfill_message(runtime, msg_time):
                continue
            await process_group_message(runtime, chat_id, message, ws, http_session, source="history")
    except Exception as exc:
        print("Ошибка обработки сообщений истории:", exc, flush=True)


async def send_history_request(
    runtime: AppRuntime,
    ws,
    chat_id: int,
    from_ts_ms: int,
    backward: int | None = None,
    forward: int | None = None,
) -> None:
    seq = await runtime.next_seq()
    payload = {
        "chatId": int(chat_id),
        "from": int(from_ts_ms),
        "forward": int(runtime.settings.history_forward if forward is None else forward),
        "backward": int(runtime.settings.history_backward if backward is None else backward),
        "getMessages": True,
    }
    message = {"ver": 11, "cmd": 0, "seq": seq, "opcode": 49, "payload": payload}
    runtime.pending_history_replies[seq] = {"chat_id": int(chat_id), "from": int(from_ts_ms)}
    try:
        await ws.send_str(json.dumps(message))
        print(
            f"[ИСТОРИЯ] запрос chat_id={chat_id} from={from_ts_ms} back={payload['backward']} fwd={payload['forward']}",
            flush=True,
        )
    except Exception as exc:
        runtime.pending_history_replies.pop(seq, None)
        print("Ошибка отправки запроса истории:", exc, flush=True)


async def maybe_send_deferred_last_message(
    runtime: AppRuntime,
    chat_id: int,
    ws,
    http_session: aiohttp.ClientSession,
) -> None:
    state = runtime.history_state.get(chat_id) or {}
    last_msg = state.get("last_message")
    if not last_msg:
        return

    try:
        last_time = last_msg.get("time") or 0
        last_id = last_msg.get("id")
        if last_id is not None and str(last_id) in runtime.seen_ids:
            state["last_message"] = None
            return
        if should_backfill_message(runtime, last_time):
            await process_group_message(
                runtime,
                chat_id,
                last_msg,
                ws,
                http_session,
                source="lastMessage_deferred",
            )
    except Exception as exc:
        print("Ошибка отправки отложенного последнего сообщения:", exc, flush=True)
    finally:
        state["last_message"] = None


async def history_timeout_guard(runtime: AppRuntime, chat_id: int, ws, http_session: aiohttp.ClientSession) -> None:
    try:
        await asyncio.sleep(runtime.settings.history_response_timeout)
        state = runtime.history_state.get(chat_id)
        if not state or not state.get("active"):
            return
        state["active"] = False
        await maybe_send_deferred_last_message(runtime, chat_id, ws, http_session)
    except asyncio.CancelledError:
        return


async def start_history_sync(runtime: AppRuntime, ws, chat_id: int, http_session: aiohttp.ClientSession) -> bool:
    if chat_id not in runtime.settings.forward_chat_ids:
        return False

    if runtime.last_active_prev <= 0:
        return False

    gap = time.time() - runtime.last_active_prev
    if runtime.settings.max_backfill_age_seconds and gap > runtime.settings.max_backfill_age_seconds:
        return False

    state = runtime.history_state.get(chat_id)
    if state and state.get("active"):
        return False

    runtime.history_state[chat_id] = {"active": True, "pages": 0, "got_any": False}
    now_ms = int(time.time() * 1000)
    await send_history_request(runtime, ws, chat_id, now_ms)
    asyncio.create_task(history_timeout_guard(runtime, chat_id, ws, http_session))
    return True


async def send_to_telegram(runtime: AppRuntime, text: str) -> bool:
    try:
        await runtime.bot.send_message(
            chat_id=runtime.settings.telegram_chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as exc:
        print("Ошибка отправки в Telegram:", exc, flush=True)
        return False


async def send_to_max_http(runtime: AppRuntime, chat_id: int, text: str, format_: str = "html") -> tuple[bool, object]:
    url = "https://platform-api.max.ru/messages"
    headers = {"Authorization": runtime.settings.max_token, "Content-Type": "application/json"}
    payload = {"chat_id": chat_id, "text": text, "format": format_}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=15) as response:
                try:
                    data = await response.json()
                except Exception:
                    data = await response.text()
                if 200 <= response.status < 300:
                    return True, data
                return False, f"status={response.status}, тело={data}"
    except Exception as exc:
        return False, str(exc)


async def request_user_name(runtime: AppRuntime, ws, sender_id) -> str:
    seq = await runtime.next_seq()
    payload = {"contactIds": [int(sender_id)]}
    request = {"ver": 11, "cmd": 0, "seq": seq, "opcode": 32, "payload": payload}
    future = asyncio.get_event_loop().create_future()
    runtime.pending_name_replies[seq] = future

    try:
        await ws.send_str(json.dumps(request))
    except Exception:
        runtime.pending_name_replies.pop(seq, None)
        future.cancel()
        return str(sender_id)

    try:
        name = await asyncio.wait_for(future, timeout=5.0)
        return name or str(sender_id)
    except asyncio.TimeoutError:
        runtime.pending_name_replies.pop(seq, None)
        return str(sender_id)


def extract_from_message(message: dict | None):
    if not message:
        return "", [], None, None

    text = message.get("text", "") or ""
    attaches = message.get("attaches") or message.get("attachments") or []

    link = message.get("link")
    if link and isinstance(link, dict) and link.get("type") == "FORWARD":
        inner = link.get("message")
        if not inner and link.get("messages"):
            inner = link.get("messages")[0]
        if inner:
            return extract_from_message(inner)

    sender_id = message.get("sender")
    message_id = message.get("id")
    return text, attaches, sender_id, message_id


async def process_group_message(
    runtime: AppRuntime,
    chat_id,
    msg: dict,
    ws,
    http_session: aiohttp.ClientSession,
    source: str = "ws",
) -> None:
    try:
        chat_id_int = int(chat_id)
    except Exception:
        return

    if chat_id_int not in runtime.settings.forward_chat_ids:
        return

    message_id = msg.get("id") or f"{chat_id_int}_{int(time.time() * 1000)}"
    message_id_key = str(message_id)
    if message_id_key in runtime.seen_ids:
        return

    text, attaches, original_sender, _original_msg_id = extract_from_message(msg)

    sender_name = str(original_sender or msg.get("sender") or "")
    try:
        lookup_sender = original_sender if original_sender is not None else msg.get("sender")
        if lookup_sender is not None:
            sender_name = await request_user_name(runtime, ws, lookup_sender)
    except Exception:
        pass

    title = runtime.chat_titles.get(str(chat_id_int), str(chat_id_int))
    print("=== ГРУППОВОЕ СООБЩЕНИЕ ===", flush=True)
    print(f"Чат: {title} ({chat_id_int})", flush=True)
    print(
        f"От: {sender_name} (id={original_sender if original_sender is not None else msg.get('sender')})",
        flush=True,
    )
    print(f"ID сообщения: {message_id}", flush=True)
    print("Текст:", text, flush=True)

    local_paths: list[str] = []
    if attaches:
        download_tasks = [download_and_attach(runtime, http_session, attach) for attach in attaches]
        results = await asyncio.gather(*download_tasks)
        local_paths = [result for result in results if result]

    if local_paths:
        print("Вложения сохранены:", flush=True)
        for path in local_paths:
            print(" -", path, flush=True)
    print("====================", flush=True)

    is_forward = bool(
        msg.get("link") and isinstance(msg.get("link"), dict) and msg["link"].get("type") == "FORWARD"
    )
    display_name = sender_name.strip() if sender_name else "участник чата"
    safe_title = escape(str(title))
    safe_display_name = escape(display_name)
    safe_text = escape(text)
    if is_forward:
        text_to_send = (
            f"Пересланное сообщение в <b>{safe_title}</b> от <b>{safe_display_name}</b>:\n\n{safe_text}"
        )
    else:
        text_to_send = f"Новое сообщение в <b>{safe_title}</b> от <b>{safe_display_name}</b>:\n\n{safe_text}"

    outbox_item = {
        "id": message_id_key,
        "chat_id": chat_id_int,
        "title": title,
        "text": text_to_send,
        "attachments": local_paths,
        "ts": time.time(),
        "source": source,
    }
    await enqueue_telegram_delivery(runtime, outbox_item)

    runtime.seen_ids.add(message_id_key)
    if len(runtime.seen_ids) % 20 == 0:
        await save_seen_ids_safe(runtime)


async def subscribe_to_chat(runtime: AppRuntime, ws, chat_id: int) -> None:
    seq = await runtime.next_seq()
    message = {"ver": 11, "cmd": 0, "seq": seq, "opcode": 75, "payload": {"chatId": chat_id, "subscribe": True}}
    try:
        await ws.send_str(json.dumps(message))
        print(f"Отправлен запрос подписки на чат {chat_id}", flush=True)
    except Exception as exc:
        print("Ошибка отправки подписки:", exc, flush=True)


async def handle_incoming(runtime: AppRuntime, data: dict, ws, http_session: aiohttp.ClientSession) -> None:
    opcode = data.get("opcode")

    try:
        with open(runtime.settings.frames_log, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if opcode == 64:
        seq = data.get("seq")
        if seq:
            future = runtime.pending_send_replies.pop(seq, None)
            if future and not future.done():
                future.set_result(data.get("payload"))

    if opcode == 75:
        payload = data.get("payload")
        print("Получен opcode 75 (подтверждение подписки). payload:", payload, flush=True)
        return

    if opcode == 49:
        payload = data.get("payload", {}) or {}
        messages_payload = payload.get("messages") or []
        chat_id = payload.get("chatId") or payload.get("chat_id")
        seq = data.get("seq")
        info = runtime.pending_history_replies.pop(seq, None) if seq in runtime.pending_history_replies else None
        if not chat_id and info:
            chat_id = info.get("chat_id")
        if not chat_id:
            print("opcode 49 без chat_id, пропуск пакета истории", flush=True)
            return

        chat_id = int(chat_id)
        await handle_history_messages(runtime, chat_id, messages_payload, ws, http_session)

        state = runtime.history_state.get(chat_id)
        if state and state.get("active"):
            state["pages"] = int(state.get("pages", 0)) + 1
            if state["pages"] >= runtime.settings.history_max_pages:
                state["active"] = False
                await maybe_send_deferred_last_message(runtime, chat_id, ws, http_session)
                return
            if not isinstance(messages_payload, list) or not messages_payload:
                state["active"] = False
                await maybe_send_deferred_last_message(runtime, chat_id, ws, http_session)
                return

            oldest_time = None
            for message in messages_payload:
                try:
                    current_time = int(message.get("time") or 0)
                except Exception:
                    current_time = 0
                if current_time and (oldest_time is None or current_time < oldest_time):
                    oldest_time = current_time

            if not oldest_time:
                state["active"] = False
                await maybe_send_deferred_last_message(runtime, chat_id, ws, http_session)
                return

            if (oldest_time / 1000.0) <= runtime.last_active_prev:
                state["active"] = False
                await maybe_send_deferred_last_message(runtime, chat_id, ws, http_session)
                return

            await send_history_request(runtime, ws, chat_id, oldest_time - 1)
        return

    if opcode == 32:
        payload = data.get("payload", {}) or {}
        contacts = payload.get("contacts", []) or []
        seq = data.get("seq")
        if seq and seq in runtime.pending_name_replies:
            name = None
            if contacts:
                contact = contacts[0]
                name = (contact.get("names") or [{}])[0].get("name") or contact.get("id")
            future = runtime.pending_name_replies.pop(seq, None)
            if future and not future.done():
                future.set_result(name)
        return

    if opcode == 19:
        payload = data.get("payload", {}) or {}
        chats = payload.get("chats", []) or []
        messages_payload = payload.get("messages") or {}
        print(f"opcode 19: получены данные аккаунта/чатов ({len(chats)} чатов)", flush=True)
        if messages_payload:
            await handle_sync_messages(runtime, messages_payload, ws, http_session)

        count = 0
        for chat in chats:
            try:
                chat_id = chat.get("id")
                title = chat.get("title") or str(chat_id)
                runtime.chat_titles[str(chat_id)] = title
                last_msg = chat.get("lastMessage")
                if last_msg:
                    try:
                        runtime.history_state.setdefault(int(chat_id), {})["last_message"] = last_msg
                    except Exception:
                        pass

                started_history = False
                try:
                    started_history = await start_history_sync(runtime, ws, int(chat_id), http_session)
                except Exception as exc:
                    print("Ошибка запуска синхронизации истории:", exc, flush=True)

                if last_msg and not started_history:
                    try:
                        last_time = last_msg.get("time") or 0
                        if should_backfill_message(runtime, last_time):
                            await process_group_message(
                                runtime,
                                chat_id,
                                last_msg,
                                ws,
                                http_session,
                                source="lastMessage",
                            )
                    except Exception as exc:
                        print("Ошибка догрузки последнего сообщения:", exc, flush=True)

                if count < runtime.settings.subscribe_limit:
                    await subscribe_to_chat(runtime, ws, int(chat_id))
                    runtime.subscribed_chats.add(str(chat_id))
                    count += 1
            except Exception:
                continue
        return

    if opcode == 128:
        payload = data.get("payload", {}) or {}
        chat_id = payload.get("chatId") or payload.get("chat_id")
        message = payload.get("message", {}) or {}
        await process_group_message(runtime, chat_id, message, ws, http_session, source="ws")
        return

    print("Прочий opcode:", opcode, "| фрагмент payload:", str(data.get("payload"))[:200], flush=True)


async def periodic_resubscribe(runtime: AppRuntime, ws) -> None:
    try:
        while True:
            await asyncio.sleep(runtime.settings.resubscribe_interval)
            if not runtime.subscribed_chats:
                continue

            print("Периодическая переподписка на чаты...", flush=True)
            for chat_id in list(runtime.subscribed_chats):
                try:
                    await subscribe_to_chat(runtime, ws, int(chat_id))
                except Exception as exc:
                    print("Ошибка периодической подписки:", exc, flush=True)
    except asyncio.CancelledError:
        return


async def send_text_via_ws(runtime: AppRuntime, chat_id: int, text: str, timeout: float = 8.0) -> tuple[bool, object]:
    if not runtime.ws_connected.is_set():
        return False, "Нет подключения к WebSocket"

    seq = await runtime.next_seq()
    cid = int(time.time() * 1000)
    message = {
        "ver": 11,
        "cmd": 0,
        "seq": seq,
        "opcode": 64,
        "payload": {
            "chatId": chat_id,
            "message": {
                "text": text,
                "cid": cid,
                "elements": [],
                "attaches": [],
            },
            "notify": True,
        },
    }
    future = asyncio.get_event_loop().create_future()
    runtime.pending_send_replies[seq] = future
    try:
        await runtime.outgoing_queue.put(message)
    except Exception as exc:
        runtime.pending_send_replies.pop(seq, None)
        return False, str(exc)

    try:
        payload = await asyncio.wait_for(future, timeout=timeout)
        return True, payload
    except asyncio.TimeoutError:
        runtime.pending_send_replies.pop(seq, None)
        return False, "таймаут ожидания подтверждения от сервера"
    except Exception as exc:
        runtime.pending_send_replies.pop(seq, None)
        return False, str(exc)


async def ws_loop(runtime: AppRuntime) -> None:
    backoff = 1
    max_backoff = 60
    headers = {
        "Origin": runtime.settings.ws_origin,
        "Referer": runtime.settings.ws_referer,
        "User-Agent": runtime.settings.ws_user_agent,
    }

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                print("Подключение к", runtime.settings.ws_uri, flush=True)
                async with session.ws_connect(runtime.settings.ws_uri, headers=headers, max_msg_size=0) as ws:
                    print("WS подключен", flush=True)
                    try:
                        async with runtime.reconnect_lock:
                            runtime.reconnect_counter = 0
                    except Exception:
                        pass
                    backoff = 1

                    seq0 = await runtime.next_seq()
                    first_msg = {
                        "ver": 11,
                        "cmd": 0,
                        "seq": seq0,
                        "opcode": 6,
                        "payload": {
                            "userAgent": runtime.settings.user_agent_payload,
                            "deviceId": runtime.settings.ws_device_id,
                        },
                    }
                    await ws.send_str(json.dumps(first_msg))
                    await asyncio.sleep(0.08)

                    seq1 = await runtime.next_seq()
                    second_msg = {
                        "ver": 11,
                        "cmd": 0,
                        "seq": seq1,
                        "opcode": 19,
                        "payload": {
                            "interactive": True,
                            "token": runtime.settings.max_token,
                            "chatsCount": runtime.settings.chats_count,
                            "chatsSync": runtime.settings.chats_sync,
                            "contactsSync": runtime.settings.contacts_sync,
                            "presenceSync": runtime.settings.presence_sync,
                            "draftsSync": runtime.settings.drafts_sync,
                        },
                    }
                    await ws.send_str(json.dumps(second_msg))

                    runtime.ws_connected.set()

                    async def ws_sender() -> None:
                        try:
                            while True:
                                message = await runtime.outgoing_queue.get()
                                try:
                                    await ws.send_str(json.dumps(message))
                                except Exception as exc:
                                    seq = message.get("seq")
                                    future = runtime.pending_send_replies.pop(seq, None)
                                    if future and not future.done():
                                        future.set_exception(exc)
                        except asyncio.CancelledError:
                            return

                    async def json_heartbeat() -> None:
                        try:
                            while True:
                                seqh = await runtime.next_seq()
                                heartbeat = {
                                    "ver": 11,
                                    "cmd": 0,
                                    "seq": seqh,
                                    "opcode": 1,
                                    "payload": {"interactive": False},
                                }
                                try:
                                    await ws.send_str(json.dumps(heartbeat))
                                except Exception:
                                    return
                                await asyncio.sleep(runtime.settings.heartbeat_interval)
                        except asyncio.CancelledError:
                            return

                    ws_sender_task = asyncio.create_task(ws_sender())
                    heartbeat_task = asyncio.create_task(json_heartbeat())
                    resubscribe_task = asyncio.create_task(periodic_resubscribe(runtime, ws))

                    try:
                        async for message in ws:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(message.data)
                                except Exception:
                                    continue
                                try:
                                    await handle_incoming(runtime, data, ws, session)
                                except Exception as exc:
                                    print("Ошибка обработки входящего фрейма:", exc, flush=True)
                            elif message.type == aiohttp.WSMsgType.ERROR:
                                print("WS ОШИБКА:", message, flush=True)
                                break
                    finally:
                        heartbeat_task.cancel()
                        resubscribe_task.cancel()
                        ws_sender_task.cancel()
                        runtime.ws_connected.clear()

                        for seq, future in list(runtime.pending_send_replies.items()):
                            try:
                                if future and not future.done():
                                    future.set_exception(Exception("WS отключен"))
                            except Exception:
                                pass
                        runtime.pending_send_replies.clear()
                        runtime.pending_history_replies.clear()
                        runtime.history_state.clear()

                        try:
                            async with runtime.reconnect_lock:
                                runtime.reconnect_counter += 1
                                print(
                                    f"[СЧЕТЧИК_ПЕРЕПОДКЛЮЧЕНИЙ] увеличен -> {runtime.reconnect_counter}",
                                    flush=True,
                                )
                                if runtime.reconnect_counter >= runtime.settings.reconnect_threshold:
                                    print(
                                        f"[ТРИГГЕР_ПЕРЕЗАПУСКА] достигнуто {runtime.reconnect_counter} ошибок -> перезапуск",
                                        flush=True,
                                    )
                                    do_restart_now()
                        except Exception:
                            pass

                        print("WS соединение закрыто, переподключаюсь...", flush=True)

            except Exception as exc:
                print("WS соединение не удалось / упало:", exc, flush=True)
                try:
                    async with runtime.reconnect_lock:
                        runtime.reconnect_counter += 1
                        print(f"[СЧЕТЧИК_ПЕРЕПОДКЛЮЧЕНИЙ] увеличен -> {runtime.reconnect_counter}", flush=True)
                        if runtime.reconnect_counter >= runtime.settings.reconnect_threshold:
                            print(
                                f"[ТРИГГЕР_ПЕРЕЗАПУСКА] достигнуто {runtime.reconnect_counter} ошибок -> перезапуск",
                                flush=True,
                            )
                            do_restart_now()
                except Exception:
                    pass

                print(f"Переподключение через {backoff} сек...", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, backoff * 2)
