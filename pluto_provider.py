import requests
import json
import uuid
import os
import glob
from datetime import datetime
from typing import List, Dict, Any

class BaseProvider:
    def __init__(self, name):
        self.name = name
    def get_user_agent(self):
        # Using Chrome 133 to ensure the server treats this as a high-end desktop client
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    def get_timeout(self):
        return 30

class PlutoProvider(BaseProvider):
    """Provider for Pluto TV with HD Resolution Fixes and Regional Sorting"""

    def __init__(self):
        super().__init__("pluto")
        self.device_id = str(uuid.uuid1())
        self.session_token = None
        self.stitcher_params = ""
        self.session_expires_at = 0
        
        # Configuration from environment
        self.region = os.getenv('PLUTO_REGION', 'us_west')
        self.username = os.getenv('PLUTO_USERNAME', '').strip() or None
        self.password = os.getenv('PLUTO_PASSWORD', '').strip() or None
        
        # Regional IPs for Geo-Spoofing
        self.x_forward = {
            "local": "",
            "uk": "178.238.11.6",
            "ca": "192.206.151.131", 
            "fr": "193.169.64.141",
            "us_east": "108.82.206.181",
            "us_west": "76.81.9.69",
        }
        
        self.headers = {
            'authority': 'boot.pluto.tv',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
            'user-agent': self.get_user_agent(),
        }
        
        if self.region in self.x_forward and self.x_forward[self.region]:
            self.headers["X-Forwarded-For"] = self.x_forward[self.region]

    def _get_session_token(self) -> str:
        """Authenticates with Pluto and retrieves stitcher parameters for HD streams"""
        if self.session_token and datetime.now().timestamp() < self.session_expires_at:
            return self.session_token
        try:
            url = 'https://boot.pluto.tv/v4/start'
            params = {
                'appName': 'web',
                'appVersion': '8.1.0',
                'deviceVersion': '133.0.0',
                'deviceModel': 'web',
                'deviceMake': 'chrome',
                'deviceType': 'web',
                'clientID': self.device_id,
                'clientModelNumber': '1.0.0',
                'serverSideAds': 'false',
                'architecture': 'x86_64',
                'buildVersion': '1.0.0',
                'drmCapabilities': 'widevine:L3'
            }
            if self.username and self.password:
                params['username'] = self.username
                params['password'] = self.password
            
            response = requests.get(url, headers=self.headers, params=params, timeout=self.get_timeout())
            data = response.json()
            self.session_token = data.get('sessionToken', '')
            self.stitcher_params = data.get('stitcherParams', '')
            self.session_expires_at = datetime.now().timestamp() + (4 * 3600)
            return self.session_token
        except Exception:
            return ""

    def get_channels(self) -> List[Dict[str, Any]]:
        """Fetches channel list and builds high-resolution stream URLs"""
        try:
            token = self._get_session_token()
            if not token: return []
            
            url = "https://service-channels.clusters.pluto.tv/v2/guide/channels"
            headers = self.headers.copy()
            headers['authorization'] = f'Bearer {token}'
            params = {'channelIds': '', 'offset': '0', 'limit': '1000', 'sort': 'number:asc'}
            
            response = requests.get(url, params=params, headers=headers, timeout=self.get_timeout())
            channel_data = response.json().get("data", [])
            categories_list = self._get_categories(headers, params)
            
            processed_channels = []
            for channel in channel_data:
                channel_id = channel.get('id')
                name = channel.get('name')
                if not channel_id or not name: continue
                
                logo = ""
                images = channel.get('images', [])
                for image in images:
                    # Logic fixed to prevent SyntaxError
                    if image.get('type') == 'colorLogoPNG':
                        logo = image.get('url', '')
                        break
                
                group = categories_list.get(channel_id, 'General')
                sid = str(uuid.uuid4())
                
                # HD RESOLUTION PARAMETERS
                # quality=720p and includeExtendedEvents=true are required for max bitrate
                quality_suffix = (f"&quality=720p&deviceMake=chrome&deviceType=web&deviceModel=web"
                                  f"&deviceVersion=133.0.0&architecture=x86_64&buildVersion=1.0.0"
                                  f"&includeExtendedEvents=true&masterJWTPassthrough=true")

                if self.stitcher_params:
                    stream_url = (f"https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/v2/stitch/hls/channel/{channel_id}/master.m3u8"
                                  f"?{self.stitcher_params}&jwt={token}{quality_suffix}")
                else:
                    stream_url = (f"https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/stitch/hls/channel/{channel_id}/master.m3u8"
                                  f"?appName=web&appVersion=8.1.0&sid={sid}&serverSideAds=true{quality_suffix}")
                
                processed_channels.append({
                    'id': str(channel_id),
                    'name': name,
                    'stream_url': stream_url,
                    'logo': logo,
                    'group': group,
                    'region': self.region.upper()
                })
            return processed_channels
        except Exception:
            return []

    def _get_categories(self, headers: dict, params: dict) -> dict:
        try:
            url = "https://service-channels.clusters.pluto.tv/v2/guide/categories"
            response = requests.get(url, params=params, headers=headers, timeout=self.get_timeout())
            data = response.json().get("data", [])
            return {cid: elem.get('name', 'General') for elem in data for cid in elem.get('channelIDs', [])}
        except Exception:
            return {}

    def generate_m3u(self, channels, epg_url):
        m3u = f'#EXTM3U x-tvg-url="{epg_url}"\n'
        for ch in channels:
            m3u += f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-logo="{ch["logo"]}" group-title="{ch["group"]}",{ch["name"]}\n'
            m3u += f'{ch["stream_url"]}\n'
        return m3u

def merge_master_playlist(epg_url):
    """Combines all regional M3U files into a master playlist sorted by region"""
    files = sorted(glob.glob("pluto_*.m3u"))
    files = [f for f in files if "master" not in f]
    
    master_content = f'#EXTM3U x-tvg-url="{epg_url}"\n'
    for file in sorted(files):
        region_label = file.replace("pluto_", "").replace(".m3u", "").upper()
        with open(file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith("#EXTINF"):
                    # Prefix region to group and channel name for easier sorting in players
                    line = line.replace('group-title="', f'group-title="[{region_label}] ')
                    line = line.replace(',', f',[{region_label}] ')
                    master_content += line
                elif not line.startswith("#EXTM3U") and line.strip():
                    master_content += line
                    
    with open("pluto_master.m3u", "w", encoding="utf-8") as f:
        f.write(master_content)

if __name__ == "__main__":
    provider = PlutoProvider()
    channels = provider.get_channels()
    epg_url = "https://github.com/matthuisman/i.mjh.nz/raw/refs/heads/master/PlutoTV/all.xml.gz"
    
    # Save the individual regional file
    m3u_content = provider.generate_m3u(channels, epg_url)
    with open(f"pluto_{provider.region}.m3u", "w", encoding="utf-8") as f:
        f.write(m3u_content)
    
    # Update the combined master playlist
    merge_master_playlist(epg_url)
