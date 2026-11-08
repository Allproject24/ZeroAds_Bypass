#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sfile_dl.py - downloader untuk sfile.co / sfile.mobi / safefileku, termasuk link pendek sfl.gl.
Tanpa dependensi (hanya pustaka standar Python 3), jalan di Termux.

Contoh:
  python sfile_dl.py https://sfile.co/xxxxxxxx
  python sfile_dl.py https://sfl.gl/xxxxxxx
  python sfile_dl.py LINK1 LINK2 -o ~/storage/downloads
  python sfile_dl.py -f daftar.txt        # satu link per baris
  python sfile_dl.py LINK --link          # cari link akhirnya saja, tanpa mengunduh
  python sfile_dl.py LINK --debug         # tampilkan kandidat link + simpan HTML tiap langkah

Cara kerja: buka halaman seperti browser (cookie + referer), cari tombol/link unduhan,
ikuti rantai halaman sampai server mengirim berkas, lalu simpan dengan progress dan
dukungan lanjut (resume).

Link pendek (sfl.gl dkk) melewati halaman perantara: blog partner, form tersembunyi,
hitung mundur, link yang disandikan base64. Skrip menembusnya sampai tiba di
safefileku/sfile, lalu lanjut seperti biasa.

Kalau gagal, bahan debug otomatis dikemas ke debug_sfile_TANGGAL-JAM.zip (namanya selalu
beda tiap kali) - tinggal kirim zip itu.
"""
import argparse
import base64
import gzip
import html
import http.client
import http.cookiejar
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
MAX_PAGE = 3 * 1024 * 1024   # batas baca halaman HTML
MAX_DEPTH = 4                # maks. langkah dari halaman awal (link langsung ke host file)
MAX_REQUESTS = 14            # maks. permintaan per link (jangan membanjiri server)
GW_MAX_DEPTH = 9             # link pendek / halaman perantara butuh langkah lebih banyak
GW_MAX_REQUESTS = 32
MIN_SCORE = 40               # skor minimal sebuah kandidat link
TOP_PER_PAGE = 3             # kandidat yang dicoba per halaman
GW_TOP_PER_PAGE = 4
MAX_GUESSES = 3              # maks. URL tebakan (tanpa petunjuk) per link
GW_MAX_GUESSES = 4
MAX_WAIT_TOTAL = 90          # total detik menunggu hitung mundur per link
KEEP_HTML = 300_000          # batas isi halaman yang disimpan ke debug
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
DEBUG_DIR = os.path.join(SCRIPT_DIR, "debug_sfile")

# host tujuan akhir (halaman file) dan host link pendek
FILE_HOSTS = ("safefileku.com", "sfile.co", "sfile.mobi")
SHORT_HOSTS = ("sfl.gl", "safelinku.com")

FILE_EXT = (".zip", ".rar", ".7z", ".tar", ".gz", ".apk", ".xapk", ".apks", ".obb",
            ".hc", ".ehi", ".dark", ".nm", ".sks", ".inpv", ".ovpn", ".conf",
            ".mp3", ".mp4", ".mkv", ".pdf", ".exe", ".iso")
HTML_TYPES = ("text/html", "application/xhtml+xml")
PAGE_TYPES = ("text/html", "application/xhtml+xml", "application/json",
              "text/json", "text/javascript", "application/javascript")
BAD_DOMAINS = ("facebook.com", "fb.com", "twitter.com", "x.com", "t.me",
               "telegram.me", "telegram.org", "wa.me", "whatsapp.com",
               "instagram.com", "youtube.com", "youtu.be", "tiktok.com",
               "pinterest.com", "linkedin.com", "google.com", "apple.com",
               "doubleclick.net", "googlesyndication.com", "googleadservices.com",
               "adsterra.com", "popads.net", "propellerads.com", "histats.com",
               "disqus.com", "cloudflareinsights.com", "cloudflare.com",
               "googletagmanager.com", "google-analytics.com", "googleapis.com",
               "gstatic.com", "jsdelivr.net", "unpkg.com", "bootstrapcdn.com",
               "fontawesome.com", "jquery.com")
BAD_PATH = re.compile(
    r"/(login|register|signup|report|dmca|contact|privacy|terms|about|upload|search|faq|tos|sitemap)(/|$)",
    re.I)
# halaman sampah bawaan WordPress (kategori, tag, oEmbed, feed, dst) - tidak pernah berisi link unduhan
JUNK_PATH = re.compile(
    r"/(wp-json|wp-admin|wp-content|wp-includes|wp-login\.php|xmlrpc\.php|feed|comments|"
    r"trackback|category|tag|author|embed|amp|page/\d+)(/|$)", re.I)
JUNK_QUERY = re.compile(r"[?&](s|replytocom|share|print|format)=", re.I)

STATIC_RE = re.compile(r"\.(js|css|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|map|xml)(/|$)", re.I)

# kata petunjuk "tombol lanjut" di halaman perantara
CONT_TEXT = re.compile(
    r"get\s*-?link|dapatkan|lanjut|continue|proceed|\bnext\b|\bskip\b|go\s*to|buka\s*link|lihat\s*link|"
    r"klik\s*(?:di\s*sini|disini|untuk)|click\s*(?:here|to)|verif|unlock|download|unduh|tautan|\bgo\b", re.I)
CONT_ID = re.compile(
    r"get-?link|continue|next|skip|go-?link|lanjut|unlock|download|redirect|"
    r"btn-?(?:go|get|main|next)|tp-?snp|final|target", re.I)
CONT_URL = re.compile(
    r"/(?:go|out|redirect|link|safe|continue|next|step|verify|unlock|get|dl|file)(?:/|$|\.php|\?)|"
    r"(?:redirect|go|out|link|get)\.php|"
    r"[?&](?:go|url|link|token|key|code|to|target|dest|redirect|next|continue|sid|hash|u|r|k)=", re.I)
FORM_SKIP = re.compile(
    r"^(?:s|q|search|query|keyword|keywords|comment|author|email|pass|password|pwd|log|user|"
    r"username|name|message|subject|phone)$", re.I)
CAPTCHA_RE = re.compile(
    r"cf-turnstile|challenges\.cloudflare\.com|g-recaptcha|h-captcha|hcaptcha\.com|"
    r"recaptcha/(?:api|enterprise)|Just a moment\.\.\.|cf-browser-verification|"
    r"challenge-platform|__CF\$cv\$params|name=[\"']ray_id[\"']", re.I)

JS_NAV = re.compile(
    r"""(?:location(?:\.href|\.replace|\.assign)?\s*(?:=|\()|\.href\s*=)\s*["']([^"'\s<>]+)["']""", re.I)
JS_OPEN = re.compile(r"""window\.open\s*\(\s*["']([^"'\s<>]+)["']""", re.I)
JS_ABS = re.compile(r"""["'](https?:(?:\\?/){2}[^"'\s<>]+)["']""", re.I)
JS_COOKIE = re.compile(r"""document\.cookie\s*=\s*["']\s*([A-Za-z0-9_.\-]+)=([^"';+]+)""")
B64_RE = re.compile(r"[A-Za-z0-9+/_-]{24,2048}={0,2}")
WAIT_RES = (
    (re.compile(r"data-(?:time|seconds?|wait|countdown|delay|timer)\s*=\s*[\"'](\d{1,3})", re.I), 1),
    (re.compile(r"(?:var|let|const)\s+(?:count\w*|timer\w*|time\w*|sec\w*|wait\w*|delay\w*|left\w*)"
                r"\s*=\s*(\d{1,3})\b", re.I), 1),
    (re.compile(r"(?:tunggu|wait(?:ing)?|please\s+wait|harap\s+tunggu|countdown|timer)\D{0,40}?\b(\d{1,3})\b"
                r"\s*(?:detik|seconds?|secs?|s\b)", re.I), 1),
    (re.compile(r"\b(\d{1,3})\s*(?:detik|seconds?)\b", re.I), 1),
    (re.compile(r"setTimeout\s*\([\s\S]{0,800}?,\s*(\d{3,5})\s*\)", re.I), 1000),
)


def make_goal_re():
    hosts = "|".join(re.escape(h) for h in FILE_HOSTS)
    return re.compile(
        r"https?://(?:[A-Za-z0-9-]+\.)*(?:%s)(?::\d+)?(?:/[^\s\"'<>\\)\]}]*)?" % hosts, re.I)


GOAL_RE = make_goal_re()


def log(msg=""):
    print(msg, flush=True)


def _log_timing(stage, elapsed, host, status, request=None, error=None, **metrics):
    fields = [
        "TIMING",
        f"stage={stage}",
        f"host={host or 'unknown'}",
        f"status={status}",
        f"elapsed_ms={elapsed * 1000:.1f}",
    ]
    if request is not None:
        fields.append(f"request={request}")
    if error:
        fields.append(f"error={error}")
    fields.extend(f"{key}={value}" for key, value in metrics.items())
    try:
        print(" ".join(fields), flush=True)
    except Exception:
        pass  # log tidak boleh menggagalkan permintaan atau menahan kunci unduhan


def short(u, n=88):
    return u if len(u) <= n else u[: n - 1] + "…"


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def host_kind(host):
    """'file' = host tujuan (sfile/safefileku), 'short' = link pendek, 'other' = lainnya."""
    host = (host or "").lower()
    for d in FILE_HOSTS:
        if host == d or host.endswith("." + d):
            return "file"
    for d in SHORT_HOSTS:
        if host == d or host.endswith("." + d):
            return "short"
    return "other"


def site_of(host):
    parts = (host or "").split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else (host or "")


# ----------------------------------------------------------------- HTTP

class RedirectLog(urllib.request.HTTPRedirectHandler):
    """Catat setiap redirect supaya terlihat di mode --debug."""

    def __init__(self, sink):
        self.sink = sink

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.sink.append(f"{code} {short(req.full_url, 50)} -> {short(newurl, 80)}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, tag="l1", timeout=30, capture_trace=True, timing=False):
        self.cj = http.cookiejar.CookieJar()
        self.redirects = []
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj), RedirectLog(self.redirects))
        self.timeout = timeout
        self.requests = 0
        self.guesses = 0
        self.tag = tag
        self.capture_trace = capture_trace
        self.timing = timing
        self.gateway = False      # True kalau rantai dimulai dari link pendek / halaman perantara
        self.reached = False      # sudah tiba di host file?
        self.goal_page = ""
        self.waited = 0.0
        self.trace = []           # riwayat halaman (untuk debug)
        self.steps = []
        self.notes = []

    def open(self, url, referer=None, data=None, range_start=0):
        self.requests += 1
        host = urllib.parse.urlsplit(url).hostname or ""
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
        }
        site = "none"
        if referer:
            headers["Referer"] = referer
            rh = urllib.parse.urlsplit(referer).hostname or ""
            site = ("same-origin" if rh == host else
                    "same-site" if site_of(rh) == site_of(host) else "cross-site")
        headers["Sec-Fetch-Site"] = site
        if range_start:
            headers["Range"] = f"bytes={range_start}-"
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            p = urllib.parse.urlsplit(referer or url)
            headers["Origin"] = f"{p.scheme}://{p.netloc}"
        req = urllib.request.Request(url, data=data, headers=headers)
        started = time.perf_counter()
        try:
            response = self.opener.open(req, timeout=self.timeout)
        except Exception as error:
            if self.timing:
                _log_timing(
                    "sfile_http",
                    time.perf_counter() - started,
                    host,
                    "error",
                    request=self.requests,
                    error=type(error).__name__,
                )
            raise
        if self.timing:
            _log_timing(
                "sfile_http",
                time.perf_counter() - started,
                host,
                response.getcode(),
                request=self.requests,
            )
        return response

    def cookie_names(self):
        return sorted(f"{c.domain}|{c.name}" for c in self.cj)

    def record(self, url, final, status, headers, text, redirects, data=None):
        self.steps.append(f"{self.requests}. {'POST ' if data else ''}{url}"
                          + (f"  ->  {final}" if final != url else "") + f"  [HTTP {status}]")
        if self.capture_trace:
            self.trace.append({"n": self.requests, "url": url, "final": final, "status": status,
                               "headers": headers, "redirects": redirects, "text": text[:KEEP_HTML],
                               "cookies": self.cookie_names(), "post": bool(data)})

    def fail(self, url, e):
        body = ""
        try:
            body = e.read(4000).decode("utf-8", "replace")
        except Exception:
            pass
        hdrs = list(e.headers.items()) if getattr(e, "headers", None) else []
        self.record(url, url, e.code, hdrs, body, [])
        if e.code in (403, 429, 503):
            self.notes.append(f"HTTP {e.code} di {short(url, 70)} - kemungkinan diblokir (Cloudflare/anti-bot)")


def clean_url(u):
    """Encode karakter ilegal (spasi, non-ASCII) tanpa merusak %-encoding yang sudah ada."""
    p = urllib.parse.urlsplit(u)
    path = urllib.parse.quote(p.path, safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(p.query, safe="=&%:@!$'()*+,;/?-._~")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, query, ""))


