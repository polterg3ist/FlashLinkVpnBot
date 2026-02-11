import os
from dotenv import load_dotenv
from yookassa import Configuration

load_dotenv()

# Токен бота из BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ID администраторов (можно несколько через запятую)
ADMIN_IDS = [848651169, 618227002]  # Замените на ваши Telegram ID

# Настройки 3x-ui

# Панель
PANEL_HOST = os.getenv("PANEL_HOST")
PANEL_USERNAME = os.getenv("PANEL_USERNAME")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD")
INBOUND_ID = 1

# ЮКасса
YOOKASSA_SHOP_ID=os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY=os.getenv("YOOKASSA_SECRET_KEY")
YOOKASSA_API_KEY=os.getenv("YOOKASSA_API_KEY")
# URL для возврата после оплаты (Telegram Deep Link или ваш сайт)
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL")

# URL для вебхуков (должен быть HTTPS!)
YOOKASSA_WEBHOOK_URL = os.getenv("YOOKASSA_WEBHOOK_URL")

# Секретный код для полной очистки бота
CLEANUP_SECRET_CODE = "P8Wov7CRKkRZ6O8U"

# Текущий режим (sandbox или production)
# YOOKASSA_MODE = "sandbox"  # Поменяйте на "production" для реальных платежей
YOOKASSA_MODE = "production"  # Поменяйте на "production" для реальных платежей
BOT_MODE = os.getenv("MODE")

# ==== Настройка официальной библиотеки ЮKassa ====

# Передаём данные магазина в библиотеку
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_API_KEY  # Используем API_KEY

# Тарифы подписок (в рублях)
SUBSCRIPTION_PRICES = {
    30: 150,
    90: 320,
    180: 590,
    365: 1100
}

SUBSCRIPTION_BASE_URL = os.getenv("SUBSCRIPTION_BASE_URL")
SUBSCRIPTION_PATH = os.getenv("SUBSCRIPTION_PATH")


# Настройки подписок
TRIAL_DAYS = 14  # Длительность пробной подписки

# Настройки для генерации ссылок (значения по умолчанию)
INBOUND_CONFIG = {
    "port": 2096,  # Порт из новой ссылки
    "protocol": "vless",
    "network": "tcp",
    "security": "reality",
    "sni": "www.icloud.com",  # Из нового target
    "fingerprint": "chrome",
    "public_key": "Re5Crtxy8QzZf84aj7PoijSG8XzAHHhThhSL6a6W6Es",  # Новый ключ
    "short_id": "c44df3cc",  # Первый из shortIds
    "spider_x": "/",
    "flow": "xtls-rprx-vision",
    "encryption": "none",
    "remark": "🔥FlashLink🔥"
}
