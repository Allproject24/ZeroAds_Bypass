import os
import sys
import time
from pathlib import Path
from threading import Lock
from urllib.parse import quote

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
sys.path.insert(0, str(ROOT))

from zeroads.downloader import DownloadFailure, UnsupportedUrl, resolve_download

app = Flask(__name__, static_folder=None)
download_lock = Lock()


def _log_timing(stage, started, outcome, **metrics):
    fields = [
        "TIMING",
        f"stage={stage}",
        f"outcome={outcome}",
        f"elapsed_ms={(time.perf_counter() - started) * 1000:.1f}",
    ]
    fields.extend(f"{key}={value}" for key, value in metrics.items())
    try:
        print(" ".join(fields), flush=True)
    except Exception:
        pass  # log tidak boleh menggagalkan permintaan atau menahan kunci unduhan


@app.get("/api/healthz")
@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.post("/api/downloads")
@app.post("/downloads")
@app.post("/api/index.py")
@app.post("/index.py")
def downloads():
    body = request.get_json(silent=True) or {}
    url = body.get("url", "")
    if not isinstance(url, str) or not url.strip():
        return jsonify(error="Masukkan tautan yang akan diproses."), 400
    url = url.strip()
    if len(url) > 2048:
        return jsonify(error="Tautan ini melebihi batas 2.048 karakter."), 400
    if not download_lock.acquire(blocking=False):
        return jsonify(error="Unduhan lain sedang diproses. Coba lagi sebentar."), 429

    resolution_started = time.perf_counter()
    try:
        file_response, result = resolve_download(url)
    except UnsupportedUrl as error:
        _log_timing("api_resolve", resolution_started, "unsupported_url")
        download_lock.release()
        return jsonify(error=str(error)), 400
    except DownloadFailure as error:
        _log_timing(
            "api_resolve",
            resolution_started,
            "blocked" if error.manual_url else "failed",
        )
        download_lock.release()
        return (
            jsonify(
                status="blocked" if error.manual_url else "failed",
                error=str(error),
                manualUrl=error.manual_url,
            ),
            200,
        )
    except Exception as error:
        _log_timing("api_resolve", resolution_started, "error")
        download_lock.release()
        return jsonify(error=str(error) or "Unduhan tidak dapat diproses."), 502
    _log_timing("api_resolve", resolution_started, "success")

    max_bytes = (250 if os.environ.get("VERCEL") == "1" else 500) * 1024 * 1024
    if result["file_size"] and result["file_size"] > max_bytes:
        file_response.close()
        download_lock.release()
        return jsonify(error="Ukuran file melebihi batas unduhan."), 413

    headers = {
        "Content-Disposition": "attachment; filename*=UTF-8''"
        + quote(result["file_name"], safe=""),
        "Cache-Control": "no-store, no-cache, must-revalidate, no-transform",
        "X-Accel-Buffering": "no",
        "X-File-Name": quote(result["file_name"], safe=""),
        "X-File-Size": str(result["file_size"]),
    }
    if result["file_size"]:
        headers["Content-Length"] = str(result["file_size"])

    def file_chunks():
        stream_started = time.perf_counter()
        bytes_sent = 0
        completed = False
        try:
            while True:
                chunk = file_response.read(64 * 1024)
                if not chunk:
                    completed = True
                    break
                bytes_sent += len(chunk)
                yield chunk
        finally:
            _log_timing(
                "file_stream",
                stream_started,
                "complete" if completed else "interrupted",
                bytes=bytes_sent,
            )
            file_response.close()
            download_lock.release()

    return Response(
        stream_with_context(file_chunks()),
        status=200,
        mimetype=result["content_type"],
        headers=headers,
        direct_passthrough=True,
    )


@app.get("/")
def home():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(PUBLIC, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
