import random, re, time
from urllib.parse import unquote, urljoin, urlsplit
import requests
from bs4 import BeautifulSoup
TARGET_HOST = "https://app.khaddavi.net"
USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
def get_xsrf(session, domain):
    for cookie in session.cookies:
        if cookie.name == "XSRF-TOKEN" and domain in cookie.domain:
            return unquote(cookie.value)
    return ""
def extract_destination(html):
    m = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', html)
    if m: return m.group(1).replace("\\/", "/")
    m = re.search(r'https://safefileku\.com/download/[A-Za-z0-9]+', html)
    if m: return m.group(0)
    return None
def resolve(slug):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9", "Connection": "keep-alive"})
    # SKIP GET sfl.gl, langsung ke redirect.php - hemat 0.8s
    landed = session.get(f"{TARGET_HOST}/redirect.php?alias={slug}", timeout=10, allow_redirects=True, stream=True)
    landed.close()
    referer = landed.url
    if "khaddavi" not in referer:
        # Fallback kalo langsung gagal, baru cara lama
        page = session.get(f"https://sfl.gl/{slug}", timeout=10)
        soup = BeautifulSoup(page.text, "html.parser")
        form = soup.find("form")
        if form:
            action = urljoin(page.url, form.get("action") or page.url)
            form_data = {f.get("name"): f.get("value", "") for f in form.find_all("input") if f.get("name")}
            landed = session.get(action, params=form_data, timeout=10, allow_redirects=True, stream=True)
            landed.close()
            referer = landed.url
        page.close()
    xsrf = get_xsrf(session, "khaddavi")
    if not xsrf:
        raise ValueError("no XSRF-TOKEN for app.khaddavi.net")
    api_headers = {"Content-Type": "application/json", "X-XSRF-TOKEN": xsrf, "Origin": TARGET_HOST, "Referer": referer, "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"}
    # SKIP verify, langsung go - hemat 0.8s lagi
    key = random.randint(0, 999)
    size = f"{3840 + key * 2}.{2160 + key * 2}"
    go_response = session.post(f"{TARGET_HOST}/api/go", headers=api_headers, json={"key": key, "size": size}, timeout=10)
    go = go_response.json()
    go_response.close()
    go_url = go.get("url")
    if not go_url:
        # Kalo go gagal karena belum verify, baru verify + retry 1x
        v = session.post(f"{TARGET_HOST}/api/verify", headers=api_headers, json={"_a": 0, "captcha": "", "passcode": ""}, timeout=10, stream=True)
        v.close()
        go_response = session.post(f"{TARGET_HOST}/api/go", headers=api_headers, json={"key": key, "size": size}, timeout=10)
        go = go_response.json()
        go_response.close()
        go_url = go.get("url")
    if not go_url:
        raise ValueError(f"no url in /api/go: {go}")
    if "safefileku.com/download/" in go_url:
        return go_url
    ready = session.get(go_url, timeout=10, allow_redirects=False)
    if ready.status_code in (301,302,303,307,308) and ready.headers.get("Location"):
        loc = ready.headers["Location"]
        ready.close()
        return loc
    final = extract_destination(ready.text[:20000])
    ready.close()
    return final or go_url
