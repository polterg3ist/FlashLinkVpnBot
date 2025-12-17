import asyncio
import logging
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS, TRIAL_DAYS
from database import (
    get_user_by_telegram_id, add_user, update_user_expiry,
    get_all_users, delete_user_by_email, get_user_by_client_email
)
from vpn_manager import VPNManager

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация менеджера VPN
vpn_manager = VPNManager()


# Состояния для FSM
class UserStates(StatesGroup):
    waiting_for_renew_days = State()


class AdminStates(StatesGroup):
    waiting_for_user_to_renew = State()
    waiting_for_days_to_renew = State()
    waiting_for_user_to_delete = State()


# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(telegram_id):
    """Основная клавиатура"""
    user = get_user_by_telegram_id(telegram_id)
    is_admin = telegram_id in ADMIN_IDS

    keyboard_buttons = []

    # Если у пользователя нет аккаунта, показываем кнопку получения подписки
    if not user:
        keyboard_buttons.append([KeyboardButton(text="🎁 Получить пробную подписку")])
    else:
        # Если аккаунт есть, показываем стандартные кнопки
        keyboard_buttons.extend([
            [KeyboardButton(text="👤 Мой аккаунт")],
            [KeyboardButton(text="🔄 Продлить подписку")]
        ])

    if is_admin:
        keyboard_buttons.append([KeyboardButton(text="👑 Админ-панель")])

    return ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)


def get_admin_keyboard():
    """Клавиатура админ-панели"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Список пользователей", callback_data="admin_list_users")],
            [InlineKeyboardButton(text="❌ Удалить пользователя", callback_data="admin_delete_user")],
            [InlineKeyboardButton(text="🔄 Продлить пользователю", callback_data="admin_renew_user")],
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
        "👋 Добро пожаловать в VPN бот!\n\n"
        "🎁 Получите бесплатную пробную подписку на 30 дней\n"
        "🔐 Безопасный и быстрый доступ к интернету\n"
        "🌍 Доступ к любым сайтам и сервисам"
    )

    await message.answer(welcome_text, reply_markup=get_main_keyboard(user_id))


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
                             reply_markup=get_main_keyboard(user_id))
    else:
        await message.answer(f"❌ Ошибка при создании подписки: {result.get('error', 'Неизвестная ошибка')}")


@dp.message(lambda message: message.text == "👤 Мой аккаунт")
async def my_account(message: types.Message):
    """Информация об аккаунте пользователя с трафиком из панели"""
    user_id = message.from_user.id
    user = get_user_by_telegram_id(user_id)

    if not user:
        await message.answer("❌ У вас нет активной подписки. Получите пробную подписку!")
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
        f"🔗 Ваша ссылка для подключения:\n"
        f"<code>{vpn_link}</code>"
    )

    await message.answer(account_text, parse_mode="HTML")


@dp.message(lambda message: message.text == "🔄 Продлить подписку")
async def renew_subscription_start(message: types.Message, state: FSMContext):
    """Начало процесса продления подписки"""
    user_id = message.from_user.id
    user = get_user_by_telegram_id(user_id)

    if not user:
        await message.answer("❌ У вас нет активной подписки!")
        return

    # Показываем варианты продления (без оплаты)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="30 дней", callback_data="renew_30")],
            [InlineKeyboardButton(text="90 дней", callback_data="renew_90")],
            [InlineKeyboardButton(text="180 дней", callback_data="renew_180")],
            [InlineKeyboardButton(text="365 дней", callback_data="renew_365")]
        ]
    )

    await message.answer("Выберите период продления:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith('renew_'))
async def process_renewal(callback: types.CallbackQuery):
    """Обработка выбора периода продления"""
    days_map = {
        'renew_30': 30,
        'renew_90': 90,
        'renew_180': 180,
        'renew_365': 365
    }

    days = days_map.get(callback.data)
    if not days:
        await callback.answer("Неверный выбор")
        return

    user_id = callback.from_user.id
    user = get_user_by_telegram_id(user_id)

    if not user:
        await callback.message.answer("❌ У вас нет активной подписки!")
        await callback.answer()
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
        update_user_expiry(user_id, new_expiry)

        await callback.message.answer(
            f"✅ Подписка продлена на {days} дней!\n"
            f"Новый срок действия: {vpn_manager.timestamp_to_date(new_expiry)}"
        )
    else:
        await callback.message.answer("❌ Ошибка при продлении подписки")

    await callback.answer()


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
    await callback.message.answer("Вы вернулись в главное меню", reply_markup=get_main_keyboard(user_id))
    await callback.answer()


# ========== ЗАПУСК БОТА ==========
async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())