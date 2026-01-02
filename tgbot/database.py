import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

# Создаем папку для базы данных, если она не существует
DB_DIR = 'data'
DB_PATH = os.path.join(DB_DIR, 'database.db')

if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)
    print(f"✅ Создана папка для базы данных: {DB_DIR}")


@contextmanager
def get_db():
    """Контекстный менеджер для подключения к базе данных"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        print(f"❌ Ошибка базы данных: {e}")
        raise
    finally:
        if conn:
            conn.close()


def init_db():
    """Инициализация базы данных (создание таблиц)"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Таблица пользователей
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                client_email TEXT NOT NULL,
                client_uuid TEXT NOT NULL,
                sub_id TEXT NOT NULL,
                expiry_time INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                total_traffic_mb INTEGER DEFAULT 0,
                last_traffic_update TIMESTAMP
            )
            ''')

            # таблица с оплатами:
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                payment_id TEXT UNIQUE NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT DEFAULT 'RUB',
                status TEXT DEFAULT 'pending',
                description TEXT,
                days INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (telegram_id)
            )
            ''')

            # Индексы для быстрого поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments (payment_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status)')

            # Создаем индекс для быстрого поиска по telegram_id
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_users_telegram_id 
            ON users (telegram_id)
            ''')

            conn.commit()
            print(f"✅ База данных инициализирована: {DB_PATH}")

    except sqlite3.Error as e:
        print(f"❌ Ошибка при инициализации базы данных: {e}")
        raise


def add_user(telegram_id, client_email, client_uuid, sub_id, expiry_time=0):
    """Добавление нового пользователя"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO users (telegram_id, client_email, client_uuid, sub_id, expiry_time)
            VALUES (?, ?, ?, ?, ?)
            ''', (telegram_id, client_email, client_uuid, sub_id, expiry_time))
            conn.commit()
            print(f"✅ Пользователь {telegram_id} добавлен в БД")
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        print(f"⚠️ Пользователь {telegram_id} уже существует в БД")
        return None
    except sqlite3.Error as e:
        print(f"❌ Ошибка при добавлении пользователя: {e}")
        return None


def get_user_by_telegram_id(telegram_id):
    """Получение пользователя по Telegram ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            user = cursor.fetchone()
            return dict(user) if user else None
    except sqlite3.Error as e:
        print(f"❌ Ошибка при получении пользователя {telegram_id}: {e}")
        return None


def update_user_expiry(telegram_id, new_expiry_time):
    """Обновление срока действия подписки пользователя"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE users 
            SET expiry_time = ?, is_active = 1 
            WHERE telegram_id = ?
            ''', (new_expiry_time, telegram_id))
            conn.commit()
            print(f"✅ Обновлен срок подписки для пользователя {telegram_id}")
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        print(f"❌ Ошибка при обновлении пользователя {telegram_id}: {e}")
        return False


def update_user_traffic(telegram_id, total_traffic_mb):
    """Обновление трафика пользователя"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE users 
            SET total_traffic_mb = ?, last_traffic_update = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
            ''', (total_traffic_mb, telegram_id))
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        print(f"❌ Ошибка при обновлении трафика пользователя {telegram_id}: {e}")
        return False


def get_all_users():
    """Получение списка всех пользователей"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
            users = cursor.fetchall()
            return [dict(user) for user in users]
    except sqlite3.Error as e:
        print(f"❌ Ошибка при получении списка пользователей: {e}")
        return []


def delete_user_by_email(client_email):
    """Удаление пользователя по email клиента"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE client_email = ?', (client_email,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                print(f"✅ Пользователь {client_email} удален из БД")
            return deleted
    except sqlite3.Error as e:
        print(f"❌ Ошибка при удалении пользователя {client_email}: {e}")
        return False


def get_user_by_client_email(client_email):
    """Получение пользователя по email клиента"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE client_email = ?', (client_email,))
            user = cursor.fetchone()
            return dict(user) if user else None
    except sqlite3.Error as e:
        print(f"❌ Ошибка при поиске пользователя по email {client_email}: {e}")
        return None


def validate_and_sync_users(vpn_manager):
    """
    Проверяет пользователей в БД и синхронизирует с панелью 3x-ui.
    Возвращает список удаленных пользователей.
    """
    deleted_users = []

    try:
        # Получаем всех пользователей из БД
        db_users = get_all_users()
        if not db_users:
            return deleted_users

        # Получаем всех клиентов из панели 3x-ui
        all_clients_traffic = vpn_manager.get_all_clients_traffic()  # {email: traffic}
        panel_emails = set(all_clients_traffic.keys())

        # Проверяем каждого пользователя из БД
        for user in db_users:
            client_email = user['client_email']

            # Если пользователя нет в панели, удаляем из БД
            if client_email not in panel_emails:
                delete_user_by_email(client_email)
                deleted_users.append({
                    'telegram_id': user['telegram_id'],
                    'email': client_email,
                    'reason': 'Пользователь отсутствует в панели 3x-ui'
                })
                print(f"⚠️ Удален несуществующий пользователь: {client_email}")

    except Exception as e:
        print(f"❌ Ошибка при синхронизации БД с панелью: {e}")

    return deleted_users


def get_orphaned_users(vpn_manager):
    """
    Получает список пользователей из БД, которых нет в панели 3x-ui
    (не удаляет их, только проверяет).
    """
    orphaned_users = []

    try:
        db_users = get_all_users()
        if not db_users:
            return orphaned_users

        all_clients_traffic = vpn_manager.get_all_clients_traffic()
        panel_emails = set(all_clients_traffic.keys())

        for user in db_users:
            if user['client_email'] not in panel_emails:
                orphaned_users.append({
                    'telegram_id': user['telegram_id'],
                    'email': user['client_email'],
                    'uuid': user['client_uuid']
                })

    except Exception as e:
        print(f"❌ Ошибка при поиске несуществующих пользователей: {e}")

    return orphaned_users


# ОПЛАТА
def create_payment(user_id, payment_id, amount, days, description=""):
    """Создание записи о платеже"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO payments (user_id, payment_id, amount, days, description, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            ''', (user_id, payment_id, amount, days, description))
            conn.commit()
            return cursor.lastrowid
    except sqlite3.Error as e:
        print(f"❌ Ошибка при создании платежа: {e}")
        return None

def update_payment_status(payment_id, status):
    """Обновление статуса платежа"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE payments 
            SET status = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE payment_id = ?
            ''', (status, payment_id))
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        print(f"❌ Ошибка при обновлении платежа: {e}")
        return False

def get_payment_by_id(payment_id):
    """Получение платежа по ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM payments WHERE payment_id = ?', (payment_id,))
            payment = cursor.fetchone()
            return dict(payment) if payment else None
    except sqlite3.Error as e:
        print(f"❌ Ошибка при получении платежа: {e}")
        return None

def get_user_payments(user_id, limit=10):
    """Получение платежей пользователя"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM payments 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
            ''', (user_id, limit))
            payments = cursor.fetchall()
            return [dict(payment) for payment in payments]
    except sqlite3.Error as e:
        print(f"❌ Ошибка при получении платежей пользователя: {e}")
        return []


# Инициализация БД при импорте
if __name__ == "__main__":
    init_db()
    print("База данных готова к работе!")
else:
    init_db()