def absolutize(href, base):
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return None
    try:
        u = urllib.parse.urldefrag(urllib.parse.urljoin(base, href))[0]
        if urllib.parse.urlsplit(u).scheme not in ("http", "https"):
            return None
        return clean_url(u)
    except ValueError:
        return None


def read_html(resp):
    raw = resp.read(MAX_PAGE)
    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    charset = resp.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def looks_like_file(resp, url=""):
    """Berkas = ada Content-Disposition: attachment, atau tipe biner / ekstensi berkas.
    Halaman web, XML, JSON, teks, dan gambar BUKAN berkas (dulu XML oEmbed ikut tersimpan)."""
    if "attachment" in resp.headers.get("Content-Disposition", "").lower():
        return True
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not ctype or ctype in HTML_TYPES:
        return False
    path = urllib.parse.urlsplit(url or resp.geturl()).path.lower()
    if path.endswith(FILE_EXT):
        return True
    if (ctype.startswith(("text/", "image/")) or "xml" in ctype or "json" in ctype
            or "javascript" in ctype or ctype in PAGE_TYPES):
        return False
    return True


# ------------------------------------------------- bantu: teks, base64, timer

def norm_text(t):
    t = (t.replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "=")
         .replace("\\u002F", "/").replace("\\u002f", "/").replace("\\x2F", "/").replace("\\x3A", ":"))
    return html.unescape(t)


