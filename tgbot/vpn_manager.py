import requests
import json
import uuid
import time
import random
import string
import urllib.parse
from datetime import datetime
from config import PANEL_HOST, PANEL_USERNAME, PANEL_PASSWORD, INBOUND_ID


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
            return response.json().get('success', False)
        except:
            return False

    def fetch_inbound_config(self):
        """Получение конфигурации инбаунда для генерации ссылок"""
        list_url = f"{self.base_url}/xui/inbound/list"

        try:
            response = self.session.post(list_url)
            result = response.json()

            if result.get('success'):
                for inbound in result.get('obj', []):
                    if inbound.get('id') == INBOUND_ID:
                        # Парсим settings и streamSettings
                        settings = json.loads(inbound.get('settings', '{}'))
                        stream_settings = json.loads(inbound.get('streamSettings', '{}'))

                        reality_settings = stream_settings.get('realitySettings', {})
                        grpc_settings = stream_settings.get('grpcSettings', {})

                        # Извлекаем shortId (первый из списка, может быть пустым)
                        short_ids = reality_settings.get('shortIds', [])
                        short_id = short_ids[0] if short_ids else ''

                        # Получаем sni из serverNames или dest
                        server_names = reality_settings.get('serverNames', [])
                        sni = server_names[0] if server_names else ''
                        dest = reality_settings.get('dest', '')
                        if dest and ':' in dest:
                            sni = dest.split(':')[0]

                        # Получаем остальные параметры Reality
                        spider_x = reality_settings.get('settings', {}).get('spiderX', '/')
                        public_key = reality_settings.get('settings', {}).get('publicKey', '')
                        fingerprint = reality_settings.get('settings', {}).get('fingerprint', 'chrome')

                        # Параметры gRPC
                        service_name = grpc_settings.get('serviceName', '')
                        authority = grpc_settings.get('authority', '')

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
                            'service_name': service_name,
                            'authority': authority,
                            'encryption': encryption,
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
            list_url = f"{self.base_url}/xui/inbound/list"
            response = self.session.post(list_url)
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
            list_url = f"{self.base_url}/xui/inbound/list"
            response = self.session.post(list_url)
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
            return {}

    def create_client(self, days=0, email_prefix="user"):
        """Создание нового клиента"""
        client_uuid = str(uuid.uuid4())
        client_email = f"{email_prefix}_{client_uuid[:8]}"
        sub_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

        # Установка срока действия
        expiry_time = 0
        if days > 0:
            expiry_time = int(time.time() * 1000) + (days * 24 * 60 * 60 * 1000)

        add_url = f"{self.base_url}/xui/inbound/addClient"

        client_data = {
            "id": INBOUND_ID,
            "settings": json.dumps({
                "clients": [{
                    "id": client_uuid,
                    "flow": "",
                    "email": client_email,
                    "totalGB": 0,
                    "expiryTime": expiry_time,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
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
            return {'success': False, 'error': str(e)}

    def generate_vpn_link(self, client_uuid, client_email):
        """Генерация ссылки для подключения в правильном формате"""
        config = self.inbound_config

        if not config:
            self.fetch_inbound_config()
            config = self.inbound_config

        # Кодируем spider_x (в вашем примере spx=%2F)
        spx_encoded = urllib.parse.quote(config['spider_x'], safe='')

        # Формируем параметры в ТОЧНОМ порядке как в ваших ссылках
        params = [
            f"type={config['network']}",
            f"encryption={config['encryption']}",
            f"serviceName={config['service_name']}",
            f"authority={config['authority']}",
            f"security={config['security']}",
            f"pbk={config['public_key']}",
            f"fp={config['fingerprint']}",
            f"sni={config['sni']}",
            f"sid={config['short_id']}",
            f"spx={spx_encoded}"
        ]

        # Собираем query-строку
        query = "&".join(params)

        # Формируем полную ссылку
        link = f"vless://{client_uuid}@{config['server_ip']}:{config['port']}?{query}#{config['remark']}-{client_email}"

        return link

    def update_client(self, client_uuid, client_email, sub_id, new_expiry_time):
        """Обновление клиента (продление подписки)"""
        update_url = f"{self.base_url}/xui/inbound/updateClient/{client_uuid}"

        update_data = {
            "id": INBOUND_ID,
            "settings": json.dumps({
                "clients": [{
                    "id": client_uuid,
                    "flow": "",
                    "email": client_email,
                    "totalGB": 0,
                    "expiryTime": new_expiry_time,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "reset": 0
                }]
            })
        }

        try:
            response = self.session.post(update_url, data=update_data)
            result = response.json()
            return result.get('success', False)
        except:
            return False

    def delete_client(self, client_uuid):
        """Удаление клиента"""
        delete_url = f"{self.base_url}/xui/inbound/{INBOUND_ID}/delClient/{client_uuid}"

        try:
            response = self.session.post(delete_url)
            result = response.json()
            return result.get('success', False)
        except:
            return False

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