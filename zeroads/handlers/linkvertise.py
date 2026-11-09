import ssl
import requests
import re
from requests.adapters import HTTPAdapter
from ..errors import DownloadFailure

MALZ_URL = "https://malz-official.com/slf/"
RE_RESULT = re.compile(r'<div[^>]*id="resultUrl"[^>]*>(.*?)</div>', re.DOTALL)
RE_ERROR = re.compile(r'class="error"[^>]*>(.*?)</div>', re.DOTALL)

# Bikin adapter khusus biar maksa pakai TLS 1.2
class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

def to_canonical(url: str) -> str:
    aliases = ["link-target.net", "link-center.net", "link-hub.net", "direct-link.net"]
    for alias in aliases:
        if f"://{alias}/" in url or f"://www.{alias}/" in url:
            return url.replace(alias, "linkvertise.com")
    return url

def resolve(url: str):
    canonical_url = to_canonical(url)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        # Pake UA Windows Chrome biar mirip browser asli
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": MALZ_URL
    }
    
    session = requests.Session()
    session.mount('https://', TLSAdapter())

    try:
        r = session.post(MALZ_URL, data={"url": canonical_url}, headers=headers, timeout=60)
        r.raise_for_status()
        
        err_match = RE_ERROR.search(r.text)
        if err_match:
            return None
            
        res_match = RE_RESULT.search(r.text)
        if res_match:
            return res_match.group(1).strip()
            
        return None
    except requests.RequestException:
        return None

def process(url):
    final_url = resolve(url)
    if final_url:
        raise DownloadFailure("Link asli ditemukan.", manual_url=final_url)
    else:
        raise DownloadFailure("Gagal memproses Linkvertise via Malz.", manual_url=None)
