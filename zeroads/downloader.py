import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from . import sfile_dl, malz
from .resolver import resolve as resolve_sfl

SUPPORTED_HOSTS = (
    "sfl.gl",
    "safelinku.com",
    "sfile.co",
    "sfile.mobi",
    "safefileku.com",
    "linkvertise.com",
    "link-target.net",
    "link-center.net",
    "link-hub.net",
    "direct-link.net",
)

class UnsupportedUrl(ValueError):
    pass

class DownloadFailure(RuntimeError):
    def __init__(self, message, manual_url=None):
        super().__init__(message)
        self.manual_url = manual_url

def _log_timing(stage, started, outcome, requests=None):
    fields = [
        "TIMING",
        f"stage={stage}",
        f"outcome={outcome}",
        f"elapsed_ms={(time.perf_counter() - started) * 1000:.1f}",
    ]
    if requests is not None:
        fields.append(f"requests={requests}")
    try:
        print(" ".join(fields), flush=True)
    except Exception:
        pass

def is_supported_url(value):
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme in ("http", "https")
            and not parsed.username
            and not parsed.password
            and any(host == domain or host.endswith("." + domain) for domain in SUPPORTED_HOSTS)
        )
    except ValueError:
        return False

def resolve_download(value):
    if not is_supported_url(value):
        raise UnsupportedUrl(
            "URL tidak didukung. Gunakan tautan sfl.gl, safelinku.com, "
            "sfile.co, sfile.mobi, safefileku.com, atau Linkvertise."
        )

    parsed = urlsplit(value)
    start_url = value
    manual_url = None

    # 1. sfl.gl -> Vercel/Resolver lokal
    if (parsed.hostname or "").lower().endswith("sfl.gl"):
        slug = value.rstrip("/").split("/")[-1]
        if not slug:
            raise DownloadFailure("Tautan sfl.gl tidak memiliki kode.")
        resolver_started = time.perf_counter()
        try:
            manual_url = resolve_sfl(slug)
        except Exception as error:
            _log_timing("sfl_resolver", resolver_started, type(error).__name__)
            raise DownloadFailure(str(error)) from error
        _log_timing("sfl_resolver", resolver_started, "success")
        raise DownloadFailure("Link asli ditemukan.", manual_url=manual_url)

    # 2. Linkvertise -> Malz
    host = (parsed.hostname or "").lower()
    if any(lv in host for lv in ("linkvertise.com", "link-target.net", "link-center.net", "link-hub.net", "direct-link.net")):
        lv_started = time.perf_counter()
        try:
            final_url = malz.resolve(value)
            if final_url:
                _log_timing("linkvertise", lv_started, "success")
                raise DownloadFailure("Link asli ditemukan.", manual_url=final_url)
            else:
                raise DownloadFailure("Gagal memproses Linkvertise via Malz.", manual_url=None)
        except DownloadFailure:
            raise
        except Exception as error:
            _log_timing("linkvertise", lv_started, type(error).__name__)
            raise DownloadFailure(f"Error Linkvertise: {str(error)}")

    # 3. Sfile / Safefileku -> Crawler lokal
    client = sfile_dl.Client(capture_trace=False, timing=True)
    client.gateway = sfile_dl.host_kind(urlsplit(start_url).hostname) != "file"
    args = SimpleNamespace(debug=False, wait=0.25, maxwait=15.0)
    crawler_started = time.perf_counter()
    try:
        found = sfile_dl.resolve(client, start_url, None, args, {(start_url, None)})
    except Exception as error:
        _log_timing("sfile_crawler", crawler_started, type(error).__name__, client.requests)
        raise
    _log_timing(
        "sfile_crawler",
        crawler_started,
        "success" if found else "not_found",
        client.requests,
    )
    if not found:
        fallback = client.goal_page or manual_url
        message = (
            "Tautan asli Safefileku ditemukan. Lanjutkan sendiri di browser."
            if fallback
            else "Tautan tidak dapat diproses. Silakan coba lagi."
        )
        raise DownloadFailure(message, fallback)

    response, _referer = found
    final_url = response.geturl()
    return response, {
        "file_name": sfile_dl.pick_filename(response, final_url),
        "file_size": sfile_dl.total_size(response),
        "content_type": response.headers.get("Content-Type", "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        or "application/octet-stream",
    }
