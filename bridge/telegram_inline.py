from __future__ import annotations

import asyncio
import secrets
import time
from typing import Awaitable, Callable

from aiogram import types

from .runtime import AppRuntime

SendTextViaWs = Callable[[int, str], Awaitable[tuple[bool, object]]]


async def cleanup_pending_sends(runtime: AppRuntime) -> None:
    try:
        while True:
            now = time.time()
            for key in list(runtime.pending_sends.keys()):
                entry = runtime.pending_sends.get(key)
                if not entry:
                    continue
                if now - float(entry.get("ts", 0.0)) > runtime.settings.pending_send_ttl:
                    runtime.pending_sends.pop(key, None)
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        return


async def _is_inline_user_allowed(runtime: AppRuntime, user_id: int | None) -> bool:
    if not user_id:
        return False
    allowed_chat_id = runtime.settings.inline_allowed_chat_id
    if allowed_chat_id is None:
        return False
    try:
        member = await runtime.bot.get_chat_member(allowed_chat_id, user_id)
        return bool(member and getattr(member, "status", None) in ("creator", "administrator", "member"))
    except Exception:
        return False


def register_handlers(runtime: AppRuntime, send_text_via_ws: SendTextViaWs) -> None:
    async def inline_query_handler(inline_query: types.InlineQuery) -> None:
        try:
            text = (inline_query.query or "").strip()
            user = inline_query.from_user
            user_id = user.id if user else None

            allowed = await _is_inline_user_allowed(runtime, user_id)
            if not allowed:
                hint_text = "Inline-режим доступен только участникам разрешённого чата."
                input_content = types.InputTextMessageContent(message_text=hint_text)
                item = types.InlineQueryResultArticle(
                    id="not_allowed",
                    title="Доступ запрещён",
                    input_message_content=input_content,
                    description="Вы не являетесь участником разрешённого чата.",
                )
                await runtime.bot.answer_inline_query(inline_query.id, results=[item], cache_time=1)
                return

            if not text:
                help_input = types.InputTextMessageContent(
                    message_text="Напишите сообщение для отправки в MAX."
                )
                item = types.InlineQueryResultArticle(
                    id="help",
                    title="Отправить в MAX: введите текст",
                    input_message_content=help_input,
                    description="Введите текст",
                )
                await runtime.bot.answer_inline_query(inline_query.id, results=[item], cache_time=1)
                return

            uid = secrets.token_urlsafe(8)
            if user:
                uname_parts = []
                if getattr(user, "first_name", None):
                    uname_parts.append(user.first_name)
                if getattr(user, "last_name", None):
                    uname_parts.append(user.last_name)
                uname = " ".join(uname_parts).strip() or (getattr(user, "username", None) or f"user:{user.id}")
                owner_id = user.id
            else:
                uname = "автор"
                owner_id = None

            runtime.pending_sends[uid] = {
                "text": text,
                "chat_id": runtime.settings.max_target_chat_id,
                "ts": time.time(),
                "user_id": owner_id,
                "user_name": uname,
            }

            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="Отправить в MAX", callback_data=f"sendmax:{uid}")],
                ]
            )
            input_msg = types.InputTextMessageContent(message_text=f"Отправить в MAX:\n\n{text}")
            article = types.InlineQueryResultArticle(
                id=uid,
                title="Отправить в MAX",
                input_message_content=input_msg,
                reply_markup=keyboard,
                description=(text[:50] + "...") if len(text) > 50 else text,
            )
            await runtime.bot.answer_inline_query(inline_query.id, results=[article], cache_time=1)
        except Exception as exc:
            print("Ошибка inline_query_handler:", exc, flush=True)
            try:
                await runtime.bot.answer_inline_query(inline_query.id, results=[], cache_time=1)
            except Exception:
                pass

    async def callback_query_handler(callback_query: types.CallbackQuery) -> None:
        data = callback_query.data or ""
        if not data.startswith("sendmax:"):
            await callback_query.answer()
            return

        uid = data.split(":", 1)[1]
        entry = runtime.pending_sends.get(uid)
        if not entry:
            await callback_query.answer("Данные устарели или недоступны.", show_alert=True)
            return

        caller_id = callback_query.from_user.id if callback_query.from_user else None
        owner_id = entry.get("user_id")
        owner_name = entry.get("user_name", "автор")
        if owner_id is not None and caller_id != owner_id:
            await callback_query.answer(
                f"Только инициатор ({owner_name}) может отправить это сообщение.",
                show_alert=True,
            )
            return

        allowed = await _is_inline_user_allowed(runtime, caller_id)
        if not allowed:
            await callback_query.answer("Вы больше не участник разрешённого чата.", show_alert=True)
            return

        entry = runtime.pending_sends.pop(uid, None)
        if not entry:
            await callback_query.answer("Данные устарели или недоступны.", show_alert=True)
            return

        try:
            if runtime.settings.admin_telegram_id is not None:
                log_name = entry.get("user_name", "неизвестный пользователь")
                log_text = entry.get("text", "")
                log_id = owner_id
                log_username = (
                    f"@{callback_query.from_user.username}"
                    if callback_query.from_user and callback_query.from_user.username
                    else ""
                )
                log_msg = (
                    "<b>Новая отправка через inline</b>\n\n"
                    f"<b>Имя:</b> {log_name}\n"
                    f"<b>Юзернейм:</b> {log_username or 'нет'}\n"
                    f"<b>ID пользователя:</b> <code>{log_id}</code>\n\n"
                    f"<b>Текст:</b>\n{log_text}"
                )
                await runtime.bot.send_message(
                    chat_id=runtime.settings.admin_telegram_id,
                    text=log_msg,
                    parse_mode="HTML",
                )
        except Exception as exc:
            print("Ошибка логирования inline:", exc, flush=True)

        ok, response = await send_text_via_ws(int(entry["chat_id"]), str(entry["text"]))
        if ok:
            await callback_query.answer("Сообщение отправлено в MAX.")
            try:
                if callback_query.message:
                    await runtime.bot.edit_message_text(
                        chat_id=callback_query.message.chat.id,
                        message_id=callback_query.message.message_id,
                        text=f"Отправлено в MAX:\n\n{entry['text']}",
                    )
            except Exception:
                pass
        else:
            await callback_query.answer(f"Ошибка отправки: {response}", show_alert=True)

    runtime.dp.inline_query.register(inline_query_handler)
    runtime.dp.callback_query.register(callback_query_handler)