def decode_b64(s):
    """Base64 (biasa/urlsafe) -> teks UTF-8, atau None kalau bukan base64 yang masuk akal."""
    s = (s or "").strip().replace(" ", "+")
    if len(s) < 16 or len(s) > 4096 or not re.fullmatch(r"[A-Za-z0-9+/_\-]+={0,2}", s):
        return None
    t = s.replace("-", "+").replace("_", "/").rstrip("=")
    t += "=" * (-len(t) % 4)
    try:
        d = base64.b64decode(t).decode("utf-8")
    except Exception:
        return None
    if not d or not all(c.isprintable() or c in "\r\n\t" for c in d[:300]):
        return None
    return urllib.parse.unquote(d) if "%" in d else d


def goal_urls(text):
    """Semua URL host-file (safefileku/sfile) yang terselip di halaman: polos, ter-escape JSON,
    ter-encode %, atau disandikan base64."""
    out, seen = [], set()

    def scan(t):
        for m in GOAL_RE.finditer(t):
            u = m.group(0).rstrip(".,;:")
            if len(urllib.parse.urlsplit(u).path) > 1 and u not in seen:
                seen.add(u)
                out.append(u)

    t = norm_text(text)
    scan(t)
    if "%2F" in t or "%2f" in t:
        scan(urllib.parse.unquote(t))
    for i, m in enumerate(B64_RE.finditer(t)):
        if i >= 600:
            break
        d = decode_b64(m.group(0))
        if d:
            if not re.match(r"https?://", d, re.I) and re.match(r"[\w.-]+\.[a-z]{2,}/", d, re.I):
                d = "https://" + d
            scan(norm_text(d))
    return out


