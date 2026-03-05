from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(path: str | None = None, override: bool = False, *args, **kwargs):  # type: ignore
        env_path = path or ".env"
        if not os.path.exists(env_path):
            return False

        with open(env_path, "r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key:
                    continue
                if override or key not in os.environ:
                    os.environ[key] = value
        return True


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Переменная окружения {name} должна быть числом, получено: {value!r}") from exc


def _env_optional_int(name: str, default: int | None) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Переменная окружения {name} должна быть числом или пустой, получено: {value!r}") from exc


def _env_int_set(name: str, default_values: Iterable[int]) -> set[int]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return set(default_values)

    parsed: set[int] = set()
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            parsed.add(int(item))
        except ValueError as exc:
            raise ValueError(f"Переменная окружения {name} содержит нечисловое значение: {item!r}") from exc
    return parsed


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    inline_allowed_chat_id: int | None
    admin_telegram_id: int | None

    max_token: str
    ws_uri: str
    max_target_chat_id: int
    forward_chat_ids: set[int]

    frames_log: str
    seen_ids_file: str
    telegram_outbox_file: str
    last_active_file: str
    attachments_dir: str
    ws_auth_file: str

    outbox_poll_interval: int
    outbox_base_backoff: int
    outbox_max_backoff: int
    last_active_update_interval: int
    max_backfill_age_seconds: int

    heartbeat_interval: int
    resubscribe_interval: int
    subscribe_limit: int

    chats_count: int
    chats_sync: int
    contacts_sync: int
    presence_sync: int
    drafts_sync: int

    history_backward: int
    history_forward: int
    history_max_pages: int
    history_response_timeout: int

    restart_seconds: int
    reconnect_threshold: int
    pending_send_ttl: int

    ws_origin: str
    ws_referer: str
    ws_user_agent: str
    ws_device_id: str
    ws_device_type: str
    ws_locale: str
    ws_device_locale: str
    ws_os_version: str
    ws_device_name: str
    ws_app_version: str
    ws_screen: str
    ws_timezone: str

    @property
    def user_agent_payload(self) -> dict[str, str]:
        return {
            "deviceType": self.ws_device_type,
            "locale": self.ws_locale,
            "deviceLocale": self.ws_device_locale,
            "osVersion": self.ws_os_version,
            "deviceName": self.ws_device_name,
            "headerUserAgent": self.ws_user_agent,
            "appVersion": self.ws_app_version,
            "screen": self.ws_screen,
            "timezone": self.ws_timezone,
        }


def load_settings(env_file: str | None = None) -> Settings:
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    max_target_chat_id = _env_int("MAX_TARGET_CHAT_ID", 0)
    forward_chat_ids = _env_int_set("FORWARD_CHAT_IDS", set())
    if not forward_chat_ids and max_target_chat_id:
        forward_chat_ids = {max_target_chat_id}

    return Settings(
        telegram_bot_token=_env_str("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=_env_str("TELEGRAM_CHAT_ID", ""),
        inline_allowed_chat_id=_env_optional_int("INLINE_ALLOWED_CHAT_ID", None),
        admin_telegram_id=_env_optional_int("ADMIN_TELEGRAM_ID", None),
        max_token=_env_str("MAX_TOKEN", ""),
        ws_uri=_env_str("WS_URI", "wss://ws-api.oneme.ru/websocket"),
        max_target_chat_id=max_target_chat_id,
        forward_chat_ids=forward_chat_ids,
        frames_log=_env_str("FRAMES_LOG", "frames.log"),
        seen_ids_file=_env_str("SEEN_IDS_FILE", "seen_ids.json"),
        telegram_outbox_file=_env_str("TELEGRAM_OUTBOX_FILE", "telegram_outbox.json"),
        last_active_file=_env_str("LAST_ACTIVE_FILE", "last_active.json"),
        attachments_dir=_env_str("ATTACHMENTS_DIR", "attachments"),
        ws_auth_file=_env_str("WS_AUTH_FILE", "ws_auth.json"),
        outbox_poll_interval=_env_int("OUTBOX_POLL_INTERVAL", 10),
        outbox_base_backoff=_env_int("OUTBOX_BASE_BACKOFF", 3),
        outbox_max_backoff=_env_int("OUTBOX_MAX_BACKOFF", 300),
        last_active_update_interval=_env_int("LAST_ACTIVE_UPDATE_INTERVAL", 60),
        max_backfill_age_seconds=_env_int("MAX_BACKFILL_AGE_SECONDS", 7 * 24 * 60 * 60),
        heartbeat_interval=_env_int("HEARTBEAT_INTERVAL", 20),
        resubscribe_interval=_env_int("RESUBSCRIBE_INTERVAL", 300),
        subscribe_limit=_env_int("SUBSCRIBE_LIMIT", 500),
        chats_count=_env_int("CHATS_COUNT", 40),
        chats_sync=_env_int("CHATS_SYNC", 1),
        contacts_sync=_env_int("CONTACTS_SYNC", 0),
        presence_sync=_env_int("PRESENCE_SYNC", 0),
        drafts_sync=_env_int("DRAFTS_SYNC", 0),
        history_backward=_env_int("HISTORY_BACKWARD", 30),
        history_forward=_env_int("HISTORY_FORWARD", 0),
        history_max_pages=_env_int("HISTORY_MAX_PAGES", 20),
        history_response_timeout=_env_int("HISTORY_RESPONSE_TIMEOUT", 15),
        restart_seconds=_env_int("RESTART_SECONDS", 4 * 60 * 60),
        reconnect_threshold=_env_int("RECONNECT_THRESHOLD", 10),
        pending_send_ttl=_env_int("PENDING_SEND_TTL", 300),
        ws_origin=_env_str("WS_ORIGIN", "https://web.max.ru"),
        ws_referer=_env_str("WS_REFERER", "https://web.max.ru/"),
        ws_user_agent=_env_str(
            "WS_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
        ),
        ws_device_id=_env_str("WS_DEVICE_ID", "00000000-0000-0000-0000-000000000000"),
        ws_device_type=_env_str("WS_DEVICE_TYPE", "WEB"),
        ws_locale=_env_str("WS_LOCALE", "ru"),
        ws_device_locale=_env_str("WS_DEVICE_LOCALE", "ru"),
        ws_os_version=_env_str("WS_OS_VERSION", "Windows"),
        ws_device_name=_env_str("WS_DEVICE_NAME", "Edge"),
        ws_app_version=_env_str("WS_APP_VERSION", "25.9.16"),
        ws_screen=_env_str("WS_SCREEN", "768x1024 1.0x"),
        ws_timezone=_env_str("WS_TIMEZONE", "Europe/Samara"),
    )


def validate_main_settings(settings: Settings) -> None:
    missing: list[str] = []
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not settings.telegram_chat_id:
        missing.append("TELEGRAM_CHAT_ID")
    if not settings.max_token:
        missing.append("MAX_TOKEN")
    if settings.max_target_chat_id == 0:
        missing.append("MAX_TARGET_CHAT_ID")
    if not settings.forward_chat_ids:
        missing.append("FORWARD_CHAT_IDS")

    if missing:
        names = ", ".join(missing)
        raise ValueError(
            f"Не заполнены обязательные переменные окружения: {names}. "
            "Скопируйте .env.example в .env и укажите значения."
        )
