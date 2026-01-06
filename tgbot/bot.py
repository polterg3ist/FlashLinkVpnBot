import asyncio
import logging
import os
import time
import traceback
from datetime import datetime

from aiogram import Bot, Dispatcher, types, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Update, ErrorEvent
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS, TRIAL_DAYS
from database import (
    get_user_by_telegram_id, add_user, update_user_expiry,
    get_all_users, delete_user_by_email, get_user_by_client_email, get_orphaned_users, validate_and_sync_users,
    create_payment, get_user_payments, update_user_client
)
from vpn_manager import VPNManager

from yookassa_payments import yookassa
from config import SUBSCRIPTION_PRICES, YOOKASSA_RETURN_URL, TRIAL_DAYS


# ========== НАСТРОЙКА ПАПКИ ДЛЯ ЛОГОВ ==========
LOG_DIR = 'log/'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
    print(f"✅ Создана папка для логов: {LOG_DIR}")

# Файлы логов
BOT_LOG_FILE = os.path.join(LOG_DIR, 'bot.log')
HANDLER_ERRORS_FILE = os.path.join(LOG_DIR, 'handler_errors.log')
MAIN_LOOP_CRASHES_FILE = os.path.join(LOG_DIR, 'main_loop_crashes.log')
AIOGRAM_ERRORS_FILE = os.path.join(LOG_DIR, 'aiogram_errors.log')

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(BOT_LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ========== MIDDLEWARE ДЛЯ ОБРАБОТКИ ОШИБОК ==========
class ErrorLoggingMiddleware(BaseMiddleware):
    """Middleware для логирования ошибок в обработчиках"""

    async def __call__(self, handler, event: Update, data: dict):
        try:
            return await handler(event, data)
        except Exception as e:
            # Логируем ошибку
            await self.log_error(e, event)

            # Пытаемся уведомить пользователя
            await self.notify_user(event, e)

            # Для КРИТИЧЕСКИХ ошибок - передаём дальше (вызовет перезапуск бота)
            if self.is_critical_error(e):
                logger.critical("Критическая ошибка! Передаю исключение для перезапуска бота...")
                raise

            # Для не-критических ошибок - просто логируем и продолжаем
            return None

    async def log_error(self, error: Exception, event: Update):
        """Логирование ошибки с деталями"""
        error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Получаем ID пользователя
        user_id = None
        if hasattr(event, 'message') and event.message and hasattr(event.message, 'from_user'):
            user_id = event.message.from_user.id
        elif hasattr(event, 'callback_query') and event.callback_query:
            user_id = event.callback_query.from_user.id

        # Формируем сообщение об ошибке
        error_msg = (
            f"\n{'=' * 80}\n"
            f"🚨 ОШИБКА В ОБРАБОТЧИКЕ\n"
            f"{'=' * 80}\n"
            f"⏰ Время: {error_time}\n"
            f"👤 Пользователь ID: {user_id if user_id else 'N/A'}\n"
            f"🚨 Тип ошибки: {type(error).__name__}\n"
            f"📝 Сообщение: {str(error)}\n"
            f"📋 Трейсбэк:\n{traceback.format_exc()}\n"
            f"{'=' * 80}"
        )

        logger.error(error_msg)

        # Сохраняем в файл
        with open(HANDLER_ERRORS_FILE, 'a', encoding='utf-8') as f:
            f.write(error_msg)

    async def notify_user(self, event: Update, error: Exception):
        """Уведомление пользователя об ошибке"""
        try:
            if hasattr(event, 'message') and event.message:
                await event.message.answer(
                    "😕 Упс! Произошла техническая ошибка.\n"
                    "Мы уже работаем над её исправлением.\n"
                    "Попробуйте ещё раз через несколько минут."
                )
            elif hasattr(event, 'callback_query') and event.callback_query:
                await event.callback_query.message.answer(
                    "😕 Упс! Произошла техническая ошибка.\n"
                    "Мы уже работаем над её исправлением."
                )
                await event.callback_query.answer()
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя: {e}")

    def is_critical_error(self, error: Exception) -> bool:
        """Определяем, является ли ошибка критической"""
        critical_errors = (
            ZeroDivisionError,  # Деление на ноль
            MemoryError,  # Проблемы с памятью
            SystemExit,  # Выход из системы
            KeyboardInterrupt,  # Прерывание клавиатурой
            GeneratorExit,  # Выход из генератора
            asyncio.CancelledError,  # Отмененная задача
            ConnectionError,  # Ошибки соединения
            TimeoutError,  # Таймауты
            OSError,  # Ошибки ОС
        )

        # Также считаем критическими ошибки подключения к базе данных или API
        error_msg = str(error).lower()
        critical_keywords = [
            'database', 'sqlite', 'connection', 'timeout',
            'lost connection', 'operationalerror', 'api',
            'network', 'socket', 'connection refused'
        ]

        if any(keyword in error_msg for keyword in critical_keywords):
            return True

        return isinstance(error, critical_errors)

# ========== СОЗДАНИЕ БОТА И ДИСПЕТЧЕРА ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
vpn_manager = VPNManager()

# Регистрируем middleware
dp.update.outer_middleware(ErrorLoggingMiddleware())

# ========== ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК AIOGRAM ==========
@dp.error()
async def error_handler(error_event: ErrorEvent):
    """Глобальный обработчик ошибок aiogram"""
    error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    error_msg = (
        f"\n{'=' * 80}\n"
        f"🌐 ГЛОБАЛЬНАЯ ОШИБКА AIOGRAM\n"
        f"{'=' * 80}\n"
        f"⏰ Время: {error_time}\n"
        f"🚨 Тип: {type(error_event.exception).__name__}\n"
        f"📝 Сообщение: {str(error_event.exception)}\n"
        f"📋 Трейсбэк:\n{traceback.format_exc()}\n"
        f"{'=' * 80}"
    )

    logger.error(error_msg)

    # Сохраняем в файл
    with open(AIOGRAM_ERRORS_FILE, 'a', encoding='utf-8') as f:
        f.write(error_msg)

    return True


# Состояния для FSM
class UserStates(StatesGroup):
    waiting_for_renew_days = State()


class AdminStates(StatesGroup):
    waiting_for_user_to_renew = State()
    waiting_for_days_to_renew = State()
    waiting_for_user_to_delete = State()


# ========== КЛАВИАТУРЫ ==========
def get_user_keyboard(telegram_id):
    """Основная клавиатура"""
    user = get_user_by_telegram_id(telegram_id)

    keyboard_buttons = []

    if user:
        keyboard_buttons.extend([
            [KeyboardButton(text="👤 Мой аккаунт")],
            [KeyboardButton(text="💰 Купить подписку")],
            [KeyboardButton(text="🔁 Получить новую ссылку")],
            [KeyboardButton(text="📊 Мои платежи")]
        ])
    else:
        keyboard_buttons.extend([
            [KeyboardButton(text="🎁 Получить пробную подписку")],
            [KeyboardButton(text="💰 Купить подписку")]
        ])

    if telegram_id in ADMIN_IDS:
        keyboard_buttons.append([KeyboardButton(text="👑 Админ-панель")])

    return ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)


