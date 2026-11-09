from urllib.parse import urlsplit
from .errors import UnsupportedUrl, DownloadFailure
from .handlers import sfl, linkvertise, sfile, ouo

SUPPORTED_HOSTS = (
    "sfl.gl", "safelinku.com", "sfile.co", "sfile.mobi", "safefileku.com",
    "linkvertise.com", "link-target.net", "link-center.net", "link-hub.net", "direct-link.net",
    "mediafire.com", "drive.google.com", "ouo.io", "ouo.press" # Tambahan direct link
)

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

    host = (urlsplit(value).hostname or "").lower()

    # --- POLISI LALU LINTAS ---
    if host.endswith("sfl.gl"):
        return sfl.process(value)
    elif any(lv in host for lv in ("linkvertise.com", "link-target.net", "link-center.net", "link-hub.net", "direct-link.net")):
        return linkvertise.process(value)
    elif any(h in host for h in ("mediafire.com", "drive.google.com", "ouo.io", "ouo.press")):
        # Kalau user nempel link MediaFire, langsung kasih tombol Copy/Open
        raise DownloadFailure("Link asli ditemukan.", manual_url=value)
    else:
        return sfile.process(value)