def embedded_urls(u):
    """URL tujuan yang terselip di parameter query atau segmen path (mentah atau base64)."""
    p = urllib.parse.urlsplit(u)
    vals = [v for _, v in urllib.parse.parse_qsl(p.query, keep_blank_values=False)]
    vals += [s for s in p.path.split("/") if len(s) >= 16]
    out = []
    for v in vals:
        v = urllib.parse.unquote(v).strip()
        if re.match(r"https?://", v, re.I):
            out.append(v)
        else:
            d = decode_b64(v)
            if d and re.match(r"https?://", d, re.I):
                out.append(d)
    return out


def detect_wait(text):
    """Perkiraan hitung mundur (detik) di halaman perantara; 0 kalau tidak ketemu."""
    best = 0.0
    for rx, div in WAIT_RES:
        for m in rx.finditer(text):
            try:
                v = int(m.group(1)) / div
            except ValueError:
                continue
            if 2 <= v <= 60:
                best = max(best, v)
    return best


def apply_js_cookies(client, text, page_url):
    """Sebagian halaman perantara memasang cookie lewat JavaScript; tiru yang nilainya tertulis jelas."""
    host = urllib.parse.urlsplit(page_url).hostname
    if not host:
        return
    for m in JS_COOKIE.finditer(text):
        name, value = m.group(1), m.group(2).strip()
        if value:
            client.cj.set_cookie(http.cookiejar.Cookie(
                0, name, value, None, False, host, False, False, "/", True, False, None, True,
                None, None, {}))


# ------------------------------------------------------- cari link unduhan

class PageParser(HTMLParser):
    SKIP = ("nav", "header", "footer", "aside")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.forms = [], []
        self.refresh = None
        self._a = None
        self._form = None
        self._skip = 0

    def close_a(self):
        if self._a is not None:
            self.links.append(self._a)
            self._a = None

    def handle_starttag(self, tag, attrs):
        a = {(k or "").lower(): (v or "") for k, v in attrs}
        if tag in self.SKIP:
            self._skip += 1
        for k in ("data-href", "data-url", "data-link", "data-download"):
            if a.get(k):
                self.links.append({"href": a[k], "id": a.get("id", ""), "cls": a.get("class", ""),
                                   "text": "", "nav": self._skip > 0})
        if tag == "a":
            self.close_a()
            self._a = {"href": a.get("href", ""), "id": a.get("id", ""),
                       "cls": a.get("class", ""), "text": "", "nav": self._skip > 0}
        elif tag == "iframe" and a.get("src"):
            self.links.append({"href": a["src"], "id": a.get("id", ""), "cls": "iframe",
                               "text": "", "nav": False})
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            m = re.search(r"url\s*=\s*['\"]?([^'\";]+)", a.get("content", ""), re.I)
            if m:
                self.refresh = m.group(1).strip()
        elif tag == "form":
            self._form = {"action": a.get("action", ""),
                          "method": a.get("method", "get").lower(),
                          "id": a.get("id", ""), "cls": a.get("class", ""), "role": a.get("role", ""),
                          "fields": [], "text": ""}
        elif tag in ("input", "button") and self._form is not None:
            self._form["fields"].append({
                "name": a.get("name", ""), "value": a.get("value", ""),
                "type": a.get("type", "submit" if tag == "button" else "text"),
                "checked": "checked" in a})

    def handle_data(self, data):
        if self._a is not None:
            self._a["text"] += data
        if self._form is not None:
            self._form["text"] += data

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip > 0:
            self._skip -= 1
        if tag == "a":
            self.close_a()
        elif tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None


def js_urls(text):
    """[(url, jenis)] - jenis: 'nav' (location=...), 'open' (window.open), 'abs' (URL bertanda kutip)."""
    out = []
    for rx, kind in ((JS_NAV, "nav"), (JS_OPEN, "open"), (JS_ABS, "abs")):
        for m in rx.finditer(text):
            u = html.unescape(m.group(1).replace("\\/", "/")).strip()
            if u:
                out.append((u, kind))
    return out