def get_admin_keyboard():
    """Клавиатура админ-панели"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Список пользователей", callback_data="admin_list_users")],
            [InlineKeyboardButton(text="❌ Удалить пользователя", callback_data="admin_delete_user")],
            [InlineKeyboardButton(text="🔄 Продлить пользователю", callback_data="admin_renew_user")],
            [InlineKeyboardButton(text="🔄 Синхронизировать БД", callback_data="admin_sync_db")],
            [InlineKeyboardButton(text="📋 Проверить расхождения", callback_data="admin_check_orphans")],
            [InlineKeyboardButton(text="📈 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="⬅️ На главную", callback_data="back_to_main")]
        ]
    )


# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id

    welcome_text = (
        "👋 Добро пожаловать в FlashLinkVPN бот!\n\n"
        f"🎁 Получите бесплатную пробную подписку на {TRIAL_DAYS} дней\n"
        "🔐 Безопасный и быстрый доступ к интернету\n"
        "🌍 Доступ к любым сайтам и сервисам"
    )

    await message.answer(welcome_text, reply_markup=get_user_keyboard(user_id))


@dp.message(lambda message: message.text == "🎁 Получить пробную подписку")
async def get_trial_subscription(message: types.Message):
    """Выдача пробной подписки"""
    user_id = message.from_user.id

    # Проверяем, есть ли уже пользователь
    existing_user = get_user_by_telegram_id(user_id)
    if existing_user:
        await message.answer("❌ У вас уже есть активная подписка!")
        return

    # Создаем клиента в 3x-ui
    result = vpn_manager.create_client(days=TRIAL_DAYS, email_prefix=f"user_{user_id}")

    if result['success']:
        # Сохраняем в БД
        add_user(
            telegram_id=user_id,
            client_email=result['email'],
            client_uuid=result['uuid'],
            sub_id=result['sub_id'],
            expiry_time=result['expiry_time']
        )

        # Генерируем ссылку
        vpn_link = vpn_manager.generate_vpn_link(result['uuid'], result['email'])

        success_text = (
            f"✅ Пробная подписка активирована!\n\n"
            f"📧 Email: {result['email']}\n"
            f"⏳ Срок действия: {vpn_manager.timestamp_to_date(result['expiry_time'])}\n"
            f"🔗 Ссылка для подключения:\n\n"
            f"<code>{vpn_link}</code>\n\n"
            f"⚠️ Сохраните эту ссылку в надежном месте!"
        )

        await message.answer(success_text, parse_mode="HTML")
        # Обновляем клавиатуру (убираем кнопку получения подписки)
        await message.answer("Теперь вы можете перейти в 'Мой аккаунт' для просмотра деталей.",
                             reply_markup=get_user_keyboard(user_id))
    else:
        await message.answer(f"❌ Ошибка при создании подписки: {result.get('error', 'Неизвестная ошибка')}")


# Обработчик кнопки "💰 Купить подписку"
@dp.message(lambda message: message.text == "💰 Купить подписку")
async def buy_subscription_start(message: types.Message):
    """Начало покупки подписки"""
    user_id = message.from_user.id

    # Инлайн-клавиатура с тарифами
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"30 дней - {SUBSCRIPTION_PRICES.get(30)}₽", callback_data="buy_30"),
                InlineKeyboardButton(text=f"90 дней - {SUBSCRIPTION_PRICES.get(90)}₽", callback_data="buy_90")
            ],
            [
                InlineKeyboardButton(text=f"180 дней - {SUBSCRIPTION_PRICES.get(180)}₽", callback_data="buy_180"),
                InlineKeyboardButton(text=f"365 дней - {SUBSCRIPTION_PRICES.get(365)}₽", callback_data="buy_365")
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ]
    )

    await message.answer(
        "🎯 Выберите тариф подписки:\n\n"
        f"• 30 дней - {SUBSCRIPTION_PRICES.get(30)}₽\n"
        f"• 90 дней - {SUBSCRIPTION_PRICES.get(90)}₽ (экономьте 66₽ в месяц!)\n"
        f"• 180 дней - {SUBSCRIPTION_PRICES.get(180)}₽ (экономьте 83₽ в месяц!)\n"
        f"• 365 дней - {SUBSCRIPTION_PRICES.get(365)}₽ (экономьте 92₽ в месяц!)\n\n"
        "💳 Оплата через Яндекс Кассу (карты, ЮMoney и др.)",
        reply_markup=keyboard
    )


@dp.callback_query(lambda c: c.data.startswith('buy_'))
async def process_payment_start(callback: types.CallbackQuery):
    """Обработка выбора тарифа и создание платежа"""
    days_map = {
        'buy_30': 30,
        'buy_90': 90,
        'buy_180': 180,
        'buy_365': 365
    }

    days = days_map.get(callback.data)
    if not days:
        await callback.answer("Неверный выбор")
        return

    user_id = callback.from_user.id
    amount = SUBSCRIPTION_PRICES.get(days, 299)

    # Создаем описание платежа
    description = f"VPN подписка на {days} дней для пользователя {user_id}"

    # Метаданные для вебхука
    metadata = {
        "user_id": user_id,
        "days": days,
        "telegram_username": callback.from_user.username or "",
        "telegram_first_name": callback.from_user.first_name or ""
    }

    # Создаем платеж в ЮKassa
    payment_result = await yookassa.create_payment(
        amount=amount,
        description=description,
        return_url=YOOKASSA_RETURN_URL,
        metadata=metadata
    )

    if payment_result['success']:
        # Сохраняем платеж в БД
        payment_id = payment_result['payment_id']
        create_payment(user_id, payment_id, amount * 100, days, description)    # database.py function

        # Отправляем пользователю ссылку для оплаты
        confirmation_url = payment_result['confirmation_url']

        payment_message = (
            f"✅ Платеж создан!\n\n"
            f"📅 Тариф: {days} дней\n"
            f"💰 Сумма: {amount}₽\n"
            f"📝 Описание: {description}\n\n"
            f"Для оплаты перейдите по ссылке:\n{confirmation_url}\n\n"
            f"После оплаты подписка активируется автоматически в течение 1-2 минут."
        )

        # Инлайн-кнопка для перехода к оплате
        payment_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перейти к оплате", url=confirmation_url)],
                [InlineKeyboardButton(text="🔄 Проверить статус", callback_data=f"check_payment_{payment_id}")]
            ]
        )

        await callback.message.answer(payment_message, reply_markup=payment_keyboard)
    else:
        await callback.message.answer(
            f"❌ Ошибка при создании платежа:\n{payment_result.get('error', 'Неизвестная ошибка')}"
        )

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('check_payment_'))
async def check_payment_status(callback: types.CallbackQuery):
    """Проверка статуса платежа по кнопке"""
    payment_id = callback.data.replace('check_payment_', '')

    # Получаем статус платежа
    status_result = await yookassa.get_payment_status(payment_id)

    if status_result['success']:
        status = status_result['status']

        if status == 'succeeded':
            await callback.message.answer("✅ Платеж успешно завершен! Подписка активирована.")
        elif status == 'pending':
            await callback.message.answer("⏳ Платеж в обработке. Пожалуйста, подождите...")
        elif status == 'canceled':
            await callback.message.answer("❌ Платеж отменен.")
        else:
            await callback.message.answer(f"Статус платежа: {status}")
    else:
        await callback.message.answer("❌ Не удалось проверить статус платежа.")

    await callback.answer()


# Обработчик "📊 Мои платежи"
@dp.message(lambda message: message.text == "📊 Мои платежи")
async def my_payments(message: types.Message):
    """Показать историю платежей пользователя"""
    user_id = message.from_user.id
    payments = get_user_payments(user_id, limit=10)     # database.py function

    if not payments:
        await message.answer("📭 У вас пока нет платежей.")
        return

    text = "📊 Ваши последние платежи:\n\n"

    for i, payment in enumerate(payments, 1):
        amount_rub = payment['amount'] / 100
        status_emoji = {
            'succeeded': '✅',
            'pending': '⏳',
            'canceled': '❌'
        }.get(payment['status'], '❓')

        created = datetime.fromisoformat(payment['created_at'].replace('Z', '+00:00'))
        created_str = created.strftime('%d.%m.%Y %H:%M')

        text += (
            f"{i}. {status_emoji} {amount_rub}₽ за {payment['days']} дней\n"
            f"   Статус: {payment['status']}\n"
            f"   Дата: {created_str}\n"
            f"   ID: {payment['payment_id'][:8]}...\n"
            f"   ---\n"
        )

    await message.answer(text)

@dp.message(lambda message: message.text == "👤 Мой аккаунт")
async def my_account(message: types.Message):
    """Информация об аккаунте пользователя с трафиком из панели"""
    user_id = message.from_user.id
    user = get_user_by_telegram_id(user_id)

    if not user:
        await message.answer("❌ У вас нет активной подписки. Получите пробную подписку!")
        return

    # Проверяем, существует ли клиент в панели
    if not vpn_manager.client_exists(user['client_email']):
        # Клиент не существует - удаляем из БД
        delete_user_by_email(user['client_email'])
        await message.answer(
            "❌ Ваша подписка не найдена в системе.\n"
            "Возможно, она была удалена администратором.\n\n"
            "Пожалуйста, создайте новую подписку.",
            reply_markup=get_user_keyboard(user_id)
        )
        return

    # Получаем трафик напрямую из панели
    traffic_gb = vpn_manager.get_client_traffic(user['client_email'])

    # Получаем информацию
    expiry_date = vpn_manager.timestamp_to_date(user['expiry_time'])
    days_left = vpn_manager.get_days_left(user['expiry_time'])

    # Генерируем ссылку
    vpn_link = vpn_manager.generate_vpn_link(user['client_uuid'], user['client_email'])

    account_text = (
        f"👤 Ваш аккаунт\n\n"
        f"📧 Email: {user['client_email']}\n"
        f"⏳ Срок действия: {expiry_date}\n"
        f"📅 Осталось дней: {days_left}\n"
        f"📊 Трафик: {traffic_gb:.2f} GB\n\n"
        f"🔗 Ваша ссылка для подключения (нажмите чтобы скопировать):\n\n"
        f"<code>{vpn_link}</code>"
    )

    await message.answer(account_text, parse_mode="HTML")


@dp.message(lambda message: message.text == "🔁 Получить новую ссылку")
async def regenerate_vpn_link(message: types.Message):
    """Генерация новой VPN-ссылки для пользователя с активной подпиской"""
    user_id = message.from_user.id
    user = get_user_by_telegram_id(user_id)

    if not user:
        await message.answer("❌ У вас нет активной подписки. Получите пробную или купите подписку.")
        return

    # 1. ПРОВЕРЯЕМ, АКТИВНА ЛИ ПОДПИСКА (оставшиеся дни > 0)
    days_left = vpn_manager.get_days_left(user['expiry_time'])

    # Проверяем, что days_left — это число и оно больше 0
    # get_days_left может вернуть "∞" для бессрочной подписки, поэтому нужна проверка
    is_subscription_active = False
    remaining_days = 0

    if isinstance(days_left, str) and days_left == "∞":
        # Бессрочная подписка — считаем активной
        is_subscription_active = True
        remaining_days = 0  # Для создания клиента
    elif isinstance(days_left, int) and days_left > 0:
        # Подписка активна, осталось дней > 0
        is_subscription_active = True
        remaining_days = days_left
    else:
        # Подписка истекла (days_left == 0) или некорректный формат
        is_subscription_active = False

    if not is_subscription_active:
        # Подписка истекла — сообщаем и предлагаем купить новую
        expiry_date = vpn_manager.timestamp_to_date(user['expiry_time'])
        await message.answer(
            f"⏳ Ваша подписка истекла {expiry_date}.\n\n"
            f"Чтобы получить новую ссылку, необходимо продлить подписку.\n"
            f"Используйте кнопку <b>💰 Купить подписку</b>.",
            parse_mode="HTML"
        )
        return

    # 2. ЕСЛИ ПОДПИСКА АКТИВНА — ПЕРЕГЕНЕРИРУЕМ ССЫЛКУ
    try:
        # Проверяем, существует ли старый клиент в панели
        if not vpn_manager.client_exists(user['client_email']):
            await message.answer("⚠️ Ваш старый аккаунт не найден. Создаём новый...")

        # Удаляем старого клиента из панели (игнорируем ошибки, если его уже нет)
        vpn_manager.delete_client(user['client_uuid'])

        # Создаём нового клиента в панели с ТЕМ ЖЕ СРОКОМ ДЕЙСТВИЯ
        email_prefix = user['client_email'].split('_')[0] if '_' in user['client_email'] else 'user'
        result = vpn_manager.create_client(
            days=remaining_days,
            email_prefix=f"{email_prefix}_{user_id}"
        )

        if not result['success']:
            await message.answer(f"❌ Ошибка при создании нового клиента: {result.get('error', 'Неизвестная ошибка')}")
            return

        # Обновляем данные пользователя в БД
        success = update_user_client(
            telegram_id=user_id,
            new_client_email=result['email'],
            new_client_uuid=result['uuid'],
            new_sub_id=result['sub_id']
        )

        if not success:
            await message.answer("❌ Ошибка при обновлении данных в базе.")
            return

        # Генерируем и отправляем новую ссылку
        new_vpn_link = vpn_manager.generate_vpn_link(result['uuid'], result['email'])

        # Формируем сообщение об успехе
        success_message = (
            f"✅ Новая ссылка успешно создана!\n\n"
            f"📧 Новый email: {result['email']}\n"
        )

        # Добавляем информацию об оставшемся сроке, если он не бессрочный
        if remaining_days > 0:
            success_message += f"⏳ Осталось дней: {remaining_days}\n"
        elif remaining_days == 0 and isinstance(days_left, str):
            success_message += f"⏳ Срок: Бессрочная подписка\n"

        success_message += (
            f"\n🔗 Новая ссылка для подключения (нажмите чтобы скопировать):\n\n"
            f"<code>{new_vpn_link}</code>\n\n"
            f"⚠️ Сохраните эту ссылку в надёжном месте!"
        )

        await message.answer(success_message, parse_mode="HTML")
        logger.info(f"Пользователь {user_id} перегенерировал ссылку. Осталось дней: {remaining_days}")

    except Exception as e:
        logger.error(f"Ошибка при перегенерации ссылки для {user_id}: {e}")
        await message.answer("❌ Произошла техническая ошибка при создании новой ссылки.")

@dp.message(lambda message: message.text == "👑 Админ-панель")
async def admin_panel(message: types.Message):
    """Доступ к админ-панели"""
    user_id = message.from_user.id

    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к админ-панели!")
        return

    await message.answer("👑 Админ-панель", reply_markup=get_admin_keyboard())


# ========== АДМИН-ОБРАБОТЧИКИ ==========
@dp.callback_query(lambda c: c.data == "admin_list_users")
async def admin_list_users(callback: types.CallbackQuery):
    """Показать список всех пользователей с трафиком из панели"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    users = get_all_users()

    if not users:
        await callback.message.answer("📭 Нет зарегистрированных пользователей")
        await callback.answer()
        return

    # Получаем трафик ВСЕХ клиентов одним запросом
    all_traffic = vpn_manager.get_all_clients_traffic()

    text = "📊 Список пользователей:\n\n"
    for user in users:
        expiry_date = vpn_manager.timestamp_to_date(user['expiry_time'])
        days_left = vpn_manager.get_days_left(user['expiry_time'])

        # Получаем трафик из общего словаря
        traffic_gb = all_traffic.get(user['client_email'], 0)

        text += (
            f"👤 Telegram ID: {user['telegram_id']}\n"
            f"📧 Email: {user['client_email']}\n"
            f"⏳ До: {expiry_date} (осталось: {days_left} дней)\n"
            f"📊 Трафик: {traffic_gb:.2f} GB\n"
            f"---\n"
        )

    await callback.message.answer(text[:4000])  # Ограничение Telegram
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_delete_user")
async def admin_delete_user_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало удаления пользователя"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    # Получаем список пользователей для выбора
    users = get_all_users()

    if not users:
        await callback.message.answer("📭 Нет пользователей для удаления")
        await callback.answer()
        return

    # Создаем клавиатуру с пользователями
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for user in users[:50]:  # Ограничиваем 50 пользователями
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{user['client_email']}",
                callback_data=f"delete_{user['client_email']}"
            )
        ])

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])

    await callback.message.answer("Выберите пользователя для удаления:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('delete_'))
async def admin_delete_user_confirm(callback: types.CallbackQuery):
    """Подтверждение удаления пользователя"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    client_email = callback.data.replace('delete_', '')

    # Создаем клавиатуру подтверждения
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{client_email}")],
            [InlineKeyboardButton(text="❌ Нет, отмена", callback_data="back_to_admin")]
        ]
    )

    await callback.message.answer(
        f"Вы уверены, что хотите удалить пользователя {client_email}?",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('confirm_delete_'))
async def admin_delete_user_execute(callback: types.CallbackQuery):
    """Выполнение удаления пользователя"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    client_email = callback.data.replace('confirm_delete_', '')

    # Получаем пользователя из БД
    user = get_user_by_client_email(client_email)
    if not user:
        await callback.message.answer("❌ Пользователь не найден")
        await callback.answer()
        return

    # Удаляем из 3x-ui
    success = vpn_manager.delete_client(user['client_uuid'])

    if success:
        # Удаляем из БД
        delete_user_by_email(client_email)
        await callback.message.answer(f"✅ Пользователь {client_email} удален!")
    else:
        await callback.message.answer(f"❌ Ошибка при удалении пользователя")

    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_renew_user")
async def admin_renew_user_start(callback: types.CallbackQuery):
    """Начало продления подписки админом"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    users = get_all_users()

    if not users:
        await callback.message.answer("📭 Нет пользователей для продления")
        await callback.answer()
        return

    # Создаем клавиатуру с пользователями
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for user in users[:50]:  # Ограничиваем 50 пользователями
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{user['client_email']}",
                callback_data=f"admin_renew_email_{user['client_email']}"
            )
        ])

    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")])

    await callback.message.answer("Выберите пользователя для продления:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('admin_renew_email'))
async def admin_renew_user_select(callback: types.CallbackQuery, state: FSMContext):
    """Пользователь выбран для продления"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    client_email = callback.data.replace('admin_renew_email_', '')

    # Сохраняем email в состоянии
    await state.update_data(client_email=client_email)

    # Предлагаем выбрать количество дней
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="30 дней", callback_data="admin_renew_days_30")],
            [InlineKeyboardButton(text="90 дней", callback_data="admin_renew_days_90")],
            [InlineKeyboardButton(text="180 дней", callback_data="admin_renew_days_180")],
            [InlineKeyboardButton(text="365 дней", callback_data="admin_renew_days_365")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
        ]
    )

    await callback.message.answer(
        f"Пользователь: {client_email}\n"
        f"Выберите количество дней для продления:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('admin_renew_days_'))
async def admin_renew_user_process(callback: types.CallbackQuery, state: FSMContext):
    """Обработка продления подписки админом"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    days_map = {
        'admin_renew_days_30': 30,
        'admin_renew_days_90': 90,
        'admin_renew_days_180': 180,
        'admin_renew_days_365': 365
    }

    days = days_map.get(callback.data)
    if not days:
        await callback.answer("Неверный выбор")
        return

    # Получаем данные из состояния
    data = await state.get_data()
    client_email = data.get('client_email')

    if not client_email:
        await callback.message.answer("❌ Ошибка: пользователь не найден")
        await state.clear()
        return

    # Находим пользователя в БД
    user = get_user_by_client_email(client_email)
    if not user:
        await callback.message.answer(f"❌ Пользователь {client_email} не найден")
        await state.clear()
        return

    # Рассчитываем новый срок
    current_expiry = user['expiry_time'] if user['expiry_time'] > 0 else int(time.time() * 1000)
    new_expiry = current_expiry + (days * 24 * 60 * 60 * 1000)

    # Обновляем в 3x-ui
    success = vpn_manager.update_client(
        user['client_uuid'],
        user['client_email'],
        user['sub_id'],
        new_expiry
    )

    if success:
        # Обновляем в БД
        update_user_expiry(user['telegram_id'], new_expiry)

        await callback.message.answer(
            f"✅ Подписка пользователя {client_email} продлена на {days} дней!\n"
            f"Новый срок действия: {vpn_manager.timestamp_to_date(new_expiry)}"
        )
    else:
        await callback.message.answer(f"❌ Ошибка при продлении подписки для {client_email}")

    await state.clear()
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    """Статистика бота с трафиком из панели"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    users = get_all_users()
    total_users = len(users)

    # Получаем трафик ВСЕХ клиентов одним запросом
    all_traffic = vpn_manager.get_all_clients_traffic()

    # Статистика по активным/неактивным подпискам
    now_ms = int(time.time() * 1000)
    active_users = 0
    expired_users = 0
    unlimited_users = 0
    total_traffic_gb = 0

    for user in users:
        # Суммируем трафик
        traffic_gb = all_traffic.get(user['client_email'], 0)
        total_traffic_gb += traffic_gb

        # Статус подписки
        expiry_time = user.get('expiry_time', 0)
        if expiry_time == 0:
            unlimited_users += 1
            active_users += 1
        elif expiry_time > now_ms:
            active_users += 1
        else:
            expired_users += 1

    text = (
        f"📈 Статистика бота\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Активных подписок: {active_users}\n"
        f"❌ Истекших подписок: {expired_users}\n"
        f"∞ Бессрочных подписок: {unlimited_users}\n"
        f"📊 Общий трафик: {total_traffic_gb:.2f} GB\n"
        f"📅 Время сервера: {vpn_manager.timestamp_to_date(now_ms)}"
    )

    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    """Возврат в админ-панель"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    await callback.message.edit_text("👑 Админ-панель", reply_markup=get_admin_keyboard())
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    """Возврат на главную"""
    user_id = callback.from_user.id
    await callback.message.edit_text("Главное меню")
    await callback.message.answer("Вы вернулись в главное меню", reply_markup=get_user_keyboard(user_id))
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_check_orphans")
async def admin_check_orphans(callback: types.CallbackQuery):
    """Проверка расхождений между БД и панелью"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    orphaned_users = get_orphaned_users(vpn_manager)

    if not orphaned_users:
        await callback.message.answer("✅ Расхождений не обнаружено! Все пользователи в БД существуют в панели.")
        await callback.answer()
        return

    text = "⚠️ Обнаружены расхождения:\n\n"
    for i, user in enumerate(orphaned_users, 1):
        text += f"{i}. Telegram ID: {user['telegram_id']}\n"
        text += f"   Email: {user['email']}\n"
        text += f"   UUID: {user['uuid'][:8]}...\n"
        text += "   ---\n"

    text += f"\nВсего несуществующих пользователей: {len(orphaned_users)}"

    # Создаем клавиатуру для действий
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Автоочистка", callback_data="admin_auto_cleanup")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
        ]
    )

    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_auto_cleanup")
