import random
import re
import time
from urllib.parse import unquote, urljoin, urlsplit, quote

import requests
from bs4 import BeautifulSoup

TARGET_HOST = "https://app.khaddavi.net"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
)
WORKER_URL = "https://sfl-proxy.allstorevpn.workers.dev"

def proxify(url):
    """Bungkus URL agar lewat Cloudflare Worker"""
    return f"{WORKER_URL}?url={quote(url, safe='')}"

def _log_timing(stage, started, response=None, host=None, error=None, attempt=None):
    response_url = getattr(response, "url", "") if response is not None else ""
    host = urlsplit(response_url).hostname or host or "unknown"
    status = getattr(response, "status_code", "error" if error else "unknown")
    fields = [
        "TIMING",
        f"stage={stage}",
        f"host={host}",
        f"status={status}",
        f"elapsed_ms={(time.perf_counter() - started) * 1000:.1f}",
    ]
    if attempt is not None:
        fields.append(f"attempt={attempt}")
    if error:
        fields.append(f"error={type(error).__name__}")
    try:
        print(" ".join(fields), flush=True)
    except Exception:
        pass

def get_xsrf(session, domain):
    for cookie in session.cookies:
        if cookie.name == "XSRF-TOKEN":
            return unquote(cookie.value)
    return ""

TARGET_RE = re.compile(r"https://safefileku\.com/download/[A-Za-z0-9_-]+")

def is_target(url):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if not (
        parts.scheme == "https"
        and host == "safefileku.com"
        and (port is None or port == 443)
        and parts.path.startswith("/download/")
    ):
        return False
    rest = parts.path[len("/download/"):].rstrip("/")
    return bool(rest) and all(c.isalnum() or c in "_-" for c in rest)

def extract_destination(html, base=""):
    candidates = []
    for match in re.finditer(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', html):
        candidates.append(match.group(1).replace("\\/", "/"))
    for match in re.finditer(r'http-equiv=["\']refresh["\'][^>]+url=([^"\'>\s]+)', html, re.I):
        candidates.append(match.group(1))
    for candidate in candidates:
        candidate = urljoin(base, candidate) if base else candidate
        if is_target(candidate):
            return candidate
    match = TARGET_RE.search(html.replace("\\/", "/"))
    if match:
        return match.group(0)
    return candidates[0] if candidates else None

def open_destination(session, url, max_hops=8):
    for _ in range(max_hops):
        if is_target(url):
            return url, None, ""
        
        response = session.get(proxify(url), timeout=30, allow_redirects=False)
        
        real_url = response.headers.get("X-Real-Url", url)
        real_redirect = response.headers.get("X-Real-Redirect")
        
        if real_redirect:
            response.close()
            url = real_redirect
            continue
            
        text = response.text
        response.close()
        return real_url, response, text
        
    response = session.get(proxify(url), timeout=30, allow_redirects=True)
    text = response.text
    response.close()
    return url, response, text

def _log_retry(attempt, reason, final=None):
    fields = ["TIMING", "stage=resolver_retry", f"attempt={attempt}", f"reason={reason}"]
    try:
        host = urlsplit(final).hostname if final else None
        if host:
            fields.append(f"final_host={host}")
        print(" ".join(fields), flush=True)
    except Exception:
        pass

def resolve(slug):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    page_started = time.perf_counter()
    try:
        page = session.get(proxify(f"https://sfl.gl/{slug}"), timeout=30)
        page_text = page.text
        page.close()
    except Exception as error:
        _log_timing("sfl_page", page_started, host="sfl.gl", error=error)
        raise
    _log_timing("sfl_page", page_started, response=page)

    soup = BeautifulSoup(page_text, "html.parser")
    form = soup.find("form")

    landing_started = time.perf_counter()
    try:
        if not form:
            match = re.search(r'ray_id["\']?\s*value=["\']([^"\']+)', page_text)
            if match:
                landed = session.get(
                    proxify(f"{TARGET_HOST}/redirect.php?alias={slug}&ray_id={match.group(1)}"),
                    timeout=30,
                    allow_redirects=True,
                )
            else:
                landed = session.get(
                    proxify(f"{TARGET_HOST}/redirect.php?alias={slug}"),
                    timeout=30,
                    allow_redirects=True,
                )
        else:
            action = urljoin(page.url, form.get("action") or page.url)
            form_data = {
                field.get("name"): field.get("value", "")
                for field in form.find_all("input")
                if field.get("name")
            }
            landed = session.get(
                proxify(action),
                params=form_data,
                timeout=30,
                allow_redirects=True,
            )
        landed.close()
        referer = landed.headers.get("X-Real-Url", landed.url)
    except Exception as error:
        _log_timing("landing", landing_started, host="app.khaddavi.net", error=error)
        raise
    _log_timing("landing", landing_started, response=landed)

    if "khaddavi" not in referer:
        raise ValueError(f"did not land on {TARGET_HOST}, got {referer}")

    xsrf = get_xsrf(session, "khaddavi")
    if not xsrf:
        raise ValueError("no XSRF-TOKEN for app.khaddavi.net")

    api_headers = {
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": xsrf,
        "Origin": TARGET_HOST,
        "Referer": referer,
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
    }

    verification_started = time.perf_counter()
    try:
        verification = session.post(
            proxify(f"{TARGET_HOST}/api/verify"),
            headers=api_headers,
            json={"_a": 0, "captcha": "", "passcode": ""},
            timeout=30,
        )
        verification.close()
    except Exception as error:
        _log_timing("verify", verification_started, host="app.khaddavi.net", error=error)
        raise
    _log_timing("verify", verification_started, response=verification)

    for attempt in range(1, 4):
        key = random.randint(0, 999)
        size = f"{3840 + key * 2}.{2160 + key * 2}"
        go_started = time.perf_counter()
        try:
            go_response = session.post(
                proxify(f"{TARGET_HOST}/api/go"),
                headers=api_headers,
                json={"key": key, "size": size},
                timeout=30,
            )
            go = go_response.json()
            go_response.close()
        except Exception as error:
            _log_timing(
                "api_go",
                go_started,
                host="app.khaddavi.net",
                error=error,
                attempt=attempt,
            )
            raise
        _log_timing("api_go", go_started, response=go_response, attempt=attempt)

        go_url = go.get("url")
        if not go_url:
            raise ValueError(f"no url in /api/go response: {go}")

        ready_started = time.perf_counter()
        try:
            ready_url, ready, ready_text = open_destination(session, go_url)
        except Exception as error:
            _log_timing(
                "destination_page",
                ready_started,
                host=urlsplit(go_url).hostname or "unknown",
                error=error,
                attempt=attempt,
            )
            raise
        _log_timing(
            "destination_page",
            ready_started,
            response=ready,
            host=urlsplit(ready_url).hostname or "unknown",
            attempt=attempt,
        )

        if is_target(ready_url):
            return ready_url
        final = extract_destination(ready_text, ready_url)
        if final and is_target(final):
            return final
        _log_retry(attempt, "not_safefileku" if final else "no_target", final)
        api_headers["Referer"] = ready_url

    raise ValueError("destination not found after 3 tries")
