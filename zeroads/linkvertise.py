import urllib.parse
import requests

def resolve(url):
    """Fungsi bypass Linkvertise menggunakan REST API."""
    parsed = urllib.parse.urlparse(url)
    path = [p for p in parsed.path.strip("/").split("/") if p]
    
    # Linkvertise selalu butuh UID dan PID
    if len(path) < 2:
        return None
        
    uid, pid = path[0], path[1]
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/json",
        "Origin": "https://linkvertise.com",
        "Referer": "https://linkvertise.com/"
    })
    
    # Endpoint REST API terbaru (static redirect)
    api_url = f"https://publisher.linkvertise.com/api/v1/redirect/link/static/{uid}/{pid}"
    
    try:
        r = session.get(api_url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("data"):
                # Link target biasanya ada di dalam 'target' atau 'url'
                return data["data"].get("target") or data["data"].get("url")
    except Exception:
        pass
        
    # Jika gagal, coba endpoint alternatif
    api_url_alt = f"https://publisher.linkvertise.com/api/v1/redirect/link/{uid}/{pid}"
    try:
        r = session.get(api_url_alt, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("data"):
                return data["data"].get("target") or data["data"].get("url")
    except Exception:
        pass

    return None
