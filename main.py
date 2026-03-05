import asyncio

from bridge.outbox import last_active_writer, normalize_existing_outbox, telegram_outbox_worker
from bridge.restart_utils import restart_after
from bridge.runtime import create_runtime
from bridge.settings import load_settings, validate_main_settings
from bridge.telegram_inline import cleanup_pending_sends, register_handlers
from bridge.ws_bridge import send_text_via_ws, ws_loop


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

    polling_task = asyncio.create_task(runtime.dp.start_polling(runtime.bot))
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
