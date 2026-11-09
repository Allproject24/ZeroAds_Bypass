import requests

# API publik bypass.vip: sudah menangani Cloudflare + Angular Linkvertise
BYPASS_VIP_URL = "https://api.bypass.vip/"

def resolve(url):
    """Kirim URL Linkvertise ke bypass.vip, kembalikan link tujuan atau None."""
    try:
        r = requests.post(
            BYPASS_VIP_URL,
            data={"url": url},
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"},
            timeout=30,
        )
        data = r.json()
        if data.get("status") == "success":
            result = data.get("result", "")
            if result.startswith("http"):
                print(f"TIMING stage=lv_success url={result}", flush=True)
                return result
        print(f"TIMING stage=lv_err msg={data.get('message', 'unknown')}", flush=True)
        return None
    except Exception as e:
        print(f"TIMING stage=lv_err exception={str(e)}", flush=True)
        return None
