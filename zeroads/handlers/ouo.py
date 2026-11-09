import os
import requests
from ..errors import DownloadFailure

# Ambil API Key dari environment variable, jangan di-hardcode
API_KEY = os.environ.get("KISALINKATLA_API_KEY")
API_URL = "https://api.kisalinkatla.com/resolve"

def process(url):
    if not API_KEY:
        raise DownloadFailure(
            "API Key untuk KısaLinkAtla belum di-set. "
            "Tambahkan environment variable KISALINKATLA_API_KEY.",
            manual_url=None
        )

    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }
    payload = {"url": url}

    try:
        r = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        data = r.json()

        if data.get("status") == "success" and data.get("result_url"):
            final_url = data["result_url"]
            raise DownloadFailure("Link asli ditemukan.", manual_url=final_url)
        else:
            # Ambil pesan error dari API jika ada
            error_msg = data.get("message", "Gagal memproses Ouo.io via KısaLinkAtla.")
            raise DownloadFailure(error_msg, manual_url=None)

    except requests.RequestException:
        raise DownloadFailure("Gagal terhubung ke API KısaLinkAtla.", manual_url=None)