def score(url, current, text="", lid="", cls="", gw=False, nav=False):
    """Skor seberapa mirip link ini dengan langkah berikutnya. -1 = buang.
    gw=True: halaman perantara (blog/link pendek). Kata 'download' di slug artikel blog
    TIDAK dihitung - itu yang dulu menyesatkan skrip ke kategori/tag WordPress."""
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    if (any(host == d or host.endswith("." + d) for d in BAD_DOMAINS) or BAD_PATH.search(p.path)
            or JUNK_PATH.search(p.path) or JUNK_QUERY.search("?" + p.query)):
        return -1
    if STATIC_RE.search(p.path) and not p.path.lower().endswith(FILE_EXT):
        return -1
    if url.rstrip("/") == current.rstrip("/"):
        return -1
    lid, cls, low = lid.lower(), cls.lower(), url.lower()
    t = " ".join(text.split()).lower()
    s = 0
    if gw:
        kind = host_kind(host)
        if kind == "file" and len(p.path) > 1:
            s += 300                       # sudah menuju host file: ini tujuannya
        elif kind == "short" and len(p.path) > 1:
            s += 60                        # balik ke link pendek (langkah berikutnya)
        if CONT_ID.search(lid) or CONT_ID.search(cls):
            s += 60
        if CONT_TEXT.search(t):
            s += 50
        if CONT_URL.search(low):
            s += 45
        if p.path.lower().endswith(FILE_EXT):
            s += 60
        if len(t) > 28:
            s -= 50                        # teks panjang = judul artikel, bukan tombol
        if nav:
            s -= 40                        # menu / header / footer / sidebar
        return s
    if lid in ("download", "btn-download", "btndownload", "downloadbutton",
               "download-button", "dl"):
        s += 100
    elif "download" in lid or "download" in cls:
        s += 50
    if re.search(r"download|unduh|\bdl\b|klik di sini|click here|get file", t):
        s += 50
    if re.search(r"download|unduh|/dl/|[?&]dl=", low):
        s += 40
    if p.path.lower().endswith(FILE_EXT):
        s += 60
    if "download" in host:
        s += 30
    return s


def is_junk_form(f):
    meta = f"{f['id']} {f['cls']} {f['role']} {f['action']}".lower()
    if re.search(r"search|comment|login|signin|register|subscribe|newsletter|cari", meta):
        return True
    for x in f["fields"]:
        if x["type"].lower() in ("hidden", "submit", "button", "image", "checkbox", "radio"):
            continue
        if FORM_SKIP.match(x["name"] or ""):
            return True
    return False


def find_candidates(text, page_url, gw=False):
    pp = PageParser()
    try:
        pp.feed(text)
        pp.close()
    except Exception:
        pass
    pp.close_a()

    found = {}

    def add(url, s, why, data=None, fallback=False):
        # fallback = tebakan: URL tanpa petunjuk, hanya dicoba kalau langsung berupa berkas
        if fallback:
            p = urllib.parse.urlsplit(url)
            direct_file = (p.path.lower().endswith(FILE_EXT)
                           or (host_kind(p.hostname) == "file" and len(p.path) > 1))
            if not direct_file:
                return
        if s < MIN_SCORE and not (fallback and s >= 0):
            return
        key = (url, data)
        if key not in found or found[key][0] < s:
            found[key] = (s, why, fallback and s < MIN_SCORE)

    def add_embedded(u, why):
        # URL tujuan yang terselip di parameter (?url=...) atau disandikan base64
        for e in embedded_urls(u):
            eu = absolutize(e, page_url)
            if eu:
                s = score(eu, page_url, gw=gw)
                if s >= 0:
                    add(eu, s + 120, why + " > terselip")

    for l in pp.links:
        u = absolutize(l["href"], page_url)
        if u:
            label = f"a#{l['id']} {' '.join(l['text'].split())[:30]}".strip()
            s = score(u, page_url, l["text"], l["id"], l["cls"], gw, l.get("nav", False))
            add(u, s, label)
            if s >= 0:
                add_embedded(u, label)

    if pp.refresh:
        u = absolutize(pp.refresh, page_url)
        if u:
            s = score(u, page_url, gw=gw)
            add(u, s + 80 if s >= 0 else s, "meta refresh")
            if s >= 0:
                add_embedded(u, "meta refresh")

    for f in pp.forms:
        blob = (f["text"] + " " + " ".join(f"{x['name']}={x['value']}" for x in f["fields"])).lower()
        has_hidden = any(x["type"].lower() == "hidden" and x["value"] for x in f["fields"])
        cont = bool(CONT_TEXT.search(blob))
        if gw:
            if is_junk_form(f) or not (has_hidden or cont):
                continue
        elif not re.search(r"download|unduh", blob):
            continue
        action = absolutize(f["action"] or page_url, page_url)
        if not action:
            continue
        fields, submit_done = {}, False
        for x in f["fields"]:
            n, v, t = x["name"], x["value"], x["type"].lower()
            if not n:
                continue
            if t in ("submit", "button", "image"):
                if not submit_done and (gw or re.search(r"download|unduh", v.lower())):
                    fields[n] = v
                    submit_done = True
                continue
            if t in ("checkbox", "radio") and not x["checked"]:
                continue
            fields[n] = v
        body = urllib.parse.urlencode(fields)
        s = 70 + (20 if gw and has_hidden else 0) + (20 if gw and cont else 0)
        if f["method"] == "post":
            add(action, s, "form POST", body.encode())
        else:
            sep = "&" if "?" in action else "?"
            add(action + (sep + body if body else ""), s, "form GET")

    for raw, kind in js_urls(text):
        u = absolutize(raw, page_url)
        if u:
            static = bool(STATIC_RE.search(urllib.parse.urlsplit(u).path))
            s = score(u, page_url, gw=gw)
            if gw and kind == "nav" and s >= 0 and not static:
                s += 55
            add(u, s, "js", fallback=not static)
            if s >= 0:
                add_embedded(u, "js")

    if gw:
        for g in goal_urls(text):
            gu = absolutize(g, page_url)
            if gu:
                s = score(gu, page_url, gw=True)
                if s >= 0:
                    add(gu, max(s, 300), "tujuan akhir")

    cands = [{"url": k[0], "data": k[1], "score": v[0], "why": v[1], "fallback": v[2]}
             for k, v in found.items()]
    cands.sort(key=lambda c: (c["fallback"], -c["score"]))
    return cands


