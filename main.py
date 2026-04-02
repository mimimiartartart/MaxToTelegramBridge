import asyncio

from bridge.outbox import last_active_writer, normalize_existing_outbox, telegram_outbox_worker
from bridge.restart_utils import restart_after
from bridge.runtime import create_runtime
from bridge.settings import load_settings, validate_main_settings
from bridge.telegram_inline import cleanup_pending_sends, register_handlers
from bridge.ws_bridge import send_text_via_ws, ws_loop


async def telegram_polling_loop(runtime) -> None:
    backoff = max(1, runtime.settings.telegram_retry_base_delay)
    max_backoff = max(backoff, runtime.settings.telegram_retry_max_delay)

    while True:
        try:
            print(
                f"[TELEGRAM] запуск polling (timeout={runtime.settings.telegram_request_timeout}s)",
                flush=True,
            )
            await runtime.dp.start_polling(
                runtime.bot,
                handle_signals=False,
                close_bot_session=False,
            )
            print("[TELEGRAM] polling завершился, перезапускаю...", flush=True)
            backoff = max(1, runtime.settings.telegram_retry_base_delay)
            await runtime.bot.session.close()
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[TELEGRAM] polling ошибка: {exc}", flush=True)
            try:
                await runtime.bot.session.close()
            except Exception:
                pass
            print(f"[TELEGRAM] повтор через {backoff} сек...", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)


async def main() -> None:
    settings = load_settings()
    validate_main_settings(settings)
    runtime = create_runtime(settings)
    normalize_existing_outbox(runtime)

    register_handlers(
        runtime,
        lambda chat_id, text: send_text_via_ws(runtime, chat_id, text),
    )

    restart_after(settings.restart_seconds)

    cleanup_task = asyncio.create_task(cleanup_pending_sends(runtime))
    outbox_task = asyncio.create_task(telegram_outbox_worker(runtime))
    last_active_task = asyncio.create_task(last_active_writer(runtime))

    polling_task = asyncio.create_task(telegram_polling_loop(runtime))
    ws_task = asyncio.create_task(ws_loop(runtime))

    try:
        await asyncio.gather(polling_task, ws_task)
    finally:
        cleanup_task.cancel()
        outbox_task.cancel()
        last_active_task.cancel()
        try:
            await runtime.bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Остановлено по Ctrl+C", flush=True)
