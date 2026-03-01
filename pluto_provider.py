import requests
import json
import uuid
import os
from datetime import datetime
from typing import List, Dict, Any

# Mocking BaseProvider for standalone execution
class BaseProvider:
    def __init__(self, name):
        self.name = name
    def get_user_agent(self):
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    def get_timeout(self):
        return 30
    def validate_channel(self, channel):
        return True
    def normalize_channel(self, channel):
        return channel

class PlutoProvider(BaseProvider):
    """Provider for Pluto TV channels"""

    def __init__(self):
        super().__init__("pluto")
        
        self.device_id = str(uuid.uuid1()) [cite: 1]
        self.session_token = None [cite: 1]
        self.stitcher_params = "" [cite: 1]
        self.session_expires_at = 0 [cite: 1]
        
        self.username = os.getenv('PLUTO_USERNAME') [cite: 1]
        self.password = os.getenv('PLUTO_PASSWORD') [cite: 1]
        self.region = os.getenv('PLUTO_REGION', 'us_west') [cite: 2]
        
        self.x_forward = {
            "local": "",
            "uk": "178.238.11.6",
            "ca": "192.206.151.131", 
            "fr": "193.169.64.141",
            "us_east": "108.82.206.181",
            "us_west": "76.81.9.69",
        } [cite: 2]
        
        self.headers = {
            'authority': 'boot.pluto.tv',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
            'user-agent': self.get_user_agent(),
        } [cite: 3]
        
        if self.region in self.x_forward:
            forwarded_ip = self.x_forward[self.region]
            if forwarded_ip:
                self.headers["X-Forwarded-For"] = forwarded_ip [cite: 3]

    def _get_session_token(self) -> str:
        if self.session_token and datetime.now().timestamp() < self.session_expires_at:
            return self.session_token [cite: 4]
        
        try:
            url = 'https://boot.pluto.tv/v4/start' [cite: 4]
            params = {
                'appName': 'web',
                'appVersion': '8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6',
                'deviceVersion': '122.0.0',
                'deviceModel': 'web',
                'deviceMake': 'chrome',
                'deviceType': 'web',
                'clientID': self.device_id,
                'clientModelNumber': '1.0.0',
                'serverSideAds': 'false',
                'drmCapabilities': 'widevine:L3',
                'blockingMode': '',
                'notificationVersion': '1',
                'appLaunchCount': '',
                'lastAppLaunchDate': '',
            } [cite: 4, 5, 6]
            
            if self.username and self.password:
                params['username'] = self.username [cite: 6]
                params['password'] = self.password [cite: 7]
            
            response = requests.get(url, headers=self.headers, params=params, timeout=self.get_timeout()) [cite: 7]
            response.raise_for_status()
            
            data = response.json()
            self.session_token = data.get('sessionToken') [cite: 7]
            self.stitcher_params = data.get('stitcherParams', '') [cite: 7]
            self.session_expires_at = datetime.now().timestamp() + (4 * 3600) [cite: 8]
            
            return self.session_token [cite: 9]
        except Exception:
            return ""

    def get_channels(self) -> List[Dict[str, Any]]:
        try:
            token = self._get_session_token() [cite: 9]
            if not token: return [] [cite: 10]
            
            url = "https://service-channels.clusters.pluto.tv/v2/guide/channels" [cite: 10]
            headers = self.headers.copy()
            headers['authorization'] = f'Bearer {token}' [cite: 11]
            
            params = {'channelIds': '', 'offset': '0', 'limit': '1000', 'sort': 'number:asc'} [cite: 12, 13]
            response = requests.get(url, params=params, headers=headers, timeout=self.get_timeout()) [cite: 13]
            response.raise_for_status()
            
            channel_data = response.json().get("data", []) [cite: 13]
            categories_list = self._get_categories(headers, params) [cite: 14, 27]
            
            processed_channels = []
            for channel in channel_data:
                channel_id = channel.get('id') [cite: 15]
                name = channel.get('name') [cite: 15]
                if not channel_id or not name: continue [cite: 16]
                
                logo = ""
                for image in channel.get('images', []): [cite: 17]
                    if image.get('type') == 'colorLogoPNG':
                        logo = image.get('url', '') [cite: 17]
                        break
                
                group = categories_list.get(channel_id, 'General') [cite: 18, 28]
                
                if self.stitcher_params: [cite: 19]
                    stream_url = (f"https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/v2/stitch/hls/channel/{channel_id}/master.m3u8"
                                  f"?{self.stitcher_params}&jwt={token}&masterJWTPassthrough=true&includeExtendedEvents=true") [cite: 19, 20]
                else:
                    sid = str(uuid.uuid4()) [cite: 20]
                    stream_url = (f"https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/stitch/hls/channel/{channel_id}/master.m3u8"
                                  f"?advertisingId=&appName=web&appVersion=unknown&deviceId={self.device_id}&deviceMake=Chrome&deviceModel=web"
                                  f"&deviceType=web&sid={sid}&serverSideAds=true") [cite: 21, 22]
                
                processed_channels.append({
                    'id': str(channel_id), [cite: 23]
                    'name': name, [cite: 23]
                    'stream_url': stream_url, [cite: 23]
                    'logo': logo, [cite: 23]
                    'group': group [cite: 24]
                })
            return processed_channels
        except Exception:
            return []

    def _get_categories(self, headers: dict, params: dict) -> dict:
        try:
            category_url = "https://service-channels.clusters.pluto.tv/v2/guide/categories" [cite: 27]
            response = requests.get(category_url, params=params, headers=headers, timeout=self.get_timeout()) [cite: 27]
            categories_data = response.json().get("data", []) [cite: 27]
            categories_list = {}
            for elem in categories_data:
                category = elem.get('name', 'General') [cite: 28]
                for cid in elem.get('channelIDs', []): [cite: 28]
                    categories_list[cid] = category
            return categories_list
        except Exception:
            return {}

    def generate_m3u(self, channels, epg_url):
        m3u = f'#EXTM3U x-tvg-url="{epg_url}"\n'
        for ch in channels:
            m3u += f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-logo="{ch["logo"]}" group-title="{ch["group"]}",{ch["name"]}\n'
            m3u += f'{ch["stream_url"]}\n'
        return m3u

if __name__ == "__main__":
    provider = PlutoProvider()
    channels = provider.get_channels()
    epg_url = "https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master/PlutoTV/all.xml.gz"
    
    playlist = provider.generate_m3u(channels, epg_url)
    
    with open(f"pluto_{provider.region}.m3u", "w") as f:
        f.write(playlist)
