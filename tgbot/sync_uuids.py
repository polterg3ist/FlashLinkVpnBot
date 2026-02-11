#!/usr/bin/env python3
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import get_all_users, update_user_client
from vpn_manager import VPNManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def sync_uuids():
    vpn = VPNManager()

    # 1. Получаем всех клиентов из панели
    panel_result = vpn.get_all_clients_from_panel()
    if not panel_result['success']:
        logger.error("Не удалось получить клиентов из панели")
        return

    panel_clients = panel_result['clients']
    logger.info(f"В панели найдено клиентов: {len(panel_clients)}")

    # 2. Строим словарь email -> данные из панели
    panel_dict = {}
    for client in panel_clients:
        email = client['email']
        panel_dict[email] = {
            'uuid': client['uuid'],
            'sub_id': client.get('subId', ''),
            'expiry_time': client.get('expiryTime', 0),
            'enable': client.get('enable', True)
        }

    # 3. Получаем всех пользователей из БД
    db_users = get_all_users()
    logger.info(f"В БД пользователей: {len(db_users)}")

    updated = 0
    not_found = 0
    errors = 0

    for user in db_users:
        db_email = user['client_email']
        db_uuid = user['client_uuid']

        if db_email in panel_dict:
            panel_info = panel_dict[db_email]
            panel_uuid = panel_info['uuid']

            if db_uuid != panel_uuid:
                # Несоответствие – обновляем
                logger.info(f"Обновление UUID для {db_email}: {db_uuid} -> {panel_uuid}")
                success = update_user_client(
                    telegram_id=user['telegram_id'],
                    new_client_email=db_email,
                    new_client_uuid=panel_uuid,
                    new_sub_id=panel_info['sub_id']
                )
                if success:
                    updated += 1
                else:
                    errors += 1
        else:
            logger.warning(f"Пользователь {db_email} не найден в панели")
            not_found += 1

    logger.info(f"Синхронизация завершена. Обновлено: {updated}, не найдено: {not_found}, ошибок: {errors}")


if __name__ == "__main__":
    sync_uuids()