async def admin_auto_cleanup(callback: types.CallbackQuery):
    """Автоматическая очистка несуществующих пользователей"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    deleted_users = validate_and_sync_users(vpn_manager)

    if not deleted_users:
        await callback.message.answer("✅ Нечего удалять. БД уже синхронизирована.")
    else:
        text = f"✅ Удалено {len(deleted_users)} несуществующих пользователей:\n\n"
        for user in deleted_users:
            text += f"• {user['email']} (Telegram ID: {user['telegram_id']})\n"

        await callback.message.answer(text[:4000])

    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_sync_db")
async def admin_sync_db(callback: types.CallbackQuery):
    """Полная синхронизация БД с панелью"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа!")
        return

    # Получаем всех пользователей из БД и панели
    db_users = get_all_users()
    panel_traffic = vpn_manager.get_all_clients_traffic()
    panel_emails = set(panel_traffic.keys())

    if not db_users:
        await callback.message.answer("📭 В БД нет пользователей")
        await callback.answer()
        return

    # Создаем отчет
    text = "🔄 Результаты синхронизации:\n\n"

    # Пользователи только в БД (орфаны)
    orphaned = []
    for user in db_users:
        if user['client_email'] not in panel_emails:
            orphaned.append(user)

    # Пользователи только в панели (новые, не зарегистрированные в боте)
    new_in_panel = []
    for email in panel_emails:
        found = False
        for user in db_users:
            if user['client_email'] == email:
                found = True
                break
        if not found:
            new_in_panel.append(email)

    # Удаляем орфанов
    for user in orphaned:
        delete_user_by_email(user['client_email'])

    text += f"🗑️ Удалено из БД: {len(orphaned)}\n"
    text += f"🆕 Новых в панели: {len(new_in_panel)}\n"
    text += f"✅ В синхронизации: {len(db_users) - len(orphaned)}\n"
    text += f"📊 Всего в панели: {len(panel_emails)}\n\n"

    if orphaned:
        text += "Удаленные пользователи:\n"
        for user in orphaned[:10]:  # Показываем только первые 10
            text += f"• {user['client_email']}\n"
        if len(orphaned) > 10:
            text += f"... и еще {len(orphaned) - 10}\n"

    if new_in_panel:
        text += "\nПользователи в панели, но не в БД:\n"
        for email in new_in_panel[:10]:
            text += f"• {email}\n"
        if len(new_in_panel) > 10:
            text += f"... и еще {len(new_in_panel) - 10}\n"

    await callback.message.answer(text[:4000])
    await callback.answer()


