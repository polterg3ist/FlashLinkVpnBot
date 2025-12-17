import os
from dotenv import load_dotenv

load_dotenv()

# Токен бота из BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ID администраторов (можно несколько через запятую)
ADMIN_IDS = [848651169, 618227002]  # Замените на ваши Telegram ID

# Настройки 3x-ui

PANEL_HOST = os.getenv("PANEL_HOST")
PANEL_USERNAME = os.getenv("PANEL_USERNAME")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD")
INBOUND_ID = 6

# Настройки подписок
TRIAL_DAYS = 14  # Длительность пробной подписки
RENEWAL_PRICE = 299  # Цена продления в рублях (пока не используется)

# Настройки для генерации ссылок (значения по умолчанию)
INBOUND_CONFIG = {
    "port": 28048,
    "protocol": "vless",
    "network": "grpc",
    "security": "reality",
    "sni": "microsoft.com",
    "fingerprint": "chrome",
    "public_key": os.getenv("PUBLIC_KEY"),
    "short_id": "",  # В вашем примере sid пустой
    "spider_x": "/",
    "service_name": "",
    "authority": "",
    "encryption": "none",
    "remark": "TESTS"  # Префикс перед email в ссылке
}