# ----------------------------------------------------------- debug otomatis

def save_debug(client):
    d = DEBUG_DIR
    os.makedirs(d, exist_ok=True)
    for t in client.trace:
        host = re.sub(r"[^\w.-]", "_", urllib.parse.urlsplit(t["final"]).hostname or "x")
        path = os.path.join(d, f"{client.tag}_langkah{t['n']:02d}_{host}.html")
        head = "\n".join(f"{k}: {v}" for k, v in t["headers"])
        redir = "\n".join(t["redirects"])
        info = (f"{'POST ' if t['post'] else ''}{t['url']}\nakhir: {t['final']}\nHTTP {t['status']}\n"
                f"{head}\n--- redirect ---\n{redir}\n--- cookie ---\n" + "\n".join(t["cookies"]))
        info = info.replace("--", "- -")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"<!--\n{info}\n-->\n{t['text']}")
    with open(os.path.join(d, f"{client.tag}_ringkasan.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(client.steps) + "\n\nCatatan:\n" + ("\n".join(client.notes) or "(tidak ada)") + "\n")


def pack_debug():
    d = DEBUG_DIR
    if not os.path.isdir(d) or not os.listdir(d):
        return None
    base = time.strftime("debug_sfile_%Y%m%d-%H%M%S")
    name, i = os.path.join(SCRIPT_DIR, base + ".zip"), 1
    while os.path.exists(name):          # nama zip tidak pernah sama
        i += 1
        name = os.path.join(SCRIPT_DIR, f"{base}-v{i}.zip")
    with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(d)):
            z.write(os.path.join(d, fn), fn)
    return os.path.abspath(name)


# ------------------------------------------------------------------ resolve

def resolve(client, url, referer, args, seen, depth=0, data=None):
    """Ikuti rantai halaman sampai ketemu respons berkas. Return (resp, referer) atau None."""
    pad = "  " * depth
    max_req = GW_MAX_REQUESTS if client.gateway else MAX_REQUESTS
    max_depth = GW_MAX_DEPTH if client.gateway else MAX_DEPTH
    if client.requests >= max_req:
        log(f"{pad}  batas permintaan tercapai")
        client.notes.append("batas permintaan tercapai (rantai halaman terlalu panjang)")
        return None
    log(f"{pad}→ {short(url)}" + ("  [POST]" if data else ""))
    n_red = len(client.redirects)
    try:
        resp = client.open(url, referer=referer, data=data)
    except urllib.error.HTTPError as e:
        log(f"{pad}  HTTP {e.code} {e.reason}")
        client.fail(url, e)
        return None
    except (OSError, http.client.HTTPException, ValueError) as e:
        log(f"{pad}  gagal: {getattr(e, 'reason', e)}")
        client.steps.append(f"{client.requests}. {url}  [gagal: {getattr(e, 'reason', e)}]")
        return None

    page_url = resp.geturl()
    if page_url.rstrip("/") != url.rstrip("/"):
        log(f"{pad}  ↪ {short(page_url)}")
    if args.debug:
        for r in client.redirects[n_red:]:
            log(f"{pad}  ↪ {r}")
        log(f"{pad}  HTTP {resp.getcode()}  {resp.headers.get('Content-Type', '?')}"
            f"  {resp.headers.get('Content-Length', '?')} byte")
    if looks_like_file(resp, page_url):
        client.steps.append(f"{client.requests}. {url}  ->  BERKAS ({resp.headers.get('Content-Type', '?')})")
        return resp, referer

    body_started = time.perf_counter()
    text = ""
    try:
        text = read_html(resp)
    except (OSError, http.client.HTTPException):
        text = ""
    finally:
        if client.timing:
            _log_timing(
                "sfile_html",
                time.perf_counter() - body_started,
                urllib.parse.urlsplit(page_url).hostname,
                resp.getcode(),
                request=client.requests,
                characters=len(text),
            )
        resp.close()
    seen.add((page_url, None))
    client.record(url, page_url, resp.getcode(), list(resp.headers.items()), text,
                  client.redirects[n_red:], data)
    apply_js_cookies(client, text, page_url)

    kind = host_kind(urllib.parse.urlsplit(page_url).hostname)
    if client.gateway and kind == "file" and not client.reached:
        client.reached = True
        client.goal_page = page_url
        log(f"{pad}  ✓ sampai di halaman file: {short(page_url)}")
    gw = client.gateway and kind != "file"
    if gw and CAPTCHA_RE.search(text):
        note = f"captcha / pemeriksaan Cloudflare terdeteksi di {short(page_url, 70)} (tidak bisa dilewati skrip)"
        if note not in client.notes:
            client.notes.append(note)

    if depth >= max_depth:
        return None

    cands = find_candidates(text, page_url, gw)
    if args.debug:
        for c in cands[:8]:
            tag = "tebakan" if c["fallback"] else f"skor {c['score']}"
            log(f"{pad}  [{tag}] {short(c['url'], 70)}  ({c['why']})")
        if not cands:
            log(f"{pad}  (tidak ada kandidat link unduhan)")

    top = GW_TOP_PER_PAGE if gw else TOP_PER_PAGE
    max_guess = GW_MAX_GUESSES if gw else MAX_GUESSES
    tried = guessed = 0
    first = True
    for c in cands:
        key = (c["url"], c["data"])
        if key in seen:
            continue
        if c["fallback"]:
            guessed += 1
            if guessed > 2 or client.guesses >= max_guess:
                continue
            client.guesses += 1
        else:
            tried += 1
            if tried > top:
                continue
        seen.add(key)
        pause = args.wait if gw else 0.0
        if first and gw:
            w = min(detect_wait(text), args.maxwait, max(0.0, MAX_WAIT_TOTAL - client.waited))
            if w > pause:
                log(f"{pad}  menunggu hitung mundur ±{w:.0f} dtk…")
                client.waited += w
                pause = w
        first = False
        time.sleep(pause)
        found = resolve(client, c["url"], page_url, args, seen, depth + 1, c["data"])
        if found:
            return found
    return None


# ------------------------------------------------------------- unduh berkas

def sanitize(name):
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', "_", name).strip(" .")
    if len(name) > 150:
        base, ext = os.path.splitext(name)
        name = base[: 150 - len(ext)] + ext
    return name


def pick_filename(resp, url):
    disp = resp.headers.get("Content-Disposition", "")
    name = None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", disp, re.I)
    if m:
        try:
            name = urllib.parse.unquote(m.group(2).strip().strip('"'), encoding=m.group(1) or "utf-8")
        except LookupError:
            name = urllib.parse.unquote(m.group(2).strip().strip('"'))
    if not name:
        m = re.search(r'filename\s*=\s*"([^"]+)"', disp, re.I) or \
            re.search(r"filename\s*=\s*([^;]+)", disp, re.I)
        if m:
            name = m.group(1).strip().strip('"')
            try:   # http.client membaca header sebagai latin-1; coba pulihkan UTF-8
                name = name.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    if not name:
        name = urllib.parse.unquote(os.path.basename(urllib.parse.urlsplit(url).path))
    return sanitize(name) or "download.bin"


def total_size(resp):
    m = re.search(r"/(\d+)\s*$", resp.headers.get("Content-Range", ""))
    if m:
        return int(m.group(1))
    cl = resp.headers.get("Content-Length", "")
    return int(cl) if cl.isdigit() else 0


def unique_path(path):
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def stream(resp, part, mode, start, total):
    got, t0, last = start, time.time(), 0.0
    with open(part, mode) as fh:
        while True:
            buf = resp.read(64 * 1024)
            if not buf:
                break
            fh.write(buf)
            got += len(buf)
            now = time.time()
            if now - last > 0.3:
                last = now
                rate = (got - start) / max(now - t0, 0.001)
                if total:
                    line = f"{human(got)} / {human(total)} ({got * 100 // total}%)  {human(rate)}/s"
                else:
                    line = f"{human(got)}  {human(rate)}/s"
                sys.stdout.write("\r  " + line + "      ")
                sys.stdout.flush()
    sys.stdout.write("\n")


def not_a_file(part, dest):
    """Jaring pengaman: isi unduhan ternyata halaman web / XML, bukan berkas."""
    try:
        with open(part, "rb") as fh:
            head = fh.read(600)
    except OSError:
        return None
    h = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    ext = os.path.splitext(dest)[1].lower()
    if h.startswith((b"<!doctype html", b"<html", b"<head", b"<body")) and ext not in (".html", ".htm"):
        return "halaman web (HTML)"
    if h.startswith(b"<?xml") and ext not in FILE_EXT + (".xml", ".svg", ".html", ".htm"):
        return "dokumen XML"
    return None


def download(client, resp, referer, outdir, retries):
    final_url = resp.geturl()
    total = total_size(resp)
    dest = os.path.join(outdir, pick_filename(resp, final_url))
    if os.path.exists(dest):
        if total and os.path.getsize(dest) == total:
            resp.close()
            log(f"  sudah ada: {dest}")
            return dest
        dest = unique_path(dest)
    part = dest + ".part"
    log(f"  file : {os.path.basename(dest)}" + (f"  ({human(total)})" if total else ""))

    cur, tries = resp, 0
    while True:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if total and have > total:
            os.remove(part)
            have = 0
        if total and have == total:
            break
        try:
            if cur is None or have:
                if cur is not None:
                    cur.close()
                cur = client.open(final_url, referer=referer, range_start=have)
            resumed = bool(have) and cur.getcode() == 206
            if resumed:
                log(f"  melanjutkan dari {human(have)}")
            stream(cur, part, "ab" if resumed else "wb", have if resumed else 0, total)
            cur.close()
            cur = None
            if total and os.path.getsize(part) < total:
                raise IOError("koneksi terputus sebelum selesai")
            break
        except (OSError, http.client.HTTPException) as e:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
                cur = None
            if isinstance(e, urllib.error.HTTPError) and e.code == 416:
                if not total:
                    break            # ukuran tak diketahui: anggap sudah lengkap
                if os.path.exists(part):
                    os.remove(part)  # berkas di server berubah: ulang dari awal
            tries += 1
            log(f"  terputus: {getattr(e, 'reason', e)}")
            if tries > retries:
                log(f"  gagal. Jalankan lagi perintah yang sama untuk melanjutkan ({os.path.basename(part)})")
                return None
            time.sleep(2 * tries)

    why = not_a_file(part, dest)
    if why:
        os.remove(part)
        log(f"  dibatalkan: isinya ternyata {why}, bukan berkas unduhan")
        client.notes.append(f"respons terakhir ternyata {why}, bukan berkas")
        return None
    os.replace(part, dest)
    log(f"  selesai: {dest}")
    return dest


# ------------------------------------------------------------------- main

def default_outdir():
    return SCRIPT_DIR


def main():
    ap = argparse.ArgumentParser(description="Downloader sfile.co / sfile.mobi / safefileku (+ link pendek sfl.gl)")
    ap.add_argument("urls", nargs="*", help="link halaman file atau link pendek (sfl.gl)")
    ap.add_argument("-f", "--file", help="berkas teks berisi daftar link (satu per baris)")
    ap.add_argument("-o", "--out", help="folder tujuan (default: folder tempat script ini berada)")
    ap.add_argument("-w", "--wait", type=float, default=2.0, help="jeda (detik) sebelum tiap langkah, default 2")
    ap.add_argument("--maxwait", type=float, default=15.0,
                    help="batas tunggu (detik) untuk satu hitung mundur di halaman perantara, default 15")
    ap.add_argument("-r", "--retries", type=int, default=3, help="percobaan ulang saat koneksi putus, default 3")
    ap.add_argument("--link", action="store_true", help="hanya cari link akhir, jangan mengunduh")
    ap.add_argument("--debug", action="store_true",
                    help="tampilkan kandidat link + simpan HTML tiap langkah, kemas jadi debug_sfile_<waktu>.zip "
                         "(kalau gagal, ini juga otomatis)")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            urls += [l.strip() for l in fh if l.strip() and not l.lstrip().startswith("#")]
    if not urls:
        ap.print_help()
        return 1

    outdir = os.path.expanduser(args.out) if args.out else default_outdir()
    os.makedirs(outdir, exist_ok=True)
    shutil.rmtree(DEBUG_DIR, ignore_errors=True)

    ok = 0
    need_debug = args.debug
    try:
        for i, u in enumerate(urls, 1):
            if not re.match(r"https?://", u, re.I):
                u = "https://" + u
            u = clean_url(u)
            log(f"\n[{i}/{len(urls)}] {u}")
            client = Client(tag=f"l{i}")
            client.gateway = host_kind(urllib.parse.urlsplit(u).hostname) != "file"
            found = resolve(client, u, None, args, {(u, None)})
            if not found:
                log("  link unduhan tidak ditemukan.")
                for n in client.notes:
                    log(f"  catatan: {n}")
                save_debug(client)
                need_debug = True
                continue
            resp, ref = found
            if args.link:
                if client.goal_page:
                    log(f"  halaman file : {client.goal_page}")
                log(f"  link berkas  : {resp.geturl()}")
                resp.close()
                ok += 1
                if args.debug:
                    save_debug(client)
                continue
            if download(client, resp, ref, outdir, args.retries):
                ok += 1
            else:
                save_debug(client)
                need_debug = True
            if args.debug:
                save_debug(client)
    except KeyboardInterrupt:
        log("\nDihentikan. Jalankan lagi perintah yang sama untuk melanjutkan.")
        return 130

    if need_debug:
        z = pack_debug()
        if z:
            log(f"\nBahan debug dikemas di: {z}  <- kirim file ini kalau masih gagal")
    log(f"\nSelesai: {ok}/{len(urls)} berhasil. Folder: {outdir}")
    return 0 if ok == len(urls) else 1


if __name__ == "__main__":
    sys.exit(main())
