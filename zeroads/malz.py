import requests
import re

MALZ_URL = "https://malz-official.com/slf/"
RE_RESULT = re.compile(r'<div[^>]*id="resultUrl"[^>]*>(.*?)</div>', re.DOTALL)
RE_ERROR = re.compile(r'class="error"[^>]*>(.*?)</div>', re.DOTALL)

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
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
        "Referer": MALZ_URL
    }
    
    try:
        r = requests.post(MALZ_URL, data={"url": canonical_url}, headers=headers, timeout=60)
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
