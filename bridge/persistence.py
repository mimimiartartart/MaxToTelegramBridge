from __future__ import annotations

import json
import os
import time
from typing import Any


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False)


def load_seen_ids(path: str) -> set[str]:
    data = _read_json(path, [])
    if isinstance(data, list):
        return {str(item) for item in data}
    return set()


def save_seen_ids(path: str, seen_ids: set[str]) -> None:
    write_json(path, list(seen_ids))


def load_telegram_outbox(path: str) -> list[dict]:
    data = _read_json(path, [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def save_telegram_outbox(path: str, outbox: list[dict]) -> None:
    write_json(path, outbox)


def load_last_active(path: str) -> float:
    if not os.path.exists(path):
        return time.time()

    data = _read_json(path, 0.0)
    if isinstance(data, dict):
        try:
            return float(data.get("ts", 0.0) or 0.0)
        except Exception:
            return 0.0

    if isinstance(data, (int, float)):
        return float(data)

    return 0.0


def save_last_active(path: str, value: float | None = None) -> None:
    write_json(path, {"ts": value if value is not None else time.time()})

