from __future__ import annotations

import os
import sys
import threading


def do_restart_now() -> None:
    print("[ПЕРЕЗАПУСК] Перезапуск процесса...", flush=True)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def restart_after(seconds: int) -> None:
    def _restart() -> None:
        print(f"[ТАЙМЕР_ПЕРЕЗАПУСКА] Перезапуск через {seconds} сек.", flush=True)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    timer = threading.Timer(seconds, _restart)
    timer.daemon = True
    timer.start()
