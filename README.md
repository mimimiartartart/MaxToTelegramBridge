# MaxToTelegram

Ретранслятор сообщений и вложений из MAX (OneMe WebSocket) в Telegram.

## Что умеет
- Подключается к `wss://ws-api.oneme.ru/websocket`.
- Слушает сообщения в выбранных чатах MAX и пересылает их в Telegram.
- Поддерживает историю/догон пропущенных сообщений после перезапуска.
- Скачивает вложения (изображения и другие файлы) и отправляет в Telegram.
- Имеет надёжную очередь отправки в Telegram с ретраями и экспоненциальной задержкой.
- Ведёт лог входящих WS-фреймов в `frames.log`.
- Поддерживает inline-режим Telegram для отправки текста обратно в MAX.
- Автопереподписка на чаты и авто-переподключение к WebSocket.

## Структура проекта
- `main.py` — точка входа.
- `logger.py` — отдельный логгер WS-фреймов.
- `bridge/settings.py` — загрузка и валидация `.env`.
- `bridge/runtime.py` — общее состояние приложения.
- `bridge/persistence.py` — работа с `seen_ids/outbox/last_active`.
- `bridge/outbox.py` — очередь и доставка сообщений в Telegram.
- `bridge/attachments.py` — загрузка и сохранение вложений.
- `bridge/telegram_inline.py` — обработчики inline/callback Telegram.
- `bridge/ws_bridge.py` — основная WS-логика MAX.
- `bridge/restart_utils.py` — плановый/аварийный перезапуск процесса.

## Установка
1. Клонируйте репозиторий:
```bash
git clone https://github.com/mimimiartartart/MaxToTelegram.git
cd MaxToTelegram
```
2. Создайте виртуальное окружение:
```bash
python -m venv venv
```
3. Активируйте окружение:
```bash
# Windows (PowerShell)
venv\Scripts\Activate.ps1
```
4. Установите зависимости:
```bash
pip install -r requirements.txt
```

## Настройка
1. Создайте `.env` из шаблона:
```bash
copy .env.example .env
```
2. Заполните обязательные переменные:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MAX_TOKEN`
- `MAX_TARGET_CHAT_ID`
- `FORWARD_CHAT_IDS`

Если обязательные переменные не заполнены, приложение завершится с понятной ошибкой.

## Запуск
```bash
python main.py
```

Или на Windows:
```bat
start.bat
```

### Режим логгера WS
```bash
python logger.py
```

## Inline-режим Telegram
- Бот проверяет, что пользователь состоит в `INLINE_ALLOWED_CHAT_ID`.
- Пользователь вводит текст через inline, нажимает кнопку «Отправить в MAX».
- Сообщение уходит в `MAX_TARGET_CHAT_ID`.
- Опционально отправляется админ-лог в `ADMIN_TELEGRAM_ID`.

## Переменные окружения
Полный список и примеры значений — в `.env.example`.

## Публикация на GitHub
- Секреты в `.env` не коммитятся (`.gitignore` уже настроен).
- В репозиторий добавлены только исходники, шаблон настроек и зависимости.

### Быстрый импорт в новый репозиторий
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```
