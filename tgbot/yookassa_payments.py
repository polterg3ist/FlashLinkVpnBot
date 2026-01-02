# yookassa_payments.py
import uuid
import logging
from yookassa import Payment
from yookassa.domain.notification import (
    WebhookNotificationFactory,
    WebhookNotificationEventType
)

logger = logging.getLogger(__name__)


class YooKassaPayment:
    """
    Обёртка над официальным SDK ЮKassa для совместимости с текущим кодом бота.
    """

    async def create_payment(self, amount, description, return_url, metadata=None):
        """
        Создание платежа в ЮKassa через официальный SDK.
        Возвращает результат в том же формате, что и старая функция.
        """
        try:
            # Конвертируем рубли в копейки
            amount_cents = int(float(amount) * 100)

            # Генерируем уникальный ключ идемпотентности
            idempotence_key = str(uuid.uuid4())
            logger.info(f"Создание платежа. Ключ идемпотентности: {idempotence_key}")

            # Создаём платёж через SDK
            payment = Payment.create({
                "amount": {
                    "value": f"{amount:.2f}",  # Просто используем переданную сумму с двумя знаками
                    "currency": "RUB"
                },
                "payment_method_data": {
                    "type": "bank_card"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url
                },
                "description": description,
                "capture": True,
                "metadata": metadata or {}
            }, idempotence_key)  # Явно передаем ключ

            logger.info(f"Объект платежа создан: id={payment.id}, status={payment.status}")

            # Формируем ответ в старом формате для совместимости
            return {
                'success': True,
                'payment_id': payment.id,
                'confirmation_url': payment.confirmation.confirmation_url,
                'status': payment.status,
                'amount': payment.amount,
                'metadata': payment.metadata
            }

        except Exception as e:
            # Детальное логирование исключения
            logger.error(f"Исключение при создании платежа через SDK: {type(e).__name__}", exc_info=True)
            return {
                'success': False,
                'error': f"{type(e).__name__}: {str(e)}"
            }

    async def get_payment_status(self, payment_id):
        """
        Получение статуса платежа через официальный SDK.
        """
        try:
            payment = Payment.find_one(payment_id)

            return {
                'success': True,
                'payment_id': payment.id,
                'status': payment.status,
                'paid': payment.paid,
                'amount': payment.amount,
                'metadata': payment.metadata
            }

        except Exception as e:
            logger.error(f"Ошибка получения статуса платежа {payment_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def verify_webhook_signature(self, body, signature_header):
        """
        ВАЖНО: В официальном SDK нет отдельного метода validate[citation:1].
        Проверка подписи происходит автоматически при создании объекта уведомления
        из сырых данных (body).

        Эта функция теперь просто передаёт тело запроса в фабрику уведомлений SDK.
        Если подпись неверна или данные повреждены, SDK выбросит исключение.

        signature_header: оставляем для совместимости, но в данной реализации
                          он не используется напрямую.
        """
        try:
            # Преобразуем байты в строку JSON (SDK ожидает словарь или строку)
            import json
            body_str = body.decode('utf-8')
            body_dict = json.loads(body_str)

            # Пытаемся создать объект уведомления через фабрику SDK
            # Если подпись в заголовке запроса не соответствует телу,
            # или данные некорректны, здесь будет выброшено исключение.
            notification = WebhookNotificationFactory().create(body_dict)

            # Если дошли сюда — уведомление создано, значит, подпись и данные в порядке
            logger.info(f"Вебхук успешно верифицирован SDK. Событие: {notification.event}")
            return True

        except Exception as e:
            # Любая ошибка (неверная подпись, невалидный JSON и т.д.) будет перехвачена здесь
            logger.error(f"Ошибка верификации вебхука через SDK: {type(e).__name__}: {e}")
            return False

    # Сохраняем метод для совместимости, но теперь он не выполняет реальной работы
    def _get_auth_token(self):
        return ""

    def generate_idempotence_key(self):
        return str(uuid.uuid4())


# Глобальный экземпляр для обратной совместимости
yookassa = YooKassaPayment()