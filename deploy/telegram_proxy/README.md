# Telegram Proxy Via VPS

Этот каталог нужен, если вы хотите оставить MAX и всю бизнес-логику на домашнем ПК, а трафик Telegram отправлять через зарубежный VPS.

## Что получится

- MAX WebSocket остается локально на вашем ПК.
- Локальный бот продолжает работать как раньше.
- Через VPS идет только Telegram API.
- Прокси можно включать и выключать через `.env`.

## Переключение прокси локально

В корневом `.env` проекта:

```env
TELEGRAM_USE_PROXY=0
TELEGRAM_PROXY_URL=
```

Режимы:

- Без прокси:

```env
TELEGRAM_USE_PROXY=0
TELEGRAM_PROXY_URL=
```

- Через прокси на VPS:

```env
TELEGRAM_USE_PROXY=1
TELEGRAM_PROXY_URL=socks5://login:password@YOUR_VPS_IP:1080
```

Если `TELEGRAM_USE_PROXY=1`, но `TELEGRAM_PROXY_URL` пустой, приложение завершится с ошибкой конфигурации.

## Команды для VPS

Ниже команды для Ubuntu/Debian. Выполняйте их по порядку.

### 1. Установить Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

### 2. Создать каталог под прокси

```bash
mkdir -p ~/telegram-proxy
cd ~/telegram-proxy
```

### 3. Создать `docker-compose.yml`

```bash
cat > docker-compose.yml <<'EOF'
services:
  telegram_proxy:
    image: ghcr.io/tarampampam/3proxy:1.12.1
    container_name: telegram_proxy
    restart: unless-stopped
    environment:
      PROXY_LOGIN: ${PROXY_LOGIN}
      PROXY_PASSWORD: ${PROXY_PASSWORD}
      SOCKS_PORT: 1080
      PRIMARY_RESOLVER: ${PRIMARY_RESOLVER:-1.1.1.1}
      SECONDARY_RESOLVER: ${SECONDARY_RESOLVER:-8.8.8.8}
      LOG_OUTPUT: /dev/stdout
    ports:
      - "1080:1080/tcp"
EOF
```

### 4. Создать `.env`

Замените логин и пароль на свои.

```bash
cat > .env <<'EOF'
PROXY_LOGIN=change_me
PROXY_PASSWORD=change_me_to_a_long_random_password
PRIMARY_RESOLVER=1.1.1.1
SECONDARY_RESOLVER=8.8.8.8
EOF
```

### 5. Поднять контейнер

```bash
sudo docker compose up -d
sudo docker compose ps
sudo docker logs telegram_proxy --tail 50
```

### 6. Открыть порт в firewall

Если используется `ufw`:

```bash
sudo ufw allow 1080/tcp
sudo ufw status
```

Если `ufw` не используется, проверьте firewall у провайдера VPS в панели управления.

## Что указать на ПК

В корневом `.env` проекта:

```env
TELEGRAM_USE_PROXY=1
TELEGRAM_PROXY_URL=socks5://change_me:change_me_to_a_long_random_password@YOUR_VPS_IP:1080
```

## Локальный запуск проекта

Установите обновленные зависимости:

```bash
pip install -r requirements.txt
```

Запуск:

```bash
python main.py
```

## Проверка

1. Запустите бота с `TELEGRAM_USE_PROXY=1`.
2. Отправьте тестовое сообщение в MAX.
3. Убедитесь, что оно пришло в Telegram.
4. Если что-то не работает, проверьте:
   - `sudo docker logs telegram_proxy --tail 100`
   - локальный вывод `python main.py`
   - корректность `TELEGRAM_PROXY_URL`

## Безопасность

- Используйте длинный случайный пароль.
- Лучше ограничить доступ к порту `1080` вашим домашним IP, если у вас статический адрес.
- Не публикуйте `.env` с логином и паролем в репозиторий.
