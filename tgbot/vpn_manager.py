import requests
import json
import uuid
import time
import random
import string
import urllib.parse
from datetime import datetime
from config import PANEL_HOST, PANEL_USERNAME, PANEL_PASSWORD, INBOUND_ID, SUBSCRIPTION_BASE_URL, SUBSCRIPTION_PATH


class VPNManager:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = PANEL_HOST
        self.inbound_config = {}
        self.login()
        self.fetch_inbound_config()

    def login(self):
        """Авторизация в панели 3x-ui"""
        login_url = f"{self.base_url}/login"
        login_data = {"username": PANEL_USERNAME, "password": PANEL_PASSWORD}

        try:
            response = self.session.post(login_url, data=login_data)
            print('login success')
            return response.json().get('success', False)
        except Exception as e:
            print('Authentication failed')
            print(e)
            return False

    def fetch_inbound_config(self):
        """Получение конфигурации инбаунда для генерации ссылок"""
        list_url = f"{self.base_url}/panel/api/inbounds/list"

        try:
            response = self.session.get(list_url)
            print(response)
            result = response.json()

            if result.get('success'):
                for inbound in result.get('obj', []):
                    if inbound.get('id') == INBOUND_ID:
                        # Парсим settings и streamSettings
                        settings = json.loads(inbound.get('settings', '{}'))
                        stream_settings = json.loads(inbound.get('streamSettings', '{}'))

                        reality_settings = stream_settings.get('realitySettings', {})

                        # Извлекаем shortId (первый непустой из списка)
                        short_ids = reality_settings.get('shortIds', [])
                        short_id = ''
                        for sid in short_ids:
                            if sid and sid.strip():
                                short_id = sid.strip()
                                break

                        # Получаем sni из serverNames или target (новое поле вместо dest)
                        server_names = reality_settings.get('serverNames', [])
                        sni = server_names[0] if server_names else ''
                        target = reality_settings.get('target', '')
                        if target and ':' in target:
                            sni = target.split(':')[0]

                        # Получаем остальные параметры Reality
                        spider_x = reality_settings.get('settings', {}).get('spiderX', '/')
                        public_key = reality_settings.get('settings', {}).get('publicKey', '')
                        fingerprint = reality_settings.get('settings', {}).get('fingerprint', 'chrome')

                        # Получаем flow из настроек клиента
                        flow = ""
                        clients = settings.get('clients', [])
                        if clients:
                            # Берем flow первого клиента
                            first_client = clients[0]
                            flow = first_client.get('flow', '')

                        # Базовые параметры
                        encryption = settings.get('encryption', 'none')
                        network = stream_settings.get('network', '')
                        security = stream_settings.get('security', '')

                        # Сохраняем конфигурацию
                        self.inbound_config = {
                            'port': inbound.get('port', 0),
                            'protocol': inbound.get('protocol', ''),
                            'network': network,
                            'security': security,
                            'sni': sni,
                            'fingerprint': fingerprint,
                            'public_key': public_key,
                            'short_id': short_id,
                            'spider_x': spider_x,
                            'service_name': '',  # Для TCP пустое
                            'authority': '',  # Для TCP пустое
                            'encryption': encryption,
                            'flow': flow,  # Добавляем flow
                            'remark': inbound.get('remark', ''),
                            'server_ip': PANEL_HOST.split('://')[1].split(':')[0]
                        }
                        return True
        except Exception as e:
            print(f"Ошибка при получении конфигурации инбаунда: {e}")

        return False

    def get_client_traffic(self, client_email):
        """Получение трафика клиента в MB"""
        try:
            list_url = f"{self.base_url}/panel/api/inbounds/list"
            response = self.session.get(list_url)
            result = response.json()

            if result.get('success'):
                for inbound in result.get('obj', []):
                    if inbound.get('id') == INBOUND_ID:
                        client_stats = inbound.get('clientStats', [])
                        for client in client_stats:
                            if client.get('email') == client_email:
                                # Трафик в байтах, конвертируем в GB для удобства
                                up_bytes = client.get('up', 0)
                                down_bytes = client.get('down', 0)
                                total_bytes = up_bytes + down_bytes

                                # Преобразуем в GB с округлением до 2 знаков
                                total_gb = total_bytes / (1024 ** 3)
                                return round(total_gb, 2)
        except Exception as e:
            print(f"Ошибка при получении трафика клиента {client_email}: {e}")

        return 0

    def get_all_clients_traffic(self):
        """Получение трафика всех клиентов в инбаунде"""
        try:
            list_url = f"{self.base_url}/panel/api/inbounds/list"
            response = self.session.get(list_url)
            result = response.json()

            traffic_dict = {}
            if result.get('success'):
                for inbound in result.get('obj', []):
                    if inbound.get('id') == INBOUND_ID:
                        client_stats = inbound.get('clientStats', [])
                        for client in client_stats:
                            email = client.get('email')
                            up_bytes = client.get('up', 0)
                            down_bytes = client.get('down', 0)
                            total_bytes = up_bytes + down_bytes

                            # Преобразуем в GB
                            total_gb = total_bytes / (1024 ** 3)
                            traffic_dict[email] = round(total_gb, 2)
                        break
            return traffic_dict
        except Exception as e:
            print(f"Ошибка при получении трафика всех клиентов: {e}")
            try:
                print(datetime.now().time().strftime("%H:%M:%S"), 'Ошибка в vpn_manager при получении трафика всех клиентов')
                print('Адрес запроса', list_url)
                print('Ответ 3x-ui на запрос:', response)
            except Exception as e:
                print('При попытке просмотра переменной ``response`` возникла ошибка', e)
            return {}

    def create_client(self, days=0, email_prefix="user"):
        """Создание нового клиента"""
        client_uuid = str(uuid.uuid4())
        # Генерируем короткий email (как в новой панели)
        client_email = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

        # Установка срока действия
        expiry_time = 0
        if days > 0:
            expiry_time = int(time.time() * 1000) + (days * 24 * 60 * 60 * 1000)

        add_url = f"{self.base_url}/panel/api/inbounds/addClient"

        # Новая структура для клиента (на основе вашего примера)
        client_data = {
            "id": INBOUND_ID,
            "settings": json.dumps({
                "clients": [{
                    "id": client_uuid,
                    "flow": "xtls-rprx-vision",
                    "email": client_email,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": expiry_time,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "comment": "",
                    "reset": 0
                }]
            })
        }

        try:
            response = self.session.post(add_url, data=client_data)
            result = response.json()

            if result.get('success'):
                return {
                    'success': True,
                    'email': client_email,
                    'uuid': client_uuid,
                    'sub_id': sub_id,
                    'expiry_time': expiry_time
                }
            return {'success': False, 'error': result.get('msg')}
        except Exception as e:
            print(datetime.now().time().strftime("%H:%M:%S"), 'Ошибка в vpn_manager при создании клиента')
            print('Ответ 3x-ui на запрос:', response)
            return {'success': False, 'error': str(e)}

    def generate_subscription_link(self, sub_id):
        """Генерация ссылки на подписку (новая панель)"""
        return f"{SUBSCRIPTION_BASE_URL}{SUBSCRIPTION_PATH}/{sub_id}"

    def generate_vpn_link(self, client_uuid, client_email):
        """Генерация vless ссылки для подключения"""
        config = self.inbound_config

        if not config:
            self.fetch_inbound_config()
            config = self.inbound_config

        # Кодируем spider_x
        spx_encoded = urllib.parse.quote(config['spider_x'], safe='')

        # Формируем параметры как в новой панели
        params = [
            f"type={config['network']}",
            f"encryption={config['encryption']}",
            f"security={config['security']}",
            f"pbk={config['public_key']}",
            f"fp={config['fingerprint']}",
            f"sni={config['sni']}",
            f"sid={config['short_id']}",
            f"spx={spx_encoded}",
            f"flow={config.get('flow', '')}"
        ]

        # Удаляем пустые параметры
        params = [p for p in params if p.split('=')[1]]

        # Собираем query-строку
        query = "&".join(params)

        # Формируем полную ссылку
        link = f"vless://{client_uuid}@{config['server_ip']}:{config['port']}?{query}#{config['remark']}-{client_email}"

        return link

    def update_client(self, client_uuid, client_email, sub_id, new_expiry_time):
        """Обновление клиента (продление подписки)"""
        flow_value = self.inbound_config.get('flow', 'xtls-rprx-vision')
        update_url = f"{self.base_url}/panel/api/inbounds/updateClient/{client_uuid}"

        update_data = {
            "id": INBOUND_ID,
            "settings": json.dumps({
                "clients": [{
                    "id": client_uuid,
                    "flow": flow_value,
                    "email": client_email,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": new_expiry_time,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "comment": "",
                    "reset": 0
                }]
            })
        }

        try:
            response = self.session.post(update_url, data=update_data)
            result = response.json()
            return result.get('success', False)
        except Exception as e:
            print(f"Ошибка при обновлении клиента: {e}")
            return False

    def delete_client(self, client_uuid):
        """Удаление клиента"""
        delete_url = f"{self.base_url}/panel/api/inbounds/{INBOUND_ID}/delClient/{client_uuid}"

        try:
            response = self.session.post(delete_url)
            result = response.json()
            return result.get('success', False)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def timestamp_to_date(self, timestamp_ms):
        """Конвертация timestamp в читаемую дату"""
        if timestamp_ms == 0:
            return "Бессрочно"
        return datetime.fromtimestamp(timestamp_ms / 1000).strftime('%d.%m.%Y %H:%M')

    def get_days_left(self, timestamp_ms):
        """Получение количества оставшихся дней"""
        if timestamp_ms == 0:
            return "∞"
        now_ms = int(time.time() * 1000)
        if timestamp_ms <= now_ms:
            return 0
        remaining_ms = timestamp_ms - now_ms
        return int(remaining_ms / (24 * 60 * 60 * 1000))

    def client_exists(self, client_email):
        """Проверяет, существует ли клиент в панели 3x-ui"""
        try:
            traffic_data = self.get_all_clients_traffic()
            return client_email in traffic_data
        except Exception as e:
            print(f"Ошибка при проверке существования клиента {client_email}: {e}")
            return False

    def get_client_info(self, client_email):
        """Получает полную информацию о клиенте из панели"""
        try:
            list_url = f"{self.base_url}/panel/api/inbounds/list"
            response = self.session.get(list_url)
            result = response.json()

            if result.get('success'):
                for inbound in result.get('obj', []):
                    if inbound.get('id') == INBOUND_ID:
                        settings = json.loads(inbound.get('settings', '{}'))
                        client_stats = inbound.get('clientStats', [])

                        # Ищем клиента по email в clientStats
                        for client in client_stats:
                            if client.get('email') == client_email:
                                # Ищем в settings для получения полных данных
                                settings_clients = settings.get('clients', [])
                                for settings_client in settings_clients:
                                    if settings_client.get('email') == client_email:
                                        return {
                                            'stats': client,
                                            'settings': settings_client,
                                            'exists': True,
                                            'sub_id': settings_client.get('subId', '')
                                        }
        except Exception as e:
            print(f"Ошибка при получении информации о клиенте {client_email}: {e}")

        return {'exists': False}


    def delete_all_clients_from_panel(self):
        """Удаление всех клиентов из панели 3x-ui"""
        try:
            list_url = f"{self.base_url}/panel/api/inbounds/list"
            response = self.session.get(list_url)
            result = response.json()

            if not result.get('success'):
                return {'success': False, 'error': 'Не удалось получить список клиентов'}

            deleted_count = 0
            errors = []

            for inbound in result.get('obj', []):
                if inbound.get('id') == INBOUND_ID:
                    # Получаем всех клиентов
                    settings = json.loads(inbound.get('settings', '{}'))
                    clients = settings.get('clients', [])

                    for client in clients:
                        client_uuid = client.get('id')
                        if client_uuid:
                            try:
                                # Удаляем клиента
                                success = self.delete_client(client_uuid)
                                if success:
                                    deleted_count += 1
                                    print(f"✅ Удален клиент: {client.get('email', 'unknown')}")
                                else:
                                    errors.append(f"Не удалось удалить клиента {client_uuid}")
                            except Exception as e:
                                errors.append(f"Ошибка при удалении клиента {client_uuid}: {str(e)}")

                    break  # Нашли нужный inbound, выходим

            return {
                'success': True,
                'deleted_count': deleted_count,
                'errors': errors,
                'error_count': len(errors)
            }

        except Exception as e:
            print(f"❌ Ошибка при удалении всех клиентов из панели: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_all_clients_from_panel(self):
        """Получение списка всех клиентов из панели"""
        try:
            list_url = f"{self.base_url}/panel/api/inbounds/list"
            response = self.session.get(list_url)
            result = response.json()

            clients_list = []

            if result.get('success'):
                for inbound in result.get('obj', []):
                    if inbound.get('id') == INBOUND_ID:
                        settings = json.loads(inbound.get('settings', '{}'))
                        clients = settings.get('clients', [])

                        for client in clients:
                            clients_list.append({
                                'email': client.get('email'),
                                'uuid': client.get('id'),
                                'flow': client.get('flow', ''),
                                'expiryTime': client.get('expiryTime', 0),
                                'enable': client.get('enable', True)
                            })
                        break

            return {
                'success': True,
                'clients': clients_list,
                'count': len(clients_list)
            }

        except Exception as e:
            print(f"❌ Ошибка при получении клиентов из панели: {e}")
            return {
                'success': False,
                'error': str(e)
            }

if __name__ == "__main__":
    vm = VPNManager()
    print(vm.inbound_config)