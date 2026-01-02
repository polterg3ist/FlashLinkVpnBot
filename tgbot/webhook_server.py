from fastapi import FastAPI, Request, HTTPException, Header
import uvicorn
import json
import os
import logging
from datetime import datetime
from aiogram import Bot

# Импортируем наши модули
from yookassa_payments import yookassa
from database import get_payment_by_id, update_payment_status, get_user_by_telegram_id, update_user_expiry
from vpn_manager import VPNManager
from config import BOT_TOKEN
import asyncio

app = FastAPI()


# ========== НАСТРОЙКА ПАПКИ ДЛЯ ЛОГОВ ==========
LOG_DIR = 'log/'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
    print(f"✅ Создана папка для логов: {LOG_DIR}")

# Файлы логов для вебхука
WEBHOOK_LOG_FILE = os.path.join(LOG_DIR, 'webhook.log')
WEBHOOK_ERRORS_FILE = os.path.join(LOG_DIR, 'webhook_errors.log')

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ДЛЯ WEBHOOK ==========
# Создаем отдельный логгер для вебхука
webhook_logger = logging.getLogger('webhook')
webhook_logger.setLevel(logging.INFO)

# Форматтер
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Обработчик для общего лога вебхука
file_handler = logging.FileHandler(WEBHOOK_LOG_FILE, encoding='utf-8')
file_handler.setFormatter(formatter)

# Обработчик для ошибок вебхука (отдельный файл)
error_handler = logging.FileHandler(WEBHOOK_ERRORS_FILE, encoding='utf-8')
error_handler.setFormatter(formatter)
error_handler.setLevel(logging.ERROR)

# Обработчик для консоли
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# Добавляем обработчики к логгеру
webhook_logger.addHandler(file_handler)
webhook_logger.addHandler(error_handler)
webhook_logger.addHandler(console_handler)

# Убираем дублирование (предотвращаем добавление обработчиков к корневому логгеру)
webhook_logger.propagate = False

print(f"✅ Логирование вебхука настроено. Файлы: {WEBHOOK_LOG_FILE}, {WEBHOOK_ERRORS_FILE}")

# Инициализируем менеджер VPN
vpn_manager = VPNManager()

# Инициализируем бота для уведомлений
bot = None

def init_bot(token: str):
    """Инициализация бота для отправки уведомлений"""
    global bot
    bot = Bot(token=token)
    return bot


from yookassa import Configuration, Webhook




