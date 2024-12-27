# uisp_utils.py (محدث)

import logging
import requests
from datetime import datetime
import math

class UispMonitor:
    def __init__(self, api_url, api_token):
        self.api_url = api_url
        self.headers = {
            'x-auth-token': api_token
        }

    def get_device_details(self, device_id):
        try:
            response = requests.get(f"{self.api_url}/devices/{device_id}/detail", headers=self.headers)
            if response.status_code == 200:
                logging.debug(f"Device details for {device_id}: {response.json()}")
                return response.json()
            else:
                logging.error(f"Failed to fetch device details for ID {device_id}: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logging.error(f"Error fetching device details for ID {device_id}: {str(e)}")
            return None

    def get_device_ip(self, device):
        device_details = self.get_device_details(device['identification']['id'])
        if device_details:
            ip_address = device_details.get('ipAddress', None)
            ip_address_list = device_details.get('ipAddressList', [])
            if ip_address:
                logging.debug(f"IP Address for device {device['identification']['name']}: {ip_address}")
                return ip_address
            elif ip_address_list:
                ip_from_list = ip_address_list[0]
                logging.debug(f"IP Address from list for device {device['identification']['name']}: {ip_from_list}")
                return ip_from_list
        return "غير متوفر"

    def get_cable_status(self, device):
        device_details = self.get_device_details(device['identification']['id'])
        if device_details:
            interfaces = device_details.get('interfaces', [])
            for interface in interfaces:
                interface_name = interface['identification']['name'].lower()
                if "eth0" in interface_name or "lan" in interface_name or "data" in interface_name:
                    speed = interface.get('status', {}).get('speed', None)
                    plugged = interface.get('status', {}).get('plugged', False)

                    if not plugged:
                        return "unplugged"
                    elif speed == '10-full':
                        return "10mp"
                    elif speed == '100-full':
                        return "100mp"
                    elif speed == '1000-full':
                        return "1000mp"
        return "غير متوفر"

    def get_signal_strength(self, device):
        device_details = self.get_device_details(device['identification']['id'])
        if not device_details:
            return "غير متوفر"

        overview_signal = device_details.get('overview', {}).get('signal')
        if overview_signal is not None:
            return overview_signal

        interfaces = device_details.get('interfaces', [])
        for iface in interfaces:
            wireless_data = iface.get('wireless')
            if wireless_data and isinstance(wireless_data.get('stations'), list):
                for station in wireless_data['stations']:
                    rx_sig = station.get('rxSignal')
                    tx_sig = station.get('txSignal')
                    rx_chain = station.get('rxChain')
                    tx_chain = station.get('txChain')

                    if rx_sig is not None and tx_sig is not None:
                        val = (rx_sig + tx_sig) / 2
                        return round(val, 1)
                    if rx_sig is not None:
                        return rx_sig
                    if tx_sig is not None:
                        return tx_sig
                    if rx_chain and len(rx_chain) > 0 and tx_chain and len(tx_chain) > 0:
                        avg_rx_chain = sum(rx_chain) / len(rx_chain)
                        avg_tx_chain = sum(tx_chain) / len(tx_chain)
                        val = (avg_rx_chain + avg_tx_chain) / 2
                        return round(val, 1)
                    if rx_chain and len(rx_chain) > 0:
                        avg_rx_chain = sum(rx_chain) / len(rx_chain)
                        return round(avg_rx_chain, 1)
                    if tx_chain and len(tx_chain) > 0:
                        avg_tx_chain = sum(tx_chain) / len(tx_chain)
                        return round(avg_tx_chain, 1)
        return "غير متوفر"

    def get_connection_duration(self, device):
        started = device.get('overview', {}).get('serviceUptime')
        if started:
            minutes, seconds = divmod(started, 60)
            hours, minutes = divmod(minutes, 60)
            days, hours = divmod(hours, 24)

            if days > 0:
                return f"{days} يوم" if days == 1 else f"{days} أيام"
            elif hours > 0:
                return f"{hours} ساعة" if hours == 1 else f"{hours} ساعات"
            elif minutes > 0:
                return f"{minutes} دقيقة" if minutes == 1 else f"{minutes} دقائق"
            else:
                return "أقل من دقيقة"
        return "غير متوفر"

    def get_disconnection_duration(self, device):
        last_seen = device.get('overview', {}).get('lastSeen')
        if last_seen:
            last_seen_time = datetime.fromisoformat(last_seen[:-1])
            duration = datetime.utcnow() - last_seen_time
            days = duration.days
            seconds = duration.seconds
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60

            if days > 0:
                return f"{days} يوم" if days == 1 else f"{days} أيام"
            elif hours > 0:
                return f"{hours} ساعة" if hours == 1 else f"{hours} ساعات"
            elif minutes > 0:
                return f"{minutes} دقيقة" if minutes == 1 else f"{minutes} دقائق"
            else:
                return "أقل من دقيقة"
        return "غير متوفر"

    def get_frequency(self, device):
        device_details = self.get_device_details(device['identification']['id'])
        if not device_details:
            return None

        overview_freq = device_details.get('overview', {}).get('frequency')
        if overview_freq:
            return float(overview_freq)

        airmax_freq = device_details.get('airmax', {}).get('frequency')
        if airmax_freq:
            return float(airmax_freq)

        attributes_freq = device_details.get('attributes', {}).get('frequency')
        if attributes_freq:
            return float(attributes_freq)

        return None

    def remove_device(self, device_id):
        try:
            response = requests.delete(f"{self.api_url}/devices/{device_id}", headers=self.headers)
            return response.status_code == 204
        except Exception as e:
            logging.error(f"Error removing device {device_id}: {str(e)}")
            return False

    def reconnect_device(self, device_id):
        try:
            response = requests.post(f"{self.api_url}/devices/{device_id}/reconnect", headers=self.headers)
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Error reconnecting device {device_id}: {str(e)}")
            return False