# ========== ОСНОВНАЯ ФУНКЦИЯ С ПЕРЕЗАПУСКОМ ==========
async def main():
    """Основная функция с защитой от падений и улучшенным логированием"""
    max_restarts = 10
    restart_delay = 5
    restart_count = 0
    start_time = datetime.now()

    # Файл для статистики перезапусков
    STATS_FILE = os.path.join(LOG_DIR, 'restart_stats.log')

    logger.info("=" * 50)
    logger.info(f"🚀 ИНИЦИАЛИЗАЦИЯ VPN БОТА - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    # Записываем статистику запуска
    with open(STATS_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{'=' * 60}\n")
        f.write(f"НОВЫЙ ЗАПУСК БОТА: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'=' * 60}\n")

    while restart_count < max_restarts:
        try:
            logger.info(f"▶️ ЗАПУСК БОТА (попытка {restart_count + 1}/{max_restarts})")

            # Запускаем polling
            await dp.start_polling(bot)

            # Если дошли сюда - бот завершился нормально
            logger.info("✅ Бот завершил работу нормально")

            # Записываем успешное завершение
            with open(STATS_FILE, 'a', encoding='utf-8') as f:
                f.write(f"✅ Бот завершен: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"   Всего перезапусков: {restart_count}\n")

            break

        except asyncio.CancelledError:
            logger.info("⏹️ Работа бота завершена (CancelledError)")
            break

        except KeyboardInterrupt:
            logger.info("⏹️ Бот остановлен пользователем (Ctrl+C)")
            break

        except Exception as e:
            restart_count += 1
            error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Логируем ошибку основного цикла
            logger.critical(f"\n💥 КРИТИЧЕСКАЯ ОШИБКА В ОСНОВНОМ ЦИКЛЕ:")
            logger.critical(f"⏰ Время: {error_time}")
            logger.critical(f"🚨 Тип: {type(e).__name__}")
            logger.critical(f"📝 Сообщение: {str(e)}")
            logger.critical(f"📋 Трейсбэк:\n{traceback.format_exc()}")

            # Сохраняем в файл ошибок основного цикла
            with open(MAIN_LOOP_CRASHES_FILE, 'a', encoding='utf-8') as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"Время: {error_time}\n")
                f.write(f"Попытка перезапуска: {restart_count}/{max_restarts}\n")
                f.write(f"Ошибка: {type(e).__name__}: {str(e)}\n")
                f.write(f"Трейсбэк:\n{traceback.format_exc()}\n")
                f.write(f"{'=' * 80}\n")

            # Записываем статистику перезапуска
            with open(STATS_FILE, 'a', encoding='utf-8') as f:
                f.write(f"🔄 Перезапуск #{restart_count}: {error_time}\n")
                f.write(f"   Ошибка: {type(e).__name__}\n")
                f.write(f"   Задержка: {restart_delay:.1f} сек\n")

            if restart_count < max_restarts:
                # Экспоненциальная задержка
                restart_delay = min(restart_delay * 1.5, 60)
                logger.warning(f"🔄 Перезапуск через {restart_delay:.1f} секунд...")

                # Очистка ресурсов
                try:
                    await bot.session.close()
                except Exception as cleanup_error:
                    logger.error(f"Ошибка при очистке сессии: {cleanup_error}")

                # Ждем перед перезапуском
                await asyncio.sleep(restart_delay)

                # Логируем успешный перезапуск
                logger.info(f"🔄 Перезапуск {restart_count} выполнен успешно")
            else:
                logger.critical(f"❌ Достигнут лимит перезапусков ({max_restarts})")

                # Записываем финальную статистику
                end_time = datetime.now()
                uptime = end_time - start_time

                with open(STATS_FILE, 'a', encoding='utf-8') as f:
                    f.write(f"\n❌ ЛИМИТ ПЕРЕЗАПУСКОВ ДОСТИГНУТ\n")
                    f.write(f"Время работы: {uptime}\n")
                    f.write(f"Финальное время: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Причина остановки: {type(e).__name__}: {str(e)[:200]}\n")
                    f.write(f"{'=' * 60}\n")

                break


# ========== ЗАПУСК ==========
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Бот остановлен")
    except Exception as e:
        print(f"\n❌ Фатальная ошибка при запуске: {e}")
        traceback.print_exc()
