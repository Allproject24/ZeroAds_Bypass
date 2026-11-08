import random
import re
import time
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

TARGET_HOST = "https://app.khaddavi.net"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
)


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
    print(" ".join(fields), flush=True)


def get_xsrf(session, domain):
    for cookie in session.cookies:
        if cookie.name == "XSRF-TOKEN" and domain in cookie.domain:
            return unquote(cookie.value)
    return ""


def extract_destination(html):
    match = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', html)
    if match:
        return match.group(1).replace("\\/", "/")
    match = re.search(r'http-equiv=["\']refresh["\'][^>]+url=([^"\'>\s]+)', html, re.I)
    if match:
        return match.group(1)
    if "safefileku.com/download/" in html:
        match = re.search(r'https://safefileku\.com/download/[A-Za-z0-9]+', html)
        if match:
            return match.group(0)
    return None


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
        page = session.get(f"https://sfl.gl/{slug}", timeout=30)
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
                    f"{TARGET_HOST}/redirect.php?alias={slug}&ray_id={match.group(1)}",
                    timeout=30,
                    allow_redirects=True,
                    stream=True,
                )
            else:
                landed = session.get(
                    f"{TARGET_HOST}/redirect.php?alias={slug}",
                    timeout=30,
                    allow_redirects=True,
                    stream=True,
                )
        else:
            action = urljoin(page.url, form.get("action") or page.url)
            form_data = {
                field.get("name"): field.get("value", "")
                for field in form.find_all("input")
                if field.get("name")
            }
            landed = session.get(
                action,
                params=form_data,
                timeout=30,
                allow_redirects=True,
                stream=True,
            )
        landed.close()
        referer = landed.url
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
            f"{TARGET_HOST}/api/verify",
            headers=api_headers,
            json={"_a": 0, "captcha": "", "passcode": ""},
            timeout=30,
            stream=True,
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
                f"{TARGET_HOST}/api/go",
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
            ready = session.get(go_url, timeout=30, allow_redirects=True)
            ready_text = ready.text
            ready.close()
        except Exception as error:
            _log_timing(
                "destination_page",
                ready_started,
                host=urlsplit(go_url).hostname or "unknown",
                error=error,
                attempt=attempt,
            )
            raise
        _log_timing("destination_page", ready_started, response=ready, attempt=attempt)

        final = extract_destination(ready_text)
        if final and "safefileku.com/download/" in final:
            return final
        api_headers["Referer"] = ready.url

    raise ValueError("destination not found after 3 tries")
