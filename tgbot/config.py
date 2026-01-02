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
INBOUND_ID = 6

# ЮКасса
YOOKASSA_SHOP_ID=os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY=os.getenv("YOOKASSA_SECRET_KEY")
YOOKASSA_API_KEY=os.getenv("YOOKASSA_API_KEY")
# URL для возврата после оплаты (Telegram Deep Link или ваш сайт)
YOOKASSA_RETURN_URL = "https://t.me/flashlinkvpntestbot?start=payment_success"

# URL для вебхуков (должен быть HTTPS!)
YOOKASSA_WEBHOOK_URL = "https://oddly-compatible-guanaco.cloudpub.ru:443/webhook/yookassa"

# Текущий режим (sandbox или production)
YOOKASSA_MODE = "sandbox"  # Поменяйте на "production" для реальных платежей

# ==== Настройка официальной библиотеки ЮKassa ====

# Передаём данные магазина в библиотеку
Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_API_KEY  # Используем API_KEY

# Тарифы подписок (в рублях)
SUBSCRIPTION_PRICES = {
    30: 299,    # 30 дней - 299 руб
    90: 799,    # 90 дней - 799 руб
    180: 1499,  # 180 дней - 1499 руб
    365: 2699   # 365 дней - 2699 руб
}

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