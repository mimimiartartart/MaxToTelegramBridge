# MaxToTelegramBridge

Ретранслятор сообщений и вложений из MAX (OneMe WebSocket) в Telegram.

Проект работает локально, подключается к MAX по WebSocket, пересылает сообщения в Telegram через Bot API и умеет отправлять текст обратно в MAX через inline-режим Telegram. При необходимости Telegram-трафик можно пустить через прокси на зарубежном VPS, не перенося туда MAX-сессию и основную логику.

## Возможности

- пересылка сообщений из выбранных чатов MAX в Telegram;
- загрузка вложений и отправка их в Telegram как фото или документы;
- очередь отправки в Telegram с ретраями и экспоненциальной задержкой;
- догрузка пропущенных сообщений после перезапуска;
- inline-режим Telegram для отправки текста обратно в MAX;
- автопереподписка на чаты и восстановление WebSocket-соединения;
- логирование входящих WS-фреймов в `frames.log`;
- опциональная работа Telegram через SOCKS5-прокси на VPS.

## Как это устроено

- MAX: локальное WebSocket-подключение к `wss://ws-api.oneme.ru/websocket`;
- Telegram: `aiogram` + Bot API;
- прокси: включается только для Telegram, MAX остается локальным;
- состояние: `seen_ids.json`, `telegram_outbox.json`, `last_active.json`.

## Установка

1. Клонируйте репозиторий:

```bash
git clone https://github.com/mimimiartartart/MaxToTelegramBridge.git
cd MaxToTelegramBridge
```

2. Создайте виртуальное окружение:

```bash
python -m venv venv
```

3. Активируйте его:

```bash
# Windows PowerShell
venv\Scripts\Activate.ps1

# Linux / macOS
source venv/bin/activate
```

4. Установите зависимости:

```bash
pip install -r requirements.txt
```

## Настройка

1. Создайте `.env` из шаблона:

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

2. Заполните обязательные переменные:

- `TELEGRAM_BOT_TOKEN` — токен Telegram-бота;
- `TELEGRAM_CHAT_ID` — чат или канал для пересылки;
- `MAX_TOKEN` — токен MAX;
- `MAX_TARGET_CHAT_ID` — целевой чат MAX для inline-отправки;
- `FORWARD_CHAT_IDS` — список MAX-чатов для пересылки в Telegram.

3. При необходимости настройте inline-режим:

- `INLINE_ALLOWED_CHAT_ID`
- `ADMIN_TELEGRAM_ID`

## Telegram Через VPS-Прокси

Если Telegram блокируется локально, можно оставить MAX и основную логику на РФ сервере, а в VPS вынести только прокси.

Для этого используются переменные:

```env
TELEGRAM_USE_PROXY=1
TELEGRAM_PROXY_URL=socks5://login:password@YOUR_VPS_IP:1080
```

Если прокси не нужен:

```env
TELEGRAM_USE_PROXY=0
TELEGRAM_PROXY_URL=
```

Пошаговый деплой на VPS и Docker-конфиг лежат в [deploy/telegram_proxy/README.md](deploy/telegram_proxy/README.md).

## Запуск

Обычный запуск:

```bash
python main.py
```

На Windows можно использовать `start.bat`.

Логгер WS:

```bash
python logger.py
```

## Переменные Окружения

Полный список и примеры значений находятся в `.env.example`.

Наиболее важные группы настроек:

- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `INLINE_ALLOWED_CHAT_ID`, `ADMIN_TELEGRAM_ID`;
- прокси: `TELEGRAM_USE_PROXY`, `TELEGRAM_PROXY_URL`;
- MAX / WS: `MAX_TOKEN`, `WS_URI`, `MAX_TARGET_CHAT_ID`, `FORWARD_CHAT_IDS`;
- надежность и история: `OUTBOX_*`, `HISTORY_*`, `RESTART_SECONDS`, `RECONNECT_THRESHOLD`;
- клиентские параметры MAX WebSocket: `WS_ORIGIN`, `WS_REFERER`, `WS_USER_AGENT`, `WS_DEVICE_*`.

## Структура Проекта

- `main.py` — точка входа;
- `logger.py` — отдельный логгер WS-фреймов;
- `bridge/settings.py` — загрузка и валидация `.env`;
- `bridge/runtime.py` — общее состояние приложения;
- `bridge/persistence.py` — работа с `seen_ids`, `outbox`, `last_active`;
- `bridge/outbox.py` — очередь и доставка сообщений в Telegram;
- `bridge/attachments.py` — загрузка и сохранение вложений;
- `bridge/telegram_inline.py` — обработчики inline/callback Telegram;
- `bridge/ws_bridge.py` — основная логика MAX WebSocket;
- `bridge/restart_utils.py` — плановый и аварийный перезапуск;
- `deploy/telegram_proxy/` — Docker-конфиг и инструкции для VPS-прокси.

## Файлы Состояния

Проект создает и использует локальные файлы:

- `frames.log`
- `seen_ids.json`
- `telegram_outbox.json`
- `last_active.json`
- `attachments/`

Они уже исключены из Git через `.gitignore`.

## Решение Проблем

`RuntimeError: ... Install aiohttp-socks`

```bash
pip install -r requirements.txt
```

`TELEGRAM_USE_PROXY=1`, но бот не стартует

- проверьте, что `TELEGRAM_PROXY_URL` заполнен;
- проверьте формат `socks5://login:password@host:port`;
- убедитесь, что VPS-докер-контейнер поднят и порт доступен.

В Telegram показывается числовой `sender_id`

- в актуальной версии проект кэширует имена контактов из MAX;
- если контакт новый и еще не успел прийти в кэш, первое сообщение может временно уйти с id, следующие уже будут с именем.

## Безопасность

- если используете VPS-прокси, по возможности ограничьте доступ к порту вашим IP.

## Лицензия

[MIT](LICENSE)