@app.post("/webhook/yookassa")
async def yookassa_webhook(
        request: Request,
        signature: str = Header(None)
):
    """
    Вебхук для получения уведомлений от Яндекс Кассы
    """
    try:

        # Получаем сырое тело запроса для проверки подписи
        body_bytes = await request.body()
        print(body_bytes)

        # Проверяем подпись ЧЕРЕЗ SDK
        # ВАЖНО: новый метод verify_webhook_signature ожидает body_bytes и signature,
        # но использует только body_bytes. signature передаём для совместимости.
        if not yookassa.verify_webhook_signature(body_bytes, signature):
            webhook_logger.warning("Вебхук не прошел проверку подписи через SDK!")
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Парсим JSON
        data = json.loads(body_bytes.decode('utf-8'))
        event = data.get('event')
        payment_object = data.get('object', {})
        payment_id = payment_object.get('id')

        webhook_logger.info(f"Вебхук от ЮKassa: event={event}, payment_id={payment_id}")

        if event == "payment.waiting_for_capture":
            # Платеж ожидает подтверждения
            await handle_payment_waiting(payment_id, payment_object)

        elif event == "payment.succeeded":
            # Платеж успешно завершен
            await handle_payment_succeeded(payment_id, payment_object)

        elif event == "payment.canceled":
            # Платеж отменен
            await handle_payment_canceled(payment_id, payment_object)

        elif event == "refund.succeeded":
            # Возврат средств
            await handle_refund_succeeded(payment_id, payment_object)

        else:
            webhook_logger.warning(f"Неизвестное событие: {event}")

        # Всегда возвращаем 200 OK ЮKassa
        return {"status": "ok"}

    except json.JSONDecodeError as e:
        webhook_logger.error(f"Ошибка парсинга JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        webhook_logger.error(f"Ошибка в вебхуке: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def handle_payment_succeeded(payment_id: str, payment_data: dict):
    """Обработка успешного платежа"""
    try:
        # Сначала проверяем, не обрабатывали ли уже этот платеж
        existing_payment = get_payment_by_id(payment_id)
        if existing_payment and existing_payment['status'] == 'succeeded':
            webhook_logger.warning(f"Платеж {payment_id} уже был обработан")
            return

        # Обновляем статус в БД
        update_payment_status(payment_id, 'succeeded')

        # Получаем метаданные
        metadata = payment_data.get('metadata', {})
        user_id_str = metadata.get('user_id')
        days_str = metadata.get('days')

        if not user_id_str or not days_str:
            webhook_logger.error(f"Не найдены метаданные для платежа {payment_id}")
            return

        # ВАЖНО: преобразуем строки в числа
        try:
            user_id = int(user_id_str)  # Telegram ID должен быть числом
            days = int(days_str)  # Количество дней должно быть числом
        except (ValueError, TypeError) as e:
            webhook_logger.error(
                f"Неверный формат метаданных для платежа {payment_id}: user_id={user_id_str}, days={days_str}. Ошибка: {e}")
            return

        # Получаем пользователя (теперь передаем число)
        user = get_user_by_telegram_id(user_id)

        if not user:
            webhook_logger.error(f"Пользователь {user_id} не найден для платежа {payment_id}")
            return

        # Рассчитываем новый срок подписки
        current_time = int(datetime.now().timestamp() * 1000)
        # Убедитесь, что expiry_time в БД - число. Если это строка, преобразуйте:
        current_expiry = int(user['expiry_time']) if user['expiry_time'] > current_time else current_time
        new_expiry = current_expiry + (days * 24 * 60 * 60 * 1000)  # Теперь days - число, ошибки не будет

        # Обновляем подписку в 3x-ui
        success = vpn_manager.update_client(
            user['client_uuid'],
            user['client_email'],
            user['sub_id'],
            new_expiry
        )

        if success:
            # Обновляем в БД
            update_user_expiry(user_id, new_expiry)
            webhook_logger.info(f"Подписка обновлена для пользователя {user_id} на {days} дней")

            # Отправляем уведомление в Telegram
            await send_telegram_notification(user_id, payment_id, days)
        else:
            webhook_logger.error(f"Не удалось обновить подписку для пользователя {user_id}")

    except Exception as e:
        webhook_logger.error(f"Ошибка при обработке успешного платежа {payment_id}: {e}")


async def send_telegram_notification(user_id: int, payment_id: str, days: int):
    """Отправка уведомления в Telegram"""
    try:
        if bot is None:
            webhook_logger.error("Бот не инициализирован!")
            return

        message = (
            f"✅ Платеж успешно завершен!\n"
            f"📋 ID платежа: {payment_id}\n"
            f"📅 Добавлено дней: {days}\n"
            f"Ваша подписка продлена. Спасибо за оплату!"
        )

        await bot.send_message(chat_id=user_id, text=message)
        webhook_logger.info(f"Уведомление отправлено пользователю {user_id}")

    except Exception as e:
        webhook_logger.error(f"Ошибка при отправке уведомления в Telegram: {e}")
        # Записываем в файл как fallback
        with open('payment_notifications.log', 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now()} - User {user_id} - Payment {payment_id} - {days} дней - ERROR: {e}\n")


# Другие обработчики
async def handle_payment_waiting(payment_id: str, payment_data: dict):
    """Платеж ожидает подтверждения"""
    update_payment_status(payment_id, 'pending')
    webhook_logger.info(f"Платеж {payment_id} ожидает подтверждения")


async def handle_payment_canceled(payment_id: str, payment_data: dict):
    """Платеж отменен"""
    update_payment_status(payment_id, 'canceled')
    webhook_logger.info(f"Платеж {payment_id} отменен")


async def handle_refund_succeeded(payment_id: str, payment_data: dict):
    """Успешный возврат средств"""
    webhook_logger.info(f"Возврат для платежа {payment_id}")