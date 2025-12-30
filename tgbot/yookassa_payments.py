import uuid
import hashlib
import hmac
import json
import logging
from datetime import datetime
import aiohttp
from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_API_KEY

logger = logging.getLogger(__name__)


class YooKassaPayment:
    def __init__(self):
        self.shop_id = YOOKASSA_SHOP_ID
        self.secret_key = YOOKASSA_SECRET_KEY
        self.api_key = YOOKASSA_API_KEY
        self.base_url = "https://api.yookassa.ru/v3"  # Для продакшена

        # Заголовки для запросов
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Basic {self._get_auth_token()}',
            'Idempotence-Key': ''  # Будем генерировать для каждого запроса
        }

    def _get_auth_token(self):
        """Генерация токена для Basic Auth"""
        import base64
        auth_string = f"{self.shop_id}:{self.api_key}"
        return base64.b64encode(auth_string.encode()).decode()

    def generate_idempotence_key(self):
        """Генерация уникального ключа идемпотентности"""
        return str(uuid.uuid4())

    async def create_payment(self, amount, description, return_url, metadata=None):
        """
        Создание платежа в ЮKassa
        amount: сумма в рублях (например, 299.00)
        description: описание платежа
        return_url: URL для возврата после оплаты
        metadata: дополнительные данные (user_id, days и т.д.)
        """
        try:
            # Конвертируем рубли в копейки (ЮKassa работает с копейками)
            amount_cents = int(float(amount) * 100)

            # Подготовка данных
            payment_data = {
                "amount": {
                    "value": f"{amount_cents / 100:.2f}",  # В рублях с копейками
                    "currency": "RUB"
                },
                "payment_method_data": {
                    "type": "bank_card"  # Можно добавить другие методы
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url
                },
                "description": description,
                "capture": True,  # Автоматическое списание
                "metadata": metadata or {}
            }

            # Уникальный ключ для идемпотентности
            idempotence_key = self.generate_idempotence_key()
            self.headers['Idempotence-Key'] = idempotence_key

            async with aiohttp.ClientSession() as session:
                async with session.post(
                        f"{self.base_url}/payments",
                        headers=self.headers,
                        json=payment_data
                ) as response:

                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Платеж создан: {result.get('id')}")
                        return {
                            'success': True,
                            'payment_id': result.get('id'),
                            'confirmation_url': result.get('confirmation', {}).get('confirmation_url'),
                            'status': result.get('status'),
                            'amount': result.get('amount'),
                            'metadata': result.get('metadata', {})
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка создания платежа: {response.status} - {error_text}")
                        return {
                            'success': False,
                            'error': f"HTTP {response.status}",
                            'details': error_text
                        }

        except Exception as e:
            logger.error(f"Исключение при создании платежа: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def get_payment_status(self, payment_id):
        """Получение статуса платежа"""
        try:
            idempotence_key = self.generate_idempotence_key()
            self.headers['Idempotence-Key'] = idempotence_key

            async with aiohttp.ClientSession() as session:
                async with session.get(
                        f"{self.base_url}/payments/{payment_id}",
                        headers=self.headers
                ) as response:

                    if response.status == 200:
                        result = await response.json()
                        return {
                            'success': True,
                            'payment_id': result.get('id'),
                            'status': result.get('status'),
                            'paid': result.get('paid'),
                            'amount': result.get('amount'),
                            'metadata': result.get('metadata', {})
                        }
                    else:
                        error_text = await response.text()
                        return {
                            'success': False,
                            'error': f"HTTP {response.status}",
                            'details': error_text
                        }

        except Exception as e:
            logger.error(f"Исключение при проверке платежа: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def verify_webhook_signature(self, body, signature):
        """
        Проверка подписи вебхука от ЮKassa
        body: сырое тело запроса (bytes)
        signature: заголовок "Content-SHA256"
        """
        try:
            # Вычисляем SHA-256 хеш от тела запроса
            hash_object = hashlib.sha256(body)
            computed_hash = hash_object.hexdigest()

            # Создаем HMAC-SHA256 подпись
            secret_key_bytes = self.secret_key.encode('utf-8')
            computed_signature = hmac.new(
                secret_key_bytes,
                computed_hash.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            # Сравниваем подписи
            return hmac.compare_digest(computed_signature, signature)

        except Exception as e:
            logger.error(f"Ошибка при проверке подписи: {e}")
            return False


# Создаем глобальный экземпляр
yookassa = YooKassaPayment()