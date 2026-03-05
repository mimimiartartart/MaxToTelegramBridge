import asyncio
import json
import time

import aiohttp

from bridge.settings import Settings, load_settings


async def run_logger(settings: Settings) -> None:
    timeout = aiohttp.ClientTimeout(total=None)
    headers = {
        "Origin": settings.ws_origin,
        "Referer": settings.ws_referer,
        "User-Agent": settings.ws_user_agent,
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            print("Подключение к", settings.ws_uri)
            async with session.ws_connect(settings.ws_uri, headers=headers, max_msg_size=0) as ws:
                print("WS подключен. Ожидание фреймов...")
                async for msg in ws:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        raw = msg.data
                        try:
                            data = json.loads(raw)
                        except Exception:
                            data = None

                        with open(settings.frames_log, "a", encoding="utf-8") as file:
                            file.write(f"{ts} | ТЕКСТ | {raw}\n")

                        if isinstance(data, dict):
                            opcode = data.get("opcode") or data.get("op") or data.get("cmd")
                            print(f"{ts} | opcode={opcode} | {json.dumps(data, ensure_ascii=False)}")
                        else:
                            print(f"{ts} | ТЕКСТ (не json) | {raw[:400]}")
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        with open(settings.frames_log, "ab") as file:
                            file.write(b"\n" + msg.data)
                        print(f"{ts} | БИНАРНЫЙ фрейм (сохранён в лог)")
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        print("Ошибка WS:", msg)
                        break
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        print("WS закрыт")
                        break
        except Exception as exc:
            print("Ошибка подключения:", exc)


if __name__ == "__main__":
    try:
        asyncio.run(run_logger(load_settings()))
    except KeyboardInterrupt:
        print("Остановлено пользователем (Ctrl+C